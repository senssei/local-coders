"""Unified OpenAI-compatible /v1 client for local_coder."""

import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable

import requests

from .healing import heal_code_iterative
from .prompts import (
    build_code_prompt,
    build_heal_prompt,
    build_refactor_prompt,
    build_review_prompt,
    build_test_prompt,
    extract_code_block,
)
from .router import MODEL_PROFILES, EngineRouter
from .telemetry import calculate_savings
from .types import CompletionResult, EngineInfo, EngineType

DEFAULT_MAX_TOKENS = 4096

_TEST_DEF = re.compile(r"^\s*(?:async\s+def\s+|def\s+)test_|^class\s+Test", re.MULTILINE)


def _requires_tests(code: str) -> str | None:
    """Semantic check for generated test suites: a file without any test is not a fix."""
    return None if _TEST_DEF.search(code) else "no test functions (def test_*) or Test classes found"


class UnifiedLocalCoderClient:
    """Unified client for Prism, Ollama, and Microsoft Foundry Local."""

    def __init__(self, default_engine: EngineType | str | None = None, timeout_sec: int = 120):
        """``default_engine`` falls back to the ``LOCAL_CODER_ENGINE`` environment variable, then to auto."""
        self.router = EngineRouter()
        chosen = default_engine or os.environ.get("LOCAL_CODER_ENGINE") or EngineType.AUTO
        try:
            self.default_engine = EngineType(chosen.lower()) if isinstance(chosen, str) else chosen
        except ValueError:
            valid = ", ".join(t.value for t in EngineType)
            raise ValueError(f"Unknown engine {chosen!r}; expected one of: {valid}") from None
        self.timeout_sec = timeout_sec

    def resolve_engine_and_model(
        self,
        engine: EngineType | str | None = None,
        profile: str | None = None,
        model: str | None = None,
    ) -> tuple[EngineInfo, str]:
        """Resolve the target engine and best matching model name."""
        target_engine_info = self.router.resolve_target_engine(engine or self.default_engine)
        engine_key = target_engine_info.engine_type.value

        if model:
            # Check if model is an installed model or has a close alias
            for installed in target_engine_info.installed_models:
                if model.lower() in installed.lower():
                    return target_engine_info, installed
            return target_engine_info, model

        # Resolve from profile
        prof = (profile or "coding").lower()
        if prof in MODEL_PROFILES:
            configured_model = MODEL_PROFILES[prof].get(engine_key)
            if configured_model:
                for installed in target_engine_info.installed_models:
                    if configured_model.lower() in installed.lower():
                        return target_engine_info, installed
                return target_engine_info, configured_model

        # Fallback to first available installed model or default
        if target_engine_info.installed_models:
            return target_engine_info, target_engine_info.installed_models[0]

        return target_engine_info, "qwen2.5-coder:7b"

    def complete(
        self,
        messages: list[dict[str, str]],
        engine: EngineType | str | None = None,
        profile: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> CompletionResult:
        """Send chat completion request to the resolved local engine."""
        engine_info, target_model = self.resolve_engine_and_model(engine, profile, model)

        url = f"{engine_info.base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        t0 = time.perf_counter()
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout_sec)
        except requests.exceptions.RequestException as e:
            # Attempt failover to backup engine if in AUTO mode
            if (engine or self.default_engine) == EngineType.AUTO:
                backup_engines = self.router.failover_candidates(engine_info)
                if backup_engines:
                    backup = backup_engines[0]
                    sys.stderr.write(
                        f"  ⚠️ Warning: {engine_info.name} failed ({e}). Auto-failing over to {backup.name}...\n"
                    )
                    sys.stderr.flush()
                    return self.complete(
                        messages=messages,
                        engine=backup.engine_type,
                        profile=profile,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
            raise ConnectionError(f"Failed connecting to {engine_info.name} at {url}: {e}") from e

        duration = max(time.perf_counter() - t0, 0.001)

        if resp.status_code != 200:
            # Handle Microsoft Foundry auto-loading if model not resident
            if "not loaded" in resp.text.lower() and engine_info.engine_type in (EngineType.FOUNDRY, EngineType.PRISM):
                sys.stderr.write(f"  [{engine_info.name}] Loading model '{target_model}' into memory...\n")
                sys.stderr.flush()
                try:
                    subprocess.run(["foundry", "model", "load", target_model], capture_output=True, timeout=120)
                    resp = requests.post(url, json=payload, timeout=self.timeout_sec)
                except Exception:
                    pass

        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code} from {engine_info.name} ({url}): {resp.text}")

        data = resp.json()
        choices = data.get("choices", [])
        content = choices[0].get("message", {}).get("content", "") if choices else ""

        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", len(json.dumps(messages)) // 4)
        completion_tokens = usage.get("completion_tokens", len(content) // 4)
        total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)

        tok_per_sec = completion_tokens / duration if duration > 0 else 0.0
        saved_tokens, saved_usd = calculate_savings(prompt_tokens, completion_tokens)

        return CompletionResult(
            content=content,
            model=target_model,
            engine=engine_info.name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            duration_s=round(duration, 2),
            tokens_per_sec=round(tok_per_sec, 1),
            saved_tokens=saved_tokens,
            saved_usd=saved_usd,
            finish_reason=(choices[0].get("finish_reason") or "") if choices else "",
            raw_response=data,
        )

    def _generate_python(
        self,
        messages: list[dict[str, str]],
        *,
        engine: EngineType | str | None,
        profile: str,
        model: str | None,
        self_heal: bool,
        max_retries: int,
        max_tokens: int,
        extra_check: Callable[[str], str | None] | None = None,
    ) -> tuple[str, CompletionResult]:
        """Complete ``messages``, extract the Python block, and optionally AST-heal it."""
        res = self.complete(
            messages, engine=engine, profile=profile, model=model, temperature=0.1, max_tokens=max_tokens
        )
        raw_code = extract_code_block(res.content, "python")

        if not self_heal:
            return raw_code, res

        def heal_fn(invalid_code: str, err: str) -> str:
            heal_res = self.complete(
                build_heal_prompt(invalid_code, err),
                engine=engine,
                profile=profile,
                model=model,
                temperature=0.0,
                max_tokens=max_tokens,
            )
            return extract_code_block(heal_res.content, "python")

        final_code, _ = heal_code_iterative(raw_code, heal_fn, max_retries=max_retries, extra_check=extra_check)
        return final_code, res

    def generate_code(
        self,
        task: str,
        context_files: dict[str, str] | None = None,
        engine: EngineType | str | None = None,
        model: str | None = None,
        profile: str = "coding",
        self_heal: bool = True,
        max_retries: int = 2,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> tuple[str, CompletionResult]:
        """Generate Python code with optional automated AST self-healing."""
        return self._generate_python(
            build_code_prompt(task, context_files),
            engine=engine,
            profile=profile,
            model=model,
            self_heal=self_heal,
            max_retries=max_retries,
            max_tokens=max_tokens,
        )

    def generate_tests(
        self,
        source_code: str,
        file_path: str,
        framework: str = "pytest",
        engine: EngineType | str | None = None,
        model: str | None = None,
        self_heal: bool = True,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> tuple[str, CompletionResult]:
        """Generate automated unit tests."""
        return self._generate_python(
            build_test_prompt(source_code, file_path, framework),
            engine=engine,
            profile="coding",
            model=model,
            self_heal=self_heal,
            max_retries=2,
            max_tokens=max_tokens,
            extra_check=_requires_tests,
        )

    def review_code(
        self,
        source_code: str,
        file_path: str,
        focus: str | None = None,
        engine: EngineType | str | None = None,
        model: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> CompletionResult:
        """Perform security and architectural code review."""
        messages = build_review_prompt(source_code, file_path, focus)
        return self.complete(
            messages, engine=engine, profile="reasoning", model=model, temperature=0.2, max_tokens=max_tokens
        )

    def refactor_code(
        self,
        source_code: str,
        file_path: str,
        type_hints: bool = True,
        docstrings: bool = True,
        engine: EngineType | str | None = None,
        model: str | None = None,
        self_heal: bool = True,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> tuple[str, CompletionResult]:
        """Refactor code with strict type hints and docstrings."""
        return self._generate_python(
            build_refactor_prompt(source_code, file_path, type_hints, docstrings),
            engine=engine,
            profile="coding",
            model=model,
            self_heal=self_heal,
            max_retries=2,
            max_tokens=max_tokens,
        )

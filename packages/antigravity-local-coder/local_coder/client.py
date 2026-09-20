"""Unified OpenAI-compatible /v1 client for local_coder."""

import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Sequence

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
from .routing import RouteContext
from .telemetry import calculate_savings
from .types import CompletionResult, EngineInfo, EngineType

DEFAULT_MAX_TOKENS = 4096
# Ollama's OpenAI-compatible /v1 endpoint ignores num_ctx, so Ollama is called natively. The window must hold the
# prompt *and* up to max_tokens of output, so it is larger than max_tokens.
DEFAULT_NUM_CTX = 8192

EngineSpec = EngineType | str | Sequence[EngineType | str]

_FOUNDRY_SUFFIX = re.compile(r"-(?:generic-cpu|generic-gpu|cuda|directml)(?::\d+)?$")

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
        self.num_ctx = int(os.environ.get("LOCAL_CODER_NUM_CTX") or DEFAULT_NUM_CTX)
        self._announced: set[tuple[str, int]] = set()

    def _announce_route(self, info: EngineInfo) -> None:
        """Say once per rule why a routing exception picked this engine (AUTO mode only)."""
        decision = self.router.last_decision
        if decision is None or decision.rule is None:
            return
        key = (decision.rule.source, decision.rule.index)
        if key not in self._announced:
            self._announced.add(key)
            sys.stderr.write(f"  [route] {info.name}: {decision.describe()}\n")
            sys.stderr.flush()

    @staticmethod
    def match_installed_model(info: EngineInfo, name: str) -> str | None:
        """Map a requested model name or alias onto an id the engine actually serves, if any."""
        lowered = name.lower()
        if lowered in info.model_aliases:
            return info.model_aliases[lowered]
        cleaned = re.sub(r"-instruct$", "", _FOUNDRY_SUFFIX.sub("", lowered))
        if cleaned in info.model_aliases:
            return info.model_aliases[cleaned]
        for installed in info.installed_models:
            if lowered == installed.lower():
                return installed
        for installed in info.installed_models:
            if lowered in installed.lower():
                return installed
        return None

    def resolve_engine_and_model(
        self,
        engine: EngineSpec | None = None,
        profile: str | None = None,
        model: str | None = None,
        task: str | None = None,
    ) -> tuple[EngineInfo, str]:
        """Resolve the target engine and best matching model name."""
        route = RouteContext(task=task, profile=profile, model=model)
        target_engine_info = self.router.resolve_target_engine(engine or self.default_engine, route)
        self._announce_route(target_engine_info)
        engine_key = target_engine_info.engine_type.value

        if model:
            return target_engine_info, self.match_installed_model(target_engine_info, model) or model

        # Resolve from profile
        prof = (profile or "coding").lower()
        if prof in MODEL_PROFILES:
            configured_model = MODEL_PROFILES[prof].get(engine_key)
            if configured_model:
                return target_engine_info, self.match_installed_model(
                    target_engine_info, configured_model
                ) or configured_model

        # Fallback to first available installed model or default
        if target_engine_info.installed_models:
            return target_engine_info, target_engine_info.installed_models[0]

        return target_engine_info, "qwen2.5-coder:7b"

    @staticmethod
    def _ollama_native_url(info: EngineInfo) -> str:
        base = info.base_url.rstrip("/")
        return f"{base[: -len('/v1')] if base.endswith('/v1') else base}/api/chat"

    def _build_request(
        self,
        info: EngineInfo,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, dict]:
        """URL and JSON payload for ``info``: native /api/chat for Ollama, OpenAI /chat/completions otherwise."""
        if info.engine_type == EngineType.OLLAMA:
            payload = {
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": temperature, "num_ctx": self.num_ctx, "num_predict": max_tokens},
            }
            return self._ollama_native_url(info), payload
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        return f"{info.base_url.rstrip('/')}/chat/completions", payload

    @staticmethod
    def _parse_response(info: EngineInfo, data: dict, messages: list[dict[str, str]]) -> dict:
        """Normalise an engine reply to content, token counts, finish reason and engine-reported speed."""
        if info.engine_type == EngineType.OLLAMA:
            content = data.get("message", {}).get("content", "")
            prompt_tokens = data.get("prompt_eval_count", len(json.dumps(messages)) // 4)
            completion_tokens = data.get("eval_count", len(content) // 4)
            eval_ns = data.get("eval_duration", 0)
            reported_tps = completion_tokens / (eval_ns / 1e9) if eval_ns > 0 else 0.0
            return {
                "content": content,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "finish_reason": data.get("done_reason") or "",
                "reported_tps": reported_tps,
            }

        choices = data.get("choices", [])
        content = choices[0].get("message", {}).get("content", "") if choices else ""
        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", len(json.dumps(messages)) // 4)
        completion_tokens = usage.get("completion_tokens", len(content) // 4)
        return {
            "content": content,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "finish_reason": (choices[0].get("finish_reason") or "") if choices else "",
            # Prism reports pure decode speed, which excludes model load time
            "reported_tps": float(data.get("telemetry", {}).get("decode_tok_per_sec") or 0.0),
        }

    def complete(
        self,
        messages: list[dict[str, str]],
        engine: EngineSpec | None = None,
        profile: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        task: str | None = None,
    ) -> CompletionResult:
        """Send chat completion request to the resolved local engine."""
        engine_info, target_model = self.resolve_engine_and_model(engine, profile, model, task)
        url, payload = self._build_request(engine_info, target_model, messages, temperature, max_tokens)

        t0 = time.perf_counter()
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout_sec)
        except requests.exceptions.RequestException as e:
            # Attempt failover to backup engine if in AUTO mode
            self.router.mark_failed(engine_info.engine_type)
            if (engine or self.default_engine) == EngineType.AUTO:
                backup_engines = self.router.failover_candidates(
                    engine_info, RouteContext(task=task, profile=profile, model=model)
                )
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
                        task=task,
                    )
            raise ConnectionError(f"Failed connecting to {engine_info.name} at {url}: {e}") from e

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

        self.router.mark_ok(engine_info.engine_type)
        duration = max(time.perf_counter() - t0, 0.001)

        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code} from {engine_info.name} ({url}): {resp.text}")

        data = resp.json()
        parsed = self._parse_response(engine_info, data, messages)
        prompt_tokens = parsed["prompt_tokens"]
        completion_tokens = parsed["completion_tokens"]

        # Prefer the engine's own decode speed; wall time also counts model loading and would understate it
        tok_per_sec = parsed["reported_tps"] or completion_tokens / duration
        saved_tokens, saved_usd = calculate_savings(prompt_tokens, completion_tokens)

        return CompletionResult(
            content=parsed["content"],
            model=target_model,
            engine=engine_info.name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            duration_s=round(duration, 2),
            tokens_per_sec=round(tok_per_sec, 1),
            saved_tokens=saved_tokens,
            saved_usd=saved_usd,
            finish_reason=parsed["finish_reason"],
            raw_response=data,
        )

    def _generate_python(
        self,
        messages: list[dict[str, str]],
        *,
        engine: EngineSpec | None,
        profile: str,
        model: str | None,
        self_heal: bool,
        max_retries: int,
        max_tokens: int,
        temperature: float,
        task: str,
        extra_check: Callable[[str], str | None] | None = None,
    ) -> tuple[str, CompletionResult]:
        """Complete ``messages``, extract the Python block, and optionally AST-heal it."""
        res = self.complete(
            messages,
            engine=engine,
            profile=profile,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            task=task,
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
                task=task,
            )
            return extract_code_block(heal_res.content, "python")

        final_code, _ = heal_code_iterative(raw_code, heal_fn, max_retries=max_retries, extra_check=extra_check)
        return final_code, res

    def generate_code(
        self,
        task: str,
        context_files: dict[str, str] | None = None,
        engine: EngineSpec | None = None,
        model: str | None = None,
        profile: str = "coding",
        self_heal: bool = True,
        max_retries: int = 2,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = 0.1,
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
            temperature=temperature,
            task="code",
        )

    def generate_tests(
        self,
        source_code: str,
        file_path: str,
        framework: str = "pytest",
        engine: EngineSpec | None = None,
        model: str | None = None,
        self_heal: bool = True,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = 0.1,
        instructions: str | None = None,
        profile: str = "coding",
    ) -> tuple[str, CompletionResult]:
        """Generate automated unit tests."""
        return self._generate_python(
            build_test_prompt(source_code, file_path, framework, instructions),
            engine=engine,
            profile=profile,
            model=model,
            self_heal=self_heal,
            max_retries=2,
            max_tokens=max_tokens,
            temperature=temperature,
            task="test",
            extra_check=_requires_tests,
        )

    def review_code(
        self,
        source_code: str,
        file_path: str,
        focus: str | None = None,
        engine: EngineSpec | None = None,
        model: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = 0.2,
        profile: str = "reasoning",
    ) -> CompletionResult:
        """Perform security and architectural code review."""
        messages = build_review_prompt(source_code, file_path, focus)
        return self.complete(
            messages,
            engine=engine,
            profile=profile,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            task="review",
        )

    def refactor_code(
        self,
        source_code: str,
        file_path: str,
        type_hints: bool = True,
        docstrings: bool = True,
        engine: EngineSpec | None = None,
        model: str | None = None,
        self_heal: bool = True,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = 0.1,
        instructions: str | None = None,
        profile: str = "coding",
    ) -> tuple[str, CompletionResult]:
        """Refactor code with strict type hints and docstrings."""
        return self._generate_python(
            build_refactor_prompt(source_code, file_path, type_hints, docstrings, instructions),
            engine=engine,
            profile=profile,
            model=model,
            self_heal=self_heal,
            max_retries=2,
            max_tokens=max_tokens,
            temperature=temperature,
            task="refactor",
        )

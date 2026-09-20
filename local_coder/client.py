"""Unified OpenAI-compatible /v1 client for local_coder."""

import dataclasses
import json
import os
import re
import shutil
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
    is_python,
    normalize_language,
)
from .router import MODEL_FALLBACKS, MODEL_PROFILES, EngineRouter
from .routing import RouteContext
from .telemetry import calculate_savings
from .types import CompletionResult, EngineInfo, EngineType

DEFAULT_MAX_TOKENS = 4096
# When the caller did not choose a limit and the output is cut off, the request is repeated once with a larger one.
AUTO_EXTEND_LIMIT = 16384
# Ollama's OpenAI-compatible /v1 endpoint ignores num_ctx, so Ollama is called natively. The window must hold the
# prompt *and* up to max_tokens of output, so it is larger than max_tokens.
DEFAULT_NUM_CTX = 8192

EngineSpec = EngineType | str | Sequence[EngineType | str]

_FOUNDRY_SUFFIX = re.compile(r"-(?:generic-cpu|generic-gpu|cuda|directml)(?::\d+)?$")

_INSTALL_HINTS = {
    EngineType.OLLAMA: "Pull it with `ollama pull <model>`.",
    EngineType.PRISM: "See `prism list`; fetch models with `prism pull`.",
    EngineType.FOUNDRY: "See `foundry model list`.",
}


class ModelNotInstalledError(RuntimeError):
    """The requested model (or every model a profile could use) is not installed on the engine."""


def _norm(name: str) -> str:
    """Compare model names across engines: ``qwen2.5-coder-7b`` and ``qwen2.5-coder:7b`` are the same model."""
    return re.sub(r"[^a-z0-9.]", "", name.lower())


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
        wanted = _norm(name)
        for installed in info.installed_models:
            if _norm(installed) == wanted:
                return installed
        if len(wanted) >= 6:
            for installed in info.installed_models:
                if wanted in _norm(installed):
                    return installed
        return None

    def _model_for_profile(self, info: EngineInfo, profile: str) -> str | None:
        """Best installed model for a profile on ``info``: the preferred one, else the first installed fallback."""
        key = info.engine_type.value
        preferred = MODEL_PROFILES[profile].get(key)
        if not preferred:
            return None
        candidates = [preferred, *MODEL_FALLBACKS.get(profile, {}).get(key, [])]
        if not info.installed_models:  # the engine did not tell us what it has; trust the preferred model
            return preferred
        for i, candidate in enumerate(candidates):
            found = self.match_installed_model(info, candidate)
            if found:
                if i > 0:
                    sys.stderr.write(
                        f"  [model] profile '{profile}' prefers {preferred} on {info.name}, which is not installed; "
                        f"using {found}\n"
                    )
                    sys.stderr.flush()
                return found
        raise ModelNotInstalledError(
            f"No model for profile '{profile}' is installed on {info.name} (looked for: {', '.join(candidates)}). "
            f"Installed: {', '.join(info.installed_models[:8])}. {_INSTALL_HINTS[info.engine_type]}"
        )

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

        if model:
            return target_engine_info, self.match_installed_model(target_engine_info, model) or model

        # Resolve from profile
        prof = (profile or "coding").lower()
        if prof in MODEL_PROFILES:
            chosen = self._model_for_profile(target_engine_info, prof)
            if chosen:
                return target_engine_info, chosen

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
            # the window must hold the prompt and the whole answer, or Ollama silently shifts the context
            needed = len(json.dumps(messages)) // 3 + max_tokens + 256
            num_ctx = min(max(self.num_ctx, needed), 32768)
            payload = {
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": temperature, "num_ctx": num_ctx, "num_predict": max_tokens},
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

        if resp.status_code != 200 and "not loaded" in resp.text.lower():
            resp = self._load_model_and_retry(engine_info, target_model, url, payload, resp)

        self.router.mark_ok(engine_info.engine_type)
        duration = max(time.perf_counter() - t0, 0.001)

        if resp.status_code != 200:
            if resp.status_code in (400, 404) and "not found" in resp.text.lower():
                raise ModelNotInstalledError(
                    f"Model '{target_model}' was not found on {engine_info.name}. "
                    f"Installed: {', '.join(engine_info.installed_models[:8]) or 'unknown'}. "
                    f"{_INSTALL_HINTS[engine_info.engine_type]}"
                )
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
            max_tokens=max_tokens,
            raw_response=data,
        )

    def _load_model_and_retry(
        self, info: EngineInfo, model: str, url: str, payload: dict, resp: requests.Response
    ) -> requests.Response:
        """Foundry Local only serves resident models, so load it with its CLI and repeat the request.

        Prism loads models itself, so its answer is returned as it is (the caller reports it).
        """
        if info.engine_type != EngineType.FOUNDRY:
            return resp
        foundry_bin = shutil.which("foundry")
        if not foundry_bin:
            raise RuntimeError(
                f"Model '{model}' is not loaded in Foundry Local and the 'foundry' CLI is not on PATH to load it: "
                f"{resp.text}"
            )
        sys.stderr.write(f"  [{info.name}] Loading model '{model}' into memory...\n")
        sys.stderr.flush()
        try:
            proc = subprocess.run([foundry_bin, "model", "load", model], capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"`foundry model load {model}` did not finish within 180 s") from None
        if proc.returncode != 0:
            raise RuntimeError(f"`foundry model load {model}` failed: {(proc.stderr or proc.stdout).strip()}")
        return requests.post(url, json=payload, timeout=self.timeout_sec)

    @staticmethod
    def _combine(primary: CompletionResult, extra: list[CompletionResult]) -> CompletionResult:
        """``primary`` with the cost of ``extra`` calls (healing retries, a larger-limit retry) added to its counters."""
        if not extra:
            return primary
        everything = [primary, *extra]
        prompt = sum(r.prompt_tokens for r in everything)
        completion = sum(r.completion_tokens for r in everything)
        saved_tokens, saved_usd = calculate_savings(prompt, completion)
        return dataclasses.replace(
            primary,
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion,
            duration_s=round(sum(r.duration_s for r in everything), 2),
            saved_tokens=saved_tokens,
            saved_usd=saved_usd,
        )

    def _complete_extendable(
        self, messages: list[dict[str, str]], max_tokens: int | None, **kwargs
    ) -> tuple[CompletionResult, int]:
        """Complete; if the caller left the limit at its default and the output was cut off, retry once with more.

        An explicit ``max_tokens`` is always respected. Returns the (combined) result and the limit finally used.
        """
        budget = max_tokens or DEFAULT_MAX_TOKENS
        res = self.complete(messages, max_tokens=budget, **kwargs)
        if res.truncated and max_tokens is None and budget < AUTO_EXTEND_LIMIT:
            bigger = min(budget * 2, AUTO_EXTEND_LIMIT)
            sys.stderr.write(f"  [retry] output hit the {budget}-token limit; retrying once with {bigger}\n")
            sys.stderr.flush()
            retry = self.complete(messages, max_tokens=bigger, **kwargs)
            return self._combine(retry, [res]), bigger
        return res, budget

    def _generate(
        self,
        messages: list[dict[str, str]],
        *,
        engine: EngineSpec | None,
        profile: str,
        model: str | None,
        self_heal: bool,
        max_retries: int,
        max_tokens: int | None,
        temperature: float,
        task: str,
        extra_check: Callable[[str], str | None] | None = None,
        language: str = "python",
    ) -> tuple[str, CompletionResult]:
        """Complete ``messages``, extract the code block, and (for Python only) optionally AST-heal it."""
        res, budget = self._complete_extendable(
            messages,
            max_tokens,
            engine=engine,
            profile=profile,
            model=model,
            temperature=temperature,
            task=task,
        )
        raw_code = extract_code_block(res.content, language)

        if not self_heal or not is_python(language):  # there is no syntax check for other languages
            return raw_code, res
        if res.truncated:
            # Asking the model to "fix" a file that was cut off mid-way cannot restore the missing part; it only
            # burns tokens and returns a shrunken candidate. The truncation warning already tells the caller.
            sys.stderr.write("  [Self-Healing] skipped: the output was cut off at the token limit\n")
            sys.stderr.flush()
            return raw_code, res

        heal_results: list[CompletionResult] = []

        def heal_fn(invalid_code: str, err: str) -> str:
            heal_res = self.complete(
                build_heal_prompt(invalid_code, err),
                engine=engine,
                profile=profile,
                model=model,
                temperature=0.0,
                max_tokens=budget,
                task=task,
            )
            heal_results.append(heal_res)
            return extract_code_block(heal_res.content, "python")

        final_code, _ = heal_code_iterative(raw_code, heal_fn, max_retries=max_retries, extra_check=extra_check)
        return final_code, self._combine(res, heal_results)

    def generate_code(
        self,
        task: str,
        context_files: dict[str, str] | None = None,
        engine: EngineSpec | None = None,
        model: str | None = None,
        profile: str = "coding",
        self_heal: bool = True,
        max_retries: int = 2,
        max_tokens: int | None = None,
        temperature: float = 0.1,
        language: str = "python",
    ) -> tuple[str, CompletionResult]:
        """Generate code (Python by default, with optional AST self-healing; other languages are returned unchecked)."""
        language = normalize_language(language)
        return self._generate(
            build_code_prompt(task, context_files, language),
            language=language,
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
        max_tokens: int | None = None,
        temperature: float = 0.1,
        instructions: str | None = None,
        profile: str = "coding",
    ) -> tuple[str, CompletionResult]:
        """Generate automated unit tests."""
        return self._generate(
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
        max_tokens: int | None = None,
        temperature: float = 0.2,
        profile: str = "reasoning",
    ) -> CompletionResult:
        """Perform security and architectural code review."""
        messages = build_review_prompt(source_code, file_path, focus)
        res, _ = self._complete_extendable(
            messages,
            max_tokens,
            engine=engine,
            profile=profile,
            model=model,
            temperature=temperature,
            task="review",
        )
        return res

    def refactor_code(
        self,
        source_code: str,
        file_path: str,
        type_hints: bool = True,
        docstrings: bool = True,
        engine: EngineSpec | None = None,
        model: str | None = None,
        self_heal: bool = True,
        max_tokens: int | None = None,
        temperature: float = 0.1,
        instructions: str | None = None,
        profile: str = "coding",
    ) -> tuple[str, CompletionResult]:
        """Refactor code with strict type hints and docstrings."""
        return self._generate(
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

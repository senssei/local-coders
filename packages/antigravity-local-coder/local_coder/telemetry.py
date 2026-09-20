"""Telemetry and cost savings calculations for local_coder."""

import os

from .types import CompletionResult

# Reference prices (USD per 1M tokens) for the "cloud tokens saved" estimate. They stand for a Sonnet-class frontier
# model and are a notional baseline, not a bill; override with LOCAL_CODER_PRICE_PROMPT / LOCAL_CODER_PRICE_COMPLETION.
REFERENCE_PROMPT_PRICE_PER_M = 3.00
REFERENCE_COMPLETION_PRICE_PER_M = 15.00


def _price(env_name: str, default: float) -> float:
    try:
        return float(os.environ.get(env_name) or default)
    except ValueError:
        return default


def calculate_savings(prompt_tokens: int, completion_tokens: int) -> tuple[int, float]:
    """Total tokens that did not go to a cloud model, and their notional cost at the reference prices."""
    prompt_price = _price("LOCAL_CODER_PRICE_PROMPT", REFERENCE_PROMPT_PRICE_PER_M)
    completion_price = _price("LOCAL_CODER_PRICE_COMPLETION", REFERENCE_COMPLETION_PRICE_PER_M)
    saved_usd = (prompt_tokens / 1_000_000) * prompt_price + (completion_tokens / 1_000_000) * completion_price
    return prompt_tokens + completion_tokens, saved_usd


def format_telemetry_banner(
    engine_name: str,
    model: str,
    tokens_per_sec: float,
    completion_tokens: int,
    duration_s: float,
    saved_tokens: int,
    saved_usd: float,
) -> str:
    """Format a standard telemetry footer banner."""
    return (
        f"[{engine_name}: {model} | {tokens_per_sec:.1f} tok/s | "
        f"{completion_tokens} tokens in {duration_s:.2f}s | "
        f"⚡ Saved {saved_tokens} cloud tokens (~${saved_usd:.4f})]"
    )


def format_result_banner(res: CompletionResult, max_tokens: int | None = None) -> str:
    """Telemetry footer for a completion, with a truncation warning when the output hit ``max_tokens``."""
    banner = format_telemetry_banner(
        res.engine,
        res.model,
        res.tokens_per_sec,
        res.completion_tokens,
        res.duration_s,
        res.saved_tokens,
        res.saved_usd,
    )
    if res.truncated:
        limit_value = res.max_tokens or max_tokens
        limit = f" ({limit_value})" if limit_value else ""
        banner += f"\n⚠️ Output truncated at the max_tokens limit{limit}; raise --max-tokens / max_tokens and retry."
    return banner

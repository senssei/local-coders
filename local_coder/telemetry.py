"""Telemetry and cost savings calculations for local_coder."""

# Standard frontier cloud model pricing (USD per 1M tokens)
# Claude 3.5 Sonnet / GPT-4o baseline
CLAUDE_35_SONNET_PROMPT_PRICE_PER_M = 3.00
CLAUDE_35_SONNET_COMPLETION_PRICE_PER_M = 15.00


def calculate_savings(prompt_tokens: int, completion_tokens: int) -> tuple[int, float]:
    """Calculate total cloud tokens saved and estimated USD savings against frontier models."""
    total_saved_tokens = prompt_tokens + completion_tokens
    prompt_cost = (prompt_tokens / 1_000_000) * CLAUDE_35_SONNET_PROMPT_PRICE_PER_M
    completion_cost = (completion_tokens / 1_000_000) * CLAUDE_35_SONNET_COMPLETION_PRICE_PER_M
    saved_usd = prompt_cost + completion_cost
    return total_saved_tokens, saved_usd


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

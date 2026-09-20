"""Type definitions and data structures for local_coder."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EngineType(str, Enum):
    AUTO = "auto"
    PRISM = "prism"
    OLLAMA = "ollama"
    FOUNDRY = "foundry"


@dataclass
class EngineInfo:
    name: str
    engine_type: EngineType
    base_url: str
    is_online: bool
    version: str = "unknown"
    hardware: str = "unknown"
    installed_models: list[str] = field(default_factory=list)
    latency_ms: float = 0.0


@dataclass
class CompletionResult:
    content: str
    model: str
    engine: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    duration_s: float = 0.0
    tokens_per_sec: float = 0.0
    saved_tokens: int = 0
    saved_usd: float = 0.0
    raw_response: dict[str, Any] = field(default_factory=dict)

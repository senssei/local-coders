"""Engine discovery, auto-routing, and hardware detection for local_coder."""

import json
import os
import platform
import shutil
import subprocess
import time
from urllib.parse import urlsplit

import requests

from .types import EngineInfo, EngineType

DEFAULT_PRISM_URL = "http://127.0.0.1:5272/v1"
DEFAULT_OLLAMA_V1_URL = "http://localhost:11434/v1"
FOUNDRY_DAEMON_JSON = os.path.expanduser("~/.foundry/daemon.json")

# Model aliases and cross-engine defaults
MODEL_PROFILES: dict[str, dict[str, str]] = {
    "coding": {
        "prism": "phi-4-mini",
        "ollama": "qwen2.5-coder:7b",
        "foundry": "phi-3.5-mini",
    },
    "fast": {
        "prism": "qwen3-0.6b",
        "ollama": "qwen2.5-coder:3b",
        "foundry": "qwen3-0.6b",
    },
    "reasoning": {
        "prism": "Phi-4-mini-instruct-generic-cpu-5:v5",
        "ollama": "llama3.1:8b",
        "foundry": "phi-4-mini",
    },
}


def normalize_ollama_host(raw: str | None) -> tuple[str, str]:
    """Turn an ``OLLAMA_HOST`` value into ``(native_host, openai_v1_url)``.

    Ollama accepts bare ``host``, ``host:port``, ``:port`` and ``0.0.0.0`` values without a scheme, and
    clients are expected to fill in ``http://`` and port 11434. A trailing ``/v1`` is tolerated.
    """
    value = (raw or "").strip() or "http://localhost:11434"
    if "://" not in value:
        value = f"http://{value}"
    parts = urlsplit(value)
    hostname = parts.hostname or "localhost"
    if hostname in ("0.0.0.0", "::"):  # bind-all address is not a valid connect target everywhere
        hostname = "127.0.0.1"
    if ":" in hostname:  # IPv6 literal
        hostname = f"[{hostname}]"
    host = f"{parts.scheme}://{hostname}:{parts.port or 11434}"
    path = parts.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[: -len("/v1")]
    host += path
    return host, f"{host}/v1"


def detect_system_hardware() -> str:
    """Detect local GPU hardware (NVIDIA RTX CUDA or Apple Silicon Metal)."""
    sys_name = platform.system().lower()
    if sys_name == "darwin":
        try:
            chip = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
            return f"Apple Silicon Metal ({chip})"
        except Exception:
            return "Apple Silicon Metal"

    # Check Linux / WSL2 NVIDIA GPU
    try:
        smi = shutil.which("nvidia-smi") or "/usr/lib/wsl/lib/nvidia-smi"
        if os.path.exists(smi):
            out = subprocess.check_output([smi, "--query-gpu=name,memory.total", "--format=csv,noheader"], text=True)
            first_line = out.strip().split("\n")[0]
            return f"NVIDIA CUDA ({first_line})"
    except Exception:
        pass

    return f"CPU ({platform.machine()})"


class EngineRouter:
    """Discovers local inference engines and routes completions across Prism, Ollama, and Foundry."""

    def __init__(self):
        self.hardware = detect_system_hardware()

    def discover_prism(self) -> EngineInfo:
        """Inspect Prism server status."""
        base_url = os.environ.get("PRISM_BASE_URL", DEFAULT_PRISM_URL).rstrip("/")
        models = []
        is_online = False
        latency = 0.0

        t0 = time.perf_counter()
        try:
            r = requests.get(f"{base_url}/models", timeout=1.0)
            latency = (time.perf_counter() - t0) * 1000
            if r.status_code == 200:
                is_online = True
                data = r.json()
                models = [m.get("id") for m in data.get("data", []) if m.get("id")]
        except Exception:
            pass

        return EngineInfo(
            name="Prism",
            engine_type=EngineType.PRISM,
            base_url=base_url,
            is_online=is_online,
            version="prism-local 0.1.0 (CUDA)" if is_online else "offline",
            hardware=self.hardware,
            installed_models=models,
            latency_ms=round(latency, 2),
        )

    def discover_ollama(self) -> EngineInfo:
        """Inspect Ollama server status (using OpenAI /v1 endpoint)."""
        host, base_url = normalize_ollama_host(os.environ.get("OLLAMA_HOST"))
        models = []
        is_online = False
        latency = 0.0

        t0 = time.perf_counter()
        try:
            # Query Ollama native /api/tags or /v1/models
            r = requests.get(f"{host}/api/tags", timeout=1.0)
            latency = (time.perf_counter() - t0) * 1000
            if r.status_code == 200:
                is_online = True
                data = r.json()
                models = [m.get("name") for m in data.get("models", []) if m.get("name")]
        except Exception:
            pass

        return EngineInfo(
            name="Ollama",
            engine_type=EngineType.OLLAMA,
            base_url=base_url,
            is_online=is_online,
            version="llama.cpp" if is_online else "offline",
            hardware=self.hardware,
            installed_models=models,
            latency_ms=round(latency, 2),
        )

    def discover_foundry(self) -> EngineInfo:
        """Inspect Microsoft Foundry Local status."""
        env_url = os.environ.get("FOUNDRY_BASE_URL")
        base_url = env_url.rstrip("/") if env_url else ""
        if not base_url and os.path.exists(FOUNDRY_DAEMON_JSON):
            try:
                with open(FOUNDRY_DAEMON_JSON, encoding="utf-8") as f:
                    d = json.load(f)
                    urls = d.get("web_urls", [])
                    if urls:
                        base = urls[0].rstrip("/")
                        base_url = f"{base}/v1" if not base.endswith("/v1") else base
            except Exception:
                pass

        if not base_url:
            base_url = "http://127.0.0.1:5272/v1"

        models = []
        is_online = False
        latency = 0.0

        t0 = time.perf_counter()
        try:
            r = requests.get(f"{base_url}/models", timeout=1.0)
            latency = (time.perf_counter() - t0) * 1000
            if r.status_code == 200:
                is_online = True
                data = r.json()
                models = [m.get("id") for m in data.get("data", []) if m.get("id")]
        except Exception:
            pass

        return EngineInfo(
            name="Microsoft Foundry Local",
            engine_type=EngineType.FOUNDRY,
            base_url=base_url,
            is_online=is_online,
            version="ONNX Runtime GenAI" if is_online else "offline",
            hardware=self.hardware,
            installed_models=models,
            latency_ms=round(latency, 2),
        )

    def list_all_engines(self) -> list[EngineInfo]:
        """Scan and return status of all three local inference engines."""
        return [self.discover_prism(), self.discover_ollama(), self.discover_foundry()]

    def resolve_target_engine(self, requested_engine: EngineType | str = EngineType.AUTO) -> EngineInfo:
        """Select the best available engine.

        Priority in AUTO mode:
        1. On Linux/WSL2 with NVIDIA GPU: Prism (direct CUDA EP) -> Ollama (CUDA) -> Foundry.
        2. On macOS (Apple Silicon Metal): Ollama (native Metal) -> Foundry -> Prism.
        """
        req = EngineType(requested_engine.lower()) if isinstance(requested_engine, str) else requested_engine

        if req == EngineType.PRISM:
            info = self.discover_prism()
            if info.is_online:
                return info
            raise ConnectionError(
                f"Prism engine requested but offline at {info.base_url}. Start it with 'prism serve'."
            )

        if req == EngineType.OLLAMA:
            info = self.discover_ollama()
            if info.is_online:
                return info
            raise ConnectionError(
                f"Ollama engine requested but offline at {info.base_url}. Start it with 'ollama serve'."
            )

        if req == EngineType.FOUNDRY:
            info = self.discover_foundry()
            if info.is_online:
                return info
            raise ConnectionError(
                f"Foundry Local requested but offline at {info.base_url}. Start it with 'foundry server start'."
            )

        # AUTO mode:
        engines = self.list_all_engines()
        ranked = self.rank_online(engines)

        # If none online, return the first one with informative status
        return ranked[0] if ranked else engines[0]

    @staticmethod
    def priority() -> list[EngineType]:
        """Engine preference order for AUTO mode on the current platform."""
        if platform.system().lower() == "darwin":
            return [EngineType.OLLAMA, EngineType.FOUNDRY, EngineType.PRISM]
        # Linux / WSL2 priority
        return [EngineType.PRISM, EngineType.OLLAMA, EngineType.FOUNDRY]

    def rank_online(self, engines: list[EngineInfo]) -> list[EngineInfo]:
        """Online engines in priority order, one per distinct endpoint.

        Prism and Foundry Local share ``127.0.0.1:5272`` by default, so both can report the same server as online;
        only the higher-priority one is kept so failover never lands on the endpoint that just failed.
        """
        order = {t: i for i, t in enumerate(self.priority())}
        ranked: list[EngineInfo] = []
        seen_urls: set[str] = set()
        for eng in sorted((e for e in engines if e.is_online), key=lambda e: order.get(e.engine_type, len(order))):
            url = eng.base_url.rstrip("/")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            ranked.append(eng)
        return ranked

    def failover_candidates(self, failed: EngineInfo) -> list[EngineInfo]:
        """Online engines on a different endpoint than ``failed``, best first."""
        failed_url = failed.base_url.rstrip("/")
        return [e for e in self.rank_online(self.list_all_engines()) if e.base_url.rstrip("/") != failed_url]

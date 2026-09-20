"""Engine discovery, auto-routing, and hardware detection for local_coder."""

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from collections.abc import Sequence
from urllib.parse import urlsplit

import requests

from .models import EngineInfo, EngineType
from .routing import RouteContext, RouteDecision, RoutingPolicy

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


# Tried in order, after MODEL_PROFILES' preferred model, when that model is not installed on the engine.
MODEL_FALLBACKS: dict[str, dict[str, list[str]]] = {
    "coding": {
        "prism": ["phi-3.5-mini"],
        "ollama": ["qwen2.5-coder:14b", "qwen2.5-coder:3b"],
        "foundry": ["phi-4-mini"],
    },
    "fast": {
        "prism": ["phi-4-mini"],
        "ollama": ["qwen2.5-coder:7b"],
        "foundry": ["phi-3.5-mini"],
    },
    "reasoning": {
        "prism": ["phi-4-mini"],
        "ollama": ["qwen2.5-coder:14b", "qwen2.5-coder:7b"],
        "foundry": ["phi-3.5-mini"],
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


def parse_openai_models(data: dict) -> tuple[list[str], dict[str, str]]:
    """Extract model ids and alias map from an OpenAI-style ``/models`` payload.

    Foundry Local reports a ``parent`` alias per model (e.g. ``phi-3.5-mini``); Prism reports none.
    """
    ids: list[str] = []
    aliases: dict[str, str] = {}
    for item in data.get("data", []):
        mid = item.get("id")
        if not mid:
            continue
        ids.append(mid)
        parent = item.get("parent")
        aliases[mid.lower()] = parent or mid
        if parent:
            aliases[parent.lower()] = parent
    return ids, aliases


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

    def __init__(self, policy: RoutingPolicy | None = None):
        self.hardware = detect_system_hardware()
        # Off by default so AUTO routing never launches daemons; the foundry-coder entry points opt in.
        self.autostart_foundry = False
        # Routing exceptions (validated now, so a bad file fails at start-up); only consulted in AUTO mode.
        self.policy = policy or RoutingPolicy.load()
        self.last_decision: RouteDecision | None = None
        # An engine that just failed is skipped for a while so retries and healing loops do not wait on it again.
        self.cooldown_sec = float(os.environ.get("LOCAL_CODER_COOLDOWN") or 30)
        self._failed_at: dict[EngineType, float] = {}
        # Discovery is a few HTTP calls; AUTO routing and failover would otherwise repeat them on every request,
        # including each retry of the self-healing loop. 0 disables the cache.
        self.discovery_ttl = float(os.environ.get("LOCAL_CODER_DISCOVERY_TTL") or 5)
        self._discovered: tuple[float, list[EngineInfo]] | None = None

    def discover_prism(self) -> EngineInfo:
        """Inspect Prism server status."""
        base_url = os.environ.get("PRISM_BASE_URL", DEFAULT_PRISM_URL).rstrip("/")
        models: list[str] = []
        aliases: dict[str, str] = {}
        is_online = False
        latency = 0.0

        t0 = time.perf_counter()
        try:
            r = requests.get(f"{base_url}/models", timeout=1.0)
            latency = (time.perf_counter() - t0) * 1000
            if r.status_code == 200:
                is_online = True
                models, aliases = parse_openai_models(r.json())
        except Exception:
            pass

        return EngineInfo(
            name="Prism",
            engine_type=EngineType.PRISM,
            base_url=base_url,
            is_online=is_online,
            version="prism-local" if is_online else "offline",
            hardware=self.hardware,
            installed_models=models,
            latency_ms=round(latency, 2),
            model_aliases=aliases,
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
                    elif d.get("port"):
                        base_url = f"http://127.0.0.1:{d['port']}/v1"
            except Exception:
                pass

        if not base_url:
            base_url = "http://127.0.0.1:5272/v1"

        models: list[str] = []
        aliases: dict[str, str] = {}
        is_online = False
        latency = 0.0

        t0 = time.perf_counter()
        try:
            r = requests.get(f"{base_url}/models", timeout=1.0)
            latency = (time.perf_counter() - t0) * 1000
            if r.status_code == 200:
                is_online = True
                models, aliases = parse_openai_models(r.json())
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
            model_aliases=aliases,
        )

    def list_all_engines(self) -> list[EngineInfo]:
        """Status of all three local inference engines, cached for ``discovery_ttl`` seconds."""
        now = time.monotonic()
        if self._discovered is not None and now - self._discovered[0] < self.discovery_ttl:
            return list(self._discovered[1])
        engines = [self.discover_prism(), self.discover_ollama(), self.discover_foundry()]
        self._discovered = (now, engines)
        return list(engines)

    def invalidate_discovery(self) -> None:
        """Forget cached engine status (something just changed, or the caller wants live data)."""
        self._discovered = None

    def start_foundry_daemon(self) -> bool:
        """Try ``foundry server start``. Returns True when the CLI ran successfully."""
        foundry_bin = shutil.which("foundry")
        if not foundry_bin:
            return False
        sys.stderr.write("Foundry daemon not responding. Auto-starting via 'foundry server start'...\n")
        sys.stderr.flush()
        try:
            subprocess.run([foundry_bin, "server", "start"], capture_output=True, timeout=15)
        except Exception:
            return False
        time.sleep(2)
        self.invalidate_discovery()
        return True

    def resolve_target_engine(
        self,
        requested_engine: EngineType | str | Sequence[EngineType | str] = EngineType.AUTO,
        route: RouteContext | None = None,
    ) -> EngineInfo:
        """Select the best available engine.

        Priority in AUTO mode:
        1. On Linux/WSL2: Ollama -> Prism (CUDA) -> Foundry.
        2. On macOS (Apple Silicon Metal): Ollama -> Foundry -> Prism.

        Ollama comes first everywhere: measured on an RTX 5070 it is the fastest and most predictable engine for
        coder models, while Prism's ONNX models can loop on long outputs and hold GPU memory (prism-local #5, #6).
        Routing rules can put Prism first for a task or project.
        """
        self.last_decision = None
        if isinstance(requested_engine, list | tuple):
            # Ordered preference, e.g. (PRISM, FOUNDRY): first one that is online wins.
            errors = []
            for candidate in requested_engine:
                try:
                    return self.resolve_target_engine(candidate)
                except ConnectionError as e:
                    errors.append(str(e))
            raise ConnectionError("No requested engine is online: " + " | ".join(errors))

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
            if not info.is_online and self.autostart_foundry and self.start_foundry_daemon():
                info = self.discover_foundry()
            if info.is_online:
                return info
            raise ConnectionError(
                f"Foundry Local requested but offline at {info.base_url}. Start it with 'foundry server start'."
            )

        # AUTO mode: the routing rules decide which engines are allowed and in what order
        engines = self.list_all_engines()
        decision = self.policy.decide(self.priority(), route)
        self.last_decision = decision
        ranked = self.rank_online(engines, decision.order)
        if ranked:
            return ranked[0]

        allowed = ", ".join(e.value for e in decision.order) or "none"
        if decision.rule is not None and any(e.is_online for e in engines):
            raise ConnectionError(
                f"No allowed engine is online: {decision.rule.label()} allows only [{allowed}]. "
                f"Start one of them, pass --engine explicitly, or adjust the rule ({decision.rule.why or 'no reason given'})."
            )
        # If none online, return the first one with informative status
        return engines[0]

    def mark_failed(self, engine_type: EngineType) -> None:
        self._failed_at[engine_type] = time.monotonic()
        self.invalidate_discovery()

    def mark_ok(self, engine_type: EngineType) -> None:
        self._failed_at.pop(engine_type, None)

    def _cooling_down(self, engine_type: EngineType) -> bool:
        failed = self._failed_at.get(engine_type)
        return failed is not None and time.monotonic() - failed < self.cooldown_sec

    @staticmethod
    def priority() -> list[EngineType]:
        """Engine preference order for AUTO mode on the current platform."""
        if platform.system().lower() == "darwin":
            return [EngineType.OLLAMA, EngineType.FOUNDRY, EngineType.PRISM]
        # Linux / WSL2: Prism (direct CUDA) is the second choice, ahead of Foundry Local's CPU fallback
        return [EngineType.OLLAMA, EngineType.PRISM, EngineType.FOUNDRY]

    def rank_online(
        self, engines: list[EngineInfo], order: list[EngineType] | None = None, respect_cooldown: bool = True
    ) -> list[EngineInfo]:
        """Online engines in ``order`` (default: platform priority), one per distinct endpoint.

        Engines missing from ``order`` are excluded, which is how routing rules keep an avoided engine out of failover.
        Prism and Foundry Local share ``127.0.0.1:5272`` by default, so both can report the same server as online;
        only the higher-priority one is kept so failover never lands on the endpoint that just failed. Engines in
        cooldown are skipped unless that would leave nothing to try.
        """
        rank = {t: i for i, t in enumerate(order if order is not None else self.priority())}
        online = [e for e in engines if e.is_online and e.engine_type in rank]
        if respect_cooldown:
            rested = [e for e in online if not self._cooling_down(e.engine_type)]
            online = rested or online
        ranked: list[EngineInfo] = []
        seen_urls: set[str] = set()
        for eng in sorted(online, key=lambda e: rank[e.engine_type]):
            url = eng.base_url.rstrip("/")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            ranked.append(eng)
        return ranked

    def failover_candidates(self, failed: EngineInfo, route: RouteContext | None = None) -> list[EngineInfo]:
        """Allowed online engines on a different endpoint than ``failed``, best first."""
        failed_url = failed.base_url.rstrip("/")
        order = self.policy.decide(self.priority(), route).order
        candidates = [e for e in self.list_all_engines() if e.engine_type != failed.engine_type]
        return [e for e in self.rank_online(candidates, order) if e.base_url.rstrip("/") != failed_url]

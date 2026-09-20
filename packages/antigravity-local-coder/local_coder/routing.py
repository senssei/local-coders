"""Routing exceptions: ordered rules that steer AUTO engine selection.

A rule says *when* it applies (task, profile, an explicitly requested model, platform) and *what* to do:
``prefer`` engines go first, ``avoid`` engines are never used, ``only`` restricts the choice. The first matching rule
wins. Rules come from, in order of precedence, the project file, the user file and the built-in defaults; an explicit
engine (``--engine``, ``LOCAL_CODER_ENGINE``, a skill pinned to an engine) bypasses them entirely.
"""

import fnmatch
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .types import EngineType

ENGINE_NAMES = tuple(t.value for t in EngineType if t != EngineType.AUTO)
TASKS = ("code", "test", "review", "refactor")
PROFILES = ("coding", "fast", "reasoning")
WHEN_KEYS = ("task", "profile", "model", "platform")
RULE_KEYS = ("when", "prefer", "avoid", "only", "why")
PROJECT_FILE = Path(".local-coder") / "routing.json"

# Measured on an RTX 5070 (2026-09-20). Lowest precedence, so any project or user rule overrides it. Ollama is already
# first in the default order (see EngineRouter.priority), so the only built-in exception is a hard one.
BUILTIN_RULES: list[dict] = [
    {
        "when": {"model": "*coder*"},
        "avoid": ["prism"],
        "why": "ONNX coder models on Prism decode at ~30 tok/s vs 70-100 on Ollama and take ~10 GB of a 12 GB GPU",
    },
]


class RoutingConfigError(ValueError):
    """A routing file that cannot be used; raised at start-up rather than silently ignoring rules."""


@dataclass(frozen=True)
class RouteContext:
    """What the caller is doing. ``model`` is only set when the user asked for a model by name."""

    task: str | None = None
    profile: str | None = None
    model: str | None = None


@dataclass(frozen=True)
class Rule:
    when: dict[str, tuple[str, ...]]
    prefer: tuple[EngineType, ...] = ()
    avoid: tuple[EngineType, ...] = ()
    only: tuple[EngineType, ...] = ()
    why: str = ""
    source: str = "built-in"
    index: int = 0  # 1-based position inside its source

    def matches(self, ctx: RouteContext) -> bool:
        for key, wanted in self.when.items():
            if key == "task":
                if ctx.task not in wanted:
                    return False
            elif key == "profile":
                if (ctx.profile or "coding").lower() not in wanted:
                    return False
            elif key == "model":
                if not ctx.model or not any(fnmatch.fnmatchcase(ctx.model.lower(), p.lower()) for p in wanted):
                    return False
            elif key == "platform" and not any(sys.platform.startswith(p) for p in wanted):
                return False
        return True

    def apply(self, order: list[EngineType]) -> list[EngineType]:
        """Reorder and filter ``order``: prefer first, then restrict to ``only``, then drop ``avoid``."""
        result = [*self.prefer, *(e for e in order if e not in self.prefer)] if self.prefer else list(order)
        if self.only:
            result = [e for e in result if e in self.only]
        return [e for e in result if e not in self.avoid]

    def label(self) -> str:
        return f"rule #{self.index} ({self.source})"

    def describe(self) -> str:
        when = ", ".join(f"{k}={'|'.join(v)}" for k, v in self.when.items()) or "always"
        actions = [
            f"{name} {','.join(e.value for e in getattr(self, name))}"
            for name in ("prefer", "only", "avoid")
            if getattr(self, name)
        ]
        return f"when {when}: {'; '.join(actions)}" + (f"  # {self.why}" if self.why else "  # (no reason given)")


@dataclass
class RouteDecision:
    """Outcome of consulting the rules: the allowed engines in order, and the rule responsible (if any)."""

    order: list[EngineType]
    rule: Rule | None = None

    def describe(self) -> str:
        if self.rule is None:
            return "default order"
        return f"{self.rule.label()}: {self.rule.why or self.rule.describe()}"


def _as_tuple(value: object, field_name: str, where: str, allowed: tuple[str, ...] | None = None) -> tuple[str, ...]:
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list) or not items or not all(isinstance(i, str) for i in items):
        raise RoutingConfigError(f"{where}: '{field_name}' must be a string or a non-empty list of strings")
    if allowed is not None:
        bad = [i for i in items if i.lower() not in allowed]
        if bad:
            raise RoutingConfigError(f"{where}: unknown {field_name} {bad}; choose from: {', '.join(allowed)}")
    return tuple(i.lower() for i in items)


def parse_rules(data: object, source: str) -> list[Rule]:
    """Validate a routing document (``{"rules": [...]}``) and turn it into rules, or raise with the exact location."""
    if not isinstance(data, dict) or set(data) - {"rules"}:
        extra = sorted(set(data) - {"rules"}) if isinstance(data, dict) else []
        raise RoutingConfigError(
            f"{source}: expected an object with a single 'rules' list" + (f" (unknown keys: {extra})" if extra else "")
        )
    raw_rules = data.get("rules", [])
    if not isinstance(raw_rules, list):
        raise RoutingConfigError(f"{source}: 'rules' must be a list")

    rules: list[Rule] = []
    for i, raw in enumerate(raw_rules, start=1):
        where = f"{source}, rule #{i}"
        if not isinstance(raw, dict):
            raise RoutingConfigError(f"{where}: must be an object")
        unknown = sorted(set(raw) - set(RULE_KEYS))
        if unknown:
            raise RoutingConfigError(f"{where}: unknown keys {unknown}; allowed: {', '.join(RULE_KEYS)}")

        when_raw = raw.get("when", {})
        if not isinstance(when_raw, dict) or set(when_raw) - set(WHEN_KEYS):
            raise RoutingConfigError(f"{where}: 'when' must be an object with keys from: {', '.join(WHEN_KEYS)}")
        allowed_values = {"task": TASKS, "profile": PROFILES, "model": None, "platform": None}
        parsed_when = {key: _as_tuple(value, key, where, allowed_values[key]) for key, value in when_raw.items()}

        actions = {
            name: tuple(EngineType(e) for e in _as_tuple(raw[name], name, where, ENGINE_NAMES))
            for name in ("prefer", "avoid", "only")
            if name in raw
        }
        if not actions:
            raise RoutingConfigError(f"{where}: needs at least one of 'prefer', 'avoid' or 'only'")
        overlap = set(actions.get("avoid", ())) & (set(actions.get("prefer", ())) | set(actions.get("only", ())))
        if overlap:
            raise RoutingConfigError(
                f"{where}: {sorted(e.value for e in overlap)} is both avoided and preferred/required"
            )
        why = raw.get("why", "")
        if not isinstance(why, str):
            raise RoutingConfigError(f"{where}: 'why' must be a string")
        rules.append(Rule(parsed_when, why=why, source=source, index=i, **actions))
    return rules


def _read_rules(path: Path) -> list[Rule]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RoutingConfigError(f"{path}: not valid JSON ({e})") from e
    except OSError as e:
        raise RoutingConfigError(f"{path}: cannot be read ({e})") from e
    return parse_rules(data, str(path))


def find_project_file(start: Path) -> Path | None:
    """Nearest ``.local-coder/routing.json`` at or above ``start``."""
    for directory in (start, *start.parents):
        candidate = directory / PROJECT_FILE
        if candidate.is_file():
            return candidate
    return None


def user_file(env: dict[str, str] | None = None, home: Path | None = None) -> Path:
    env = os.environ if env is None else env
    base = Path(env["XDG_CONFIG_HOME"]) if env.get("XDG_CONFIG_HOME") else (home or Path.home()) / ".config"
    return base / "local-coders" / "routing.json"


@dataclass
class RoutingPolicy:
    rules: list[Rule] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)  # files that were actually loaded, highest precedence first

    @classmethod
    def load(
        cls, cwd: Path | None = None, env: dict[str, str] | None = None, home: Path | None = None
    ) -> "RoutingPolicy":
        """Project file, then user file, then built-ins. ``LOCAL_CODER_ROUTING`` names one file that replaces both
        (``none`` disables file lookup)."""
        env = os.environ if env is None else env
        explicit = env.get("LOCAL_CODER_ROUTING")
        files: list[Path] = []
        if explicit and explicit.lower() != "none":
            path = Path(explicit).expanduser()
            if not path.is_file():
                raise RoutingConfigError(f"LOCAL_CODER_ROUTING points at {path}, which does not exist")
            files = [path]
        elif not explicit:
            project = find_project_file((cwd or Path.cwd()).resolve())
            user = user_file(env, home)
            files = [p for p in (project, user if user.is_file() else None) if p is not None]

        rules: list[Rule] = []
        for path in files:
            rules += _read_rules(path)
        rules += parse_rules({"rules": BUILTIN_RULES}, "built-in")
        return cls(rules=rules, files=files)

    def decide(self, default_order: list[EngineType], ctx: RouteContext | None) -> RouteDecision:
        """Allowed engines in preference order for ``ctx``; the first matching rule wins."""
        if ctx is not None:
            for rule in self.rules:
                if rule.matches(ctx):
                    return RouteDecision(rule.apply(default_order), rule)
        return RouteDecision(list(default_order))

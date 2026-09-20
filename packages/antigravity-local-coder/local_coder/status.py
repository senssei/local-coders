"""Human-readable engine status shared by the CLI and the MCP server."""

from .router import EngineRouter


def format_status(router: EngineRouter, max_models: int = 4) -> str:
    """Render hardware and per-engine health, flagging engines that share an endpoint.

    Prism and Foundry Local both default to ``127.0.0.1:5272``; when one server answers for both, only the
    higher-priority engine is real and the other is shown as an alias instead of a second live engine.
    """
    engines = router.list_all_engines()
    owner_by_url = {e.base_url.rstrip("/"): e for e in router.rank_online(engines)}

    lines = ["⚡ Local Coder Multi-Engine Status:", f"Hardware: {router.hardware}", "-" * 36]
    for eng in engines:
        owner = owner_by_url.get(eng.base_url.rstrip("/"))
        icon = "✅" if eng.is_online else "❌"
        status = "ONLINE" if eng.is_online else "OFFLINE"
        lines.append(f"{icon} {eng.name:<24} {status:<8} ({eng.latency_ms}ms) | {eng.base_url}")
        if eng.is_online and owner is not None and owner.engine_type != eng.engine_type:
            lines.append(f"   ↳ same server as {owner.name}; not a separate engine")
            continue
        if eng.installed_models:
            lines.append(f"   Models ({len(eng.installed_models)}): {', '.join(eng.installed_models[:max_models])}")
    return "\n".join(lines)

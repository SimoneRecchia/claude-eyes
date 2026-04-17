"""claudeEyes MCP server — stdio transport via FastMCP."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import DEFAULT_FPS, DEFAULT_RESOLUTION_SCALE, ServerConfig
from .recorder import RecorderHandle, start_recorder, stop_recorder
from .session import RecordingSession, SessionRegistry, utc_now_iso
from .storage import cleanup_session_dir, list_frames as list_frames_on_disk


_config: ServerConfig = ServerConfig.from_env()
_registry: SessionRegistry = SessionRegistry(_config.sessions_dir)
_active: dict[str, RecorderHandle] = {}

mcp = FastMCP("claude_eyes")


@mcp.tool()
def start_recording(
    fps: int = DEFAULT_FPS,
    resolution_scale: float = DEFAULT_RESOLUTION_SCALE,
    region: tuple[int, int, int, int] | None = None,
    session_name: str | None = None,
) -> dict[str, Any]:
    """Begin a new screen recording session.

    Returns a ``session_id`` used for every subsequent call. The session
    folder is created under the configured ``sessions_dir``.
    """
    session = RecordingSession.create(
        name=session_name or "",
        fps=fps,
        resolution_scale=resolution_scale,
        region=region,
        monitor=_config.monitor,
        include_cursor=_config.include_cursor,
        sessions_dir=_config.sessions_dir,
    )
    handle = start_recorder(
        session_dir=Path(session.frames_dir),
        fps=fps,
        resolution_scale=resolution_scale,
        region=session.region,
        monitor_index=_config.monitor,
    )
    _active[session.session_id] = handle
    _registry.add(session)
    return {
        "session_id": session.session_id,
        "started_at": session.started_at,
        "config": {
            "fps": fps,
            "resolution_scale": resolution_scale,
            "region": list(session.region) if session.region else None,
            "monitor": _config.monitor,
            "include_cursor": _config.include_cursor,
        },
    }


@mcp.tool()
def cleanup_session(session_id: str) -> dict[str, Any]:
    """Delete all frames and registry data for a session. Always call after analysis."""
    session = _registry.get(session_id)
    if session is None:
        return {"deleted": False, "freed_bytes": 0, "reason": "unknown session"}
    if session_id in _active:
        stop_recorder(_active.pop(session_id))
    freed = cleanup_session_dir(Path(session.frames_dir))
    _registry.remove(session_id)
    return {"deleted": True, "freed_bytes": freed}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

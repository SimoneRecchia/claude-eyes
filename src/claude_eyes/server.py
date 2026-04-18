"""claudeEyes MCP server — stdio transport via FastMCP."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from .compose import compose_bucketed_preview
from .config import (
    CONTINUOUS_SESSION_DIR_NAME,
    DEFAULT_CONTINUOUS_FPS,
    DEFAULT_CONTINUOUS_RESOLUTION_SCALE,
    DEFAULT_CONTINUOUS_RETENTION_S,
    DEFAULT_FPS,
    DEFAULT_QUERY_MAX_FRAMES,
    DEFAULT_RESOLUTION_SCALE,
    ServerConfig,
)
from .continuous import ContinuousHandle, sample_frames, start_continuous, stop_continuous
from .recorder import RecorderHandle, start_recorder, stop_recorder
from .session import RecordingSession, SessionRegistry, utc_now_iso
from .storage import cleanup_session_dir, frames_in_time_range
from .storage import list_frames as list_frames_on_disk

_config: ServerConfig = ServerConfig.from_env()
_registry: SessionRegistry = SessionRegistry(_config.sessions_dir)
_active: dict[str, RecorderHandle] = {}
_continuous_handle: ContinuousHandle | None = None
_continuous_lock: threading.Lock = threading.Lock()

if _config.include_cursor:
    print(
        "[claude-eyes] CLAUDE_EYES_INCLUDE_CURSOR is set but cursor capture "
        "is not yet implemented; the flag is currently a no-op.",
        file=sys.stderr,
    )

mcp = FastMCP("claude_eyes")


@mcp.tool()
def start_recording(
    fps: int = DEFAULT_FPS,
    resolution_scale: float = DEFAULT_RESOLUTION_SCALE,
    region: tuple[int, int, int, int] | None = None,
    region_dpr: float = 1.0,
    session_name: str | None = None,
) -> dict[str, Any]:
    """Begin a new screen recording session.

    Returns a ``session_id`` used for every subsequent call. The session
    folder is created under the configured ``sessions_dir``. If ``region`` is
    given, ``region_dpr`` multiplies its coordinates before capture — use it
    when the region was computed in CSS pixels (e.g., from a browser) but the
    screen is captured in physical pixels (high-DPI / OS scaling).
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
        region_dpr=region_dpr,
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
            "region_dpr": region_dpr,
            "monitor": _config.monitor,
            "include_cursor": _config.include_cursor,
        },
    }


@mcp.tool()
def stop_recording(session_id: str) -> dict[str, Any]:
    """Stop an active recording and return frame metadata.

    The session stays in the registry so ``list_frames`` / ``cleanup_session``
    can still reach it. Call ``cleanup_session`` once the frame-analyzer
    subagent has returned.
    """
    handle = _active.pop(session_id, None)
    if handle is None:
        return {"error": f"no active recording for session_id={session_id}"}
    frames_count = stop_recorder(handle)
    duration_s = time.monotonic() - handle.started_monotonic

    session = _registry.get(session_id)
    if session is None:
        return {"error": f"session {session_id} missing from registry"}
    session.stopped_at = utc_now_iso()
    session.frames_count = frames_count
    _registry.update(session)

    frames = list_frames_on_disk(Path(session.frames_dir))

    try:
        bucket_items = compose_bucketed_preview(
            Path(session.frames_dir), bucket_s=1.0, mode="avg"
        )
    except Exception as exc:
        print(f"[claude-eyes] preview composition failed: {exc}", file=sys.stderr)
        bucket_items = []

    return {
        "session_id": session_id,
        "frames_count": frames_count,
        "duration_s": duration_s,
        "frames_dir": session.frames_dir,
        "frame_paths": [f["path"] for f in frames],
        "previews": {
            "mode": "avg",
            "bucket_s": 1.0,
            "items": [
                {
                    "bucket_index": b.bucket_index,
                    "preview_path": b.preview_path,
                    "frame_range": list(b.frame_range),
                    "ts_start_ms": b.ts_start_ms,
                    "ts_end_ms": b.ts_end_ms,
                }
                for b in bucket_items
            ],
        },
    }


@mcp.tool()
def list_frames(session_id: str) -> dict[str, Any]:
    """List frames of a session without stopping it. Safe on active sessions."""
    session = _registry.get(session_id)
    if session is None:
        return {"error": f"unknown session {session_id}"}
    return {
        "session_id": session_id,
        "frames": list_frames_on_disk(Path(session.frames_dir)),
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


@mcp.tool()
def compose_timeline_preview(
    session_id: str,
    bucket_s: float = 1.0,
    mode: Literal["avg", "max", "motion"] = "avg",
) -> dict[str, Any]:
    """Recompose the bucket previews of an existing on-demand session with
    different parameters. Writes preview files under
    ``sessions/<session_id>/previews/`` and returns their metadata.

    Continuous buffer sessions are not addressable by this tool; use
    ``query_buffer`` instead to get preview metadata for the rolling buffer.
    """
    session = _registry.get(session_id)
    if session is None:
        return {"error": f"unknown session {session_id}"}

    try:
        items = compose_bucketed_preview(
            Path(session.frames_dir), bucket_s=bucket_s, mode=mode
        )
    except Exception as exc:
        return {"error": f"compose failed: {exc}"}

    if not items:
        return {"error": "session has no frames"}

    effective_bucket_s = max(0.1, bucket_s)
    effective_mode = mode if mode in ("avg", "max", "motion") else "avg"

    return {
        "session_id": session_id,
        "mode": effective_mode,
        "bucket_s": effective_bucket_s,
        "items": [
            {
                "bucket_index": b.bucket_index,
                "preview_path": b.preview_path,
                "frame_range": list(b.frame_range),
                "ts_start_ms": b.ts_start_ms,
                "ts_end_ms": b.ts_end_ms,
            }
            for b in items
        ],
    }


@mcp.tool()
def start_continuous_buffer(
    fps: int = DEFAULT_CONTINUOUS_FPS,
    retention_s: int = DEFAULT_CONTINUOUS_RETENTION_S,
    resolution_scale: float = DEFAULT_CONTINUOUS_RESOLUTION_SCALE,
) -> dict[str, Any]:
    """Begin continuous rolling-buffer capture.

    ONLY call this when the user has explicitly asked for the buffer to start.
    Never start it on your own — the user must know their screen is being
    recorded continuously. Stop with ``stop_continuous_buffer`` when the user
    no longer needs it.
    """
    global _continuous_handle
    with _continuous_lock:
        if _continuous_handle is not None:
            return {
                "error": "continuous buffer already active",
                "started_at": _continuous_handle.started_at_iso,
            }
        session_dir = _config.sessions_dir / CONTINUOUS_SESSION_DIR_NAME
        disk_cap_bytes = _config.continuous_disk_cap_mb * 1024 * 1024
        handle = start_continuous(
            session_dir=session_dir,
            fps=fps,
            retention_s=retention_s,
            resolution_scale=resolution_scale,
            disk_cap_bytes=disk_cap_bytes,
            monitor_index=_config.monitor,
        )
        _continuous_handle = handle
        return {
            "active": True,
            "started_at": handle.started_at_iso,
            "config": {
                "fps": fps,
                "retention_s": retention_s,
                "resolution_scale": resolution_scale,
                "disk_cap_mb": _config.continuous_disk_cap_mb,
                "monitor": _config.monitor,
            },
        }


@mcp.tool()
def stop_continuous_buffer() -> dict[str, Any]:
    """Stop the continuous rolling buffer. Frames on disk are left in place
    (the session-end hook will wipe them when Claude Code exits)."""
    global _continuous_handle
    with _continuous_lock:
        if _continuous_handle is None:
            return {"error": "no active continuous buffer"}
        frames_kept, bytes_kept = stop_continuous(_continuous_handle)
        _continuous_handle = None
        return {
            "stopped": True,
            "frames_kept": frames_kept,
            "bytes_kept": bytes_kept,
        }


@mcp.tool()
def query_buffer(
    time_range_s: int,
    max_frames: int = DEFAULT_QUERY_MAX_FRAMES,
) -> dict[str, Any]:
    """Return an evenly-sampled subset of continuous-buffer frames from the
    last ``time_range_s`` seconds (capped at buffer retention)."""
    global _continuous_handle
    with _continuous_lock:
        if _continuous_handle is None:
            return {"error": "no active continuous buffer"}
        handle = _continuous_handle
        now_ms = int((time.monotonic() - handle.started_monotonic) * 1000)
        requested_oldest = now_ms - (time_range_s * 1000)
        buffer_oldest = max(0, now_ms - (handle.config.retention_s * 1000))
        clamped = requested_oldest < buffer_oldest
        oldest = buffer_oldest if clamped else requested_oldest

        all_frames = frames_in_time_range(
            handle.session_dir,
            oldest_ts_ms=oldest,
            newest_ts_ms=now_ms,
        )
        sampled = sample_frames(all_frames, max_frames)

        enriched = [
            {
                "path": f["path"],
                "index": f["index"],
                "timestamp_ms": f["timestamp_ms"],
                "age_s": round((now_ms - f["timestamp_ms"]) / 1000, 2),
            }
            for f in sampled
        ]
        result: dict[str, Any] = {
            "frames": enriched,
            "total_in_range": len(all_frames),
            "oldest_frame_age_s": enriched[0]["age_s"] if enriched else 0.0,
            "newest_frame_age_s": enriched[-1]["age_s"] if enriched else 0.0,
        }
        if clamped:
            effective_s = max(0, (now_ms - buffer_oldest) // 1000)
            result["warning"] = (
                f"time_range_s exceeded buffer age; clamped to {effective_s}s"
            )
        return result


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

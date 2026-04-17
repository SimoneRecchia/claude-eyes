"""Recording session model + JSON-backed registry."""
from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _make_id() -> str:
    return "sess_" + secrets.token_hex(6)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RecordingSession:
    session_id: str
    name: str
    fps: int
    resolution_scale: float
    region: tuple[int, int, int, int] | None
    monitor: int
    include_cursor: bool
    started_at: str
    stopped_at: str | None = None
    frames_count: int = 0
    frames_dir: str = ""

    @classmethod
    def create(
        cls,
        *,
        name: str,
        fps: int,
        resolution_scale: float,
        region: tuple[int, int, int, int] | None,
        monitor: int,
        include_cursor: bool,
        sessions_dir: Path,
    ) -> "RecordingSession":
        sid = _make_id()
        return cls(
            session_id=sid,
            name=name or sid,
            fps=fps,
            resolution_scale=resolution_scale,
            region=tuple(region) if region is not None else None,
            monitor=monitor,
            include_cursor=include_cursor,
            started_at=utc_now_iso(),
            frames_dir=str(sessions_dir / sid),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

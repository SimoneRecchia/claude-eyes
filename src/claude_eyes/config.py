"""claudeEyes configuration — internal constants and user-controlled env overrides."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Internal constants — not exposed as tool parameters.
JPEG_QUALITY: int = 85
SAFETY_CAP_SECONDS: int = 30 * 60  # anti-runaway recording cap
DEFAULT_FPS: int = 3
DEFAULT_RESOLUTION_SCALE: float = 1.0


def _parse_bool(value: str) -> bool:
    return value.strip().lower() == "true"


@dataclass(frozen=True)
class ServerConfig:
    """User-controlled config, read once from env vars at server startup."""

    monitor: int = 0
    include_cursor: bool = False
    sessions_dir: Path = Path("sessions")

    @classmethod
    def from_env(cls) -> ServerConfig:
        return cls(
            monitor=int(os.environ.get("CLAUDE_EYES_MONITOR", "0")),
            include_cursor=_parse_bool(os.environ.get("CLAUDE_EYES_INCLUDE_CURSOR", "false")),
            sessions_dir=Path(os.environ.get("CLAUDE_EYES_SESSIONS_DIR", "sessions")),
        )

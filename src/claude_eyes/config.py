"""claude-eyes configuration — internal constants and user-controlled env overrides."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Internal constants — not exposed as tool parameters.
JPEG_QUALITY: int = 85
SAFETY_CAP_SECONDS: int = 30 * 60  # anti-runaway recording cap
DEFAULT_FPS: int = 10
DEFAULT_RESOLUTION_SCALE: float = 1.0

# Continuous mode defaults
DEFAULT_CONTINUOUS_FPS: int = 2
DEFAULT_CONTINUOUS_RETENTION_S: int = 300
DEFAULT_CONTINUOUS_RESOLUTION_SCALE: float = 0.75
DEFAULT_CONTINUOUS_DISK_CAP_MB: int = 1024
DEFAULT_QUERY_MAX_FRAMES: int = 30
CONTINUOUS_SESSION_DIR_NAME: str = "_continuous"
CLEANUP_TICK_SECONDS: int = 5


def _parse_bool(value: str) -> bool:
    return value.strip().lower() == "true"


@dataclass(frozen=True)
class ServerConfig:
    """User-controlled config, read once from env vars at server startup."""

    monitor: int = 0
    include_cursor: bool = False
    sessions_dir: Path = Path("sessions")
    continuous_fps: int = DEFAULT_CONTINUOUS_FPS
    continuous_retention_s: int = DEFAULT_CONTINUOUS_RETENTION_S
    continuous_resolution_scale: float = DEFAULT_CONTINUOUS_RESOLUTION_SCALE
    continuous_disk_cap_mb: int = DEFAULT_CONTINUOUS_DISK_CAP_MB

    @classmethod
    def from_env(cls) -> ServerConfig:
        return cls(
            monitor=int(os.environ.get("CLAUDE_EYES_MONITOR", "0")),
            include_cursor=_parse_bool(os.environ.get("CLAUDE_EYES_INCLUDE_CURSOR", "false")),
            sessions_dir=Path(os.environ.get("CLAUDE_EYES_SESSIONS_DIR", "sessions")),
            continuous_fps=int(
                os.environ.get("CLAUDE_EYES_CONTINUOUS_FPS", str(DEFAULT_CONTINUOUS_FPS))
            ),
            continuous_retention_s=int(
                os.environ.get("CLAUDE_EYES_RETENTION_S", str(DEFAULT_CONTINUOUS_RETENTION_S))
            ),
            continuous_resolution_scale=float(
                os.environ.get(
                    "CLAUDE_EYES_CONTINUOUS_RESOLUTION_SCALE",
                    str(DEFAULT_CONTINUOUS_RESOLUTION_SCALE),
                )
            ),
            continuous_disk_cap_mb=int(
                os.environ.get("CLAUDE_EYES_DISK_CAP_MB", str(DEFAULT_CONTINUOUS_DISK_CAP_MB))
            ),
        )

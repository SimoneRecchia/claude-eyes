"""Tests for claude_eyes.config."""
from __future__ import annotations

from pathlib import Path

import pytest

from claude_eyes.config import (
    CLEANUP_TICK_SECONDS,
    CONTINUOUS_SESSION_DIR_NAME,
    DEFAULT_CONTINUOUS_DISK_CAP_MB,
    DEFAULT_CONTINUOUS_FPS,
    DEFAULT_CONTINUOUS_RESOLUTION_SCALE,
    DEFAULT_CONTINUOUS_RETENTION_S,
    DEFAULT_FPS,
    DEFAULT_QUERY_MAX_FRAMES,
    DEFAULT_RESOLUTION_SCALE,
    JPEG_QUALITY,
    SAFETY_CAP_SECONDS,
    ServerConfig,
)


def test_internal_constants_have_expected_defaults() -> None:
    assert DEFAULT_FPS == 3
    assert DEFAULT_RESOLUTION_SCALE == 1.0
    assert JPEG_QUALITY == 85
    assert SAFETY_CAP_SECONDS == 30 * 60


def test_server_config_defaults_when_env_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAUDE_EYES_MONITOR", raising=False)
    monkeypatch.delenv("CLAUDE_EYES_INCLUDE_CURSOR", raising=False)
    monkeypatch.delenv("CLAUDE_EYES_SESSIONS_DIR", raising=False)

    cfg = ServerConfig.from_env()

    assert cfg.monitor == 0
    assert cfg.include_cursor is False
    assert cfg.sessions_dir == Path("sessions")


def test_server_config_reads_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CLAUDE_EYES_MONITOR", "2")
    monkeypatch.setenv("CLAUDE_EYES_INCLUDE_CURSOR", "true")
    monkeypatch.setenv("CLAUDE_EYES_SESSIONS_DIR", str(tmp_path / "custom"))

    cfg = ServerConfig.from_env()

    assert cfg.monitor == 2
    assert cfg.include_cursor is True
    assert cfg.sessions_dir == tmp_path / "custom"


@pytest.mark.parametrize("value,expected", [
    ("true", True), ("True", True), ("TRUE", True),
    ("false", False), ("False", False), ("0", False), ("", False),
])
def test_include_cursor_env_parsing(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: bool
) -> None:
    monkeypatch.setenv("CLAUDE_EYES_INCLUDE_CURSOR", value)
    cfg = ServerConfig.from_env()
    assert cfg.include_cursor is expected


def test_continuous_constants_defaults() -> None:
    assert DEFAULT_CONTINUOUS_FPS == 2
    assert DEFAULT_CONTINUOUS_RETENTION_S == 300
    assert DEFAULT_CONTINUOUS_RESOLUTION_SCALE == 0.75
    assert DEFAULT_CONTINUOUS_DISK_CAP_MB == 1024
    assert DEFAULT_QUERY_MAX_FRAMES == 30
    assert CONTINUOUS_SESSION_DIR_NAME == "_continuous"
    assert CLEANUP_TICK_SECONDS == 5


def test_server_config_reads_continuous_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_EYES_CONTINUOUS_FPS", "5")
    monkeypatch.setenv("CLAUDE_EYES_RETENTION_S", "600")
    monkeypatch.setenv("CLAUDE_EYES_CONTINUOUS_RESOLUTION_SCALE", "0.5")
    monkeypatch.setenv("CLAUDE_EYES_DISK_CAP_MB", "2048")

    cfg = ServerConfig.from_env()

    assert cfg.continuous_fps == 5
    assert cfg.continuous_retention_s == 600
    assert cfg.continuous_resolution_scale == 0.5
    assert cfg.continuous_disk_cap_mb == 2048


def test_server_config_continuous_defaults_when_env_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "CLAUDE_EYES_CONTINUOUS_FPS",
        "CLAUDE_EYES_RETENTION_S",
        "CLAUDE_EYES_CONTINUOUS_RESOLUTION_SCALE",
        "CLAUDE_EYES_DISK_CAP_MB",
    ):
        monkeypatch.delenv(var, raising=False)

    cfg = ServerConfig.from_env()

    assert cfg.continuous_fps == DEFAULT_CONTINUOUS_FPS
    assert cfg.continuous_retention_s == DEFAULT_CONTINUOUS_RETENTION_S
    assert cfg.continuous_resolution_scale == DEFAULT_CONTINUOUS_RESOLUTION_SCALE
    assert cfg.continuous_disk_cap_mb == DEFAULT_CONTINUOUS_DISK_CAP_MB

"""Tests for claude_eyes.config."""
from __future__ import annotations

from pathlib import Path

import pytest

from claude_eyes.config import (
    DEFAULT_FPS,
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

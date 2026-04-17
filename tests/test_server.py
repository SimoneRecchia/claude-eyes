"""Tests for claude_eyes.server — exercise tools directly (not via stdio)."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from tests.test_recorder import _FakeMSS  # reuse fake backend


@pytest.fixture
def patched_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Patch env + mss BEFORE importing server, so module-level init uses them."""
    monkeypatch.setenv("CLAUDE_EYES_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("CLAUDE_EYES_MONITOR", "0")
    monkeypatch.setenv("CLAUDE_EYES_INCLUDE_CURSOR", "false")

    # Fresh import each test
    import importlib
    import claude_eyes.recorder as rec_mod
    monkeypatch.setattr(rec_mod.mss, "mss", _FakeMSS)

    import claude_eyes.server as server
    importlib.reload(server)
    return server


def test_start_recording_creates_session_and_directory(patched_server, tmp_path: Path) -> None:
    result = patched_server.start_recording(fps=5, resolution_scale=1.0, region=None, session_name="t1")

    assert result["session_id"].startswith("sess_")
    assert result["config"]["fps"] == 5
    assert result["config"]["resolution_scale"] == 1.0
    assert result["config"]["monitor"] == 0
    assert result["config"]["include_cursor"] is False
    # folder created
    assert (tmp_path / "sessions" / result["session_id"]).exists()

    # cleanup side-effect so subsequent tests are isolated
    patched_server.cleanup_session(result["session_id"])


def test_stop_recording_returns_frame_metadata(patched_server) -> None:
    start = patched_server.start_recording(fps=10, resolution_scale=1.0, region=None)
    sid = start["session_id"]
    time.sleep(0.4)
    result = patched_server.stop_recording(sid)

    assert result["session_id"] == sid
    assert result["frames_count"] >= 1
    assert result["duration_s"] > 0
    assert Path(result["frames_dir"]).is_dir()
    assert len(result["frame_paths"]) == result["frames_count"]

    patched_server.cleanup_session(sid)


def test_stop_recording_unknown_session_returns_error(patched_server) -> None:
    result = patched_server.stop_recording("sess_doesnotexist")
    assert "error" in result

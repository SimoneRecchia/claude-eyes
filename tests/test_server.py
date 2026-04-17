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
    result = patched_server.start_recording(
        fps=5, resolution_scale=1.0, region=None, session_name="t1"
    )

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


def test_list_frames_returns_current_frames(patched_server) -> None:
    start = patched_server.start_recording(fps=10, resolution_scale=1.0, region=None)
    sid = start["session_id"]
    time.sleep(0.35)
    listed = patched_server.list_frames(sid)

    assert listed["session_id"] == sid
    assert len(listed["frames"]) >= 1
    first = listed["frames"][0]
    assert set(first.keys()) == {"path", "index", "timestamp_ms"}

    patched_server.stop_recording(sid)
    patched_server.cleanup_session(sid)


def test_list_frames_unknown_session_returns_error(patched_server) -> None:
    result = patched_server.list_frames("sess_nope")
    assert "error" in result


def test_cleanup_session_removes_frames_and_registry(patched_server) -> None:
    start = patched_server.start_recording(fps=10, resolution_scale=1.0, region=None)
    sid = start["session_id"]
    time.sleep(0.3)
    patched_server.stop_recording(sid)
    frames_dir = Path(patched_server._registry.get(sid).frames_dir)
    assert frames_dir.is_dir()

    result = patched_server.cleanup_session(sid)

    assert result["deleted"] is True
    assert result["freed_bytes"] > 0
    assert not frames_dir.exists()
    assert patched_server._registry.get(sid) is None


def test_cleanup_session_unknown_session_reports_not_deleted(patched_server) -> None:
    result = patched_server.cleanup_session("sess_ghost")
    assert result["deleted"] is False
    assert result["freed_bytes"] == 0


def test_cleanup_session_stops_still_active_recorder(patched_server) -> None:
    start = patched_server.start_recording(fps=10, resolution_scale=1.0, region=None)
    sid = start["session_id"]
    # do NOT call stop_recording — cleanup should still succeed
    time.sleep(0.2)
    result = patched_server.cleanup_session(sid)
    assert result["deleted"] is True


def test_full_flow_start_list_stop_cleanup(patched_server, tmp_path: Path) -> None:
    start = patched_server.start_recording(fps=10, resolution_scale=0.5, region=(0, 0, 8, 8))
    sid = start["session_id"]
    assert start["config"]["resolution_scale"] == 0.5

    time.sleep(0.4)

    mid = patched_server.list_frames(sid)
    assert len(mid["frames"]) >= 1

    end = patched_server.stop_recording(sid)
    assert end["frames_count"] == len(end["frame_paths"])

    cleanup = patched_server.cleanup_session(sid)
    assert cleanup["deleted"] is True
    assert patched_server._registry.get(sid) is None

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

    import importlib

    import claude_eyes.continuous as cont_mod
    import claude_eyes.recorder as rec_mod

    monkeypatch.setattr(rec_mod.mss, "mss", _FakeMSS)
    monkeypatch.setattr(cont_mod.mss, "mss", _FakeMSS)

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


def _manual_stop_continuous(patched_server) -> None:
    """Teardown helper for Task 7 tests before ``stop_continuous_buffer`` exists."""
    from claude_eyes.continuous import stop_continuous

    if patched_server._continuous_handle is not None:
        stop_continuous(patched_server._continuous_handle)
        patched_server._continuous_handle = None


def test_start_continuous_buffer_activates_and_echoes_config(
    patched_server, tmp_path: Path
) -> None:
    result = patched_server.start_continuous_buffer(
        fps=5, retention_s=60, resolution_scale=0.5
    )

    assert result["active"] is True
    assert result["config"]["fps"] == 5
    assert result["config"]["retention_s"] == 60
    assert result["config"]["resolution_scale"] == 0.5
    assert result["config"]["monitor"] == 0
    assert (tmp_path / "sessions" / "_continuous").exists()

    _manual_stop_continuous(patched_server)


def test_start_continuous_buffer_rejects_double_start(patched_server) -> None:
    first = patched_server.start_continuous_buffer(fps=5)
    second = patched_server.start_continuous_buffer(fps=5)

    assert first["active"] is True
    assert "error" in second
    assert "already active" in second["error"]
    assert second["started_at"] == first["started_at"]

    _manual_stop_continuous(patched_server)


def test_stop_continuous_buffer_returns_stats(patched_server) -> None:
    patched_server.start_continuous_buffer(fps=10)
    time.sleep(0.25)

    result = patched_server.stop_continuous_buffer()

    assert result["stopped"] is True
    assert result["frames_kept"] >= 1
    assert result["bytes_kept"] > 0


def test_stop_continuous_buffer_rejects_when_idle(patched_server) -> None:
    result = patched_server.stop_continuous_buffer()
    assert "error" in result
    assert "no active" in result["error"]


def test_query_buffer_returns_sampled_frames(patched_server) -> None:
    patched_server.start_continuous_buffer(fps=20)
    time.sleep(0.6)
    result = patched_server.query_buffer(time_range_s=10, max_frames=5)

    assert "frames" in result
    assert 1 <= len(result["frames"]) <= 5
    assert result["total_in_range"] >= len(result["frames"])
    assert all(
        set(f.keys()) >= {"path", "index", "timestamp_ms", "age_s"}
        for f in result["frames"]
    )

    patched_server.stop_continuous_buffer()


def test_query_buffer_idle_returns_error(patched_server) -> None:
    result = patched_server.query_buffer(time_range_s=60)
    assert "error" in result


def test_query_buffer_empty_buffer_returns_empty_frames(patched_server) -> None:
    patched_server.start_continuous_buffer(fps=1)
    result = patched_server.query_buffer(time_range_s=10, max_frames=5)

    assert result["frames"] == []
    assert result["total_in_range"] == 0

    patched_server.stop_continuous_buffer()


def test_query_buffer_clamps_time_range_beyond_retention(patched_server) -> None:
    patched_server.start_continuous_buffer(fps=10, retention_s=10)
    time.sleep(0.4)
    result = patched_server.query_buffer(time_range_s=9999, max_frames=5)

    assert "warning" in result
    assert "clamped" in result["warning"]

    patched_server.stop_continuous_buffer()


def test_continuous_and_on_demand_coexist(patched_server, tmp_path: Path) -> None:
    """Buffer + on-demand run side-by-side on different directories."""
    cont = patched_server.start_continuous_buffer(fps=5)
    assert cont["active"] is True

    od = patched_server.start_recording(
        fps=10, resolution_scale=1.0, region=None, session_name="coexist"
    )
    sid = od["session_id"]
    time.sleep(0.35)
    od_stop = patched_server.stop_recording(sid)
    assert od_stop["frames_count"] >= 1

    continuous_dir = tmp_path / "sessions" / "_continuous"
    on_demand_dir = tmp_path / "sessions" / sid
    assert continuous_dir.exists()
    assert on_demand_dir.exists()
    assert continuous_dir != on_demand_dir

    q = patched_server.query_buffer(time_range_s=30, max_frames=10)
    assert "frames" in q
    cont_stop = patched_server.stop_continuous_buffer()
    assert cont_stop["stopped"] is True

    patched_server.cleanup_session(sid)


def test_start_recording_forwards_region_dpr(patched_server, tmp_path: Path) -> None:
    """Region passed to the tool is scaled by region_dpr before hitting mss."""
    from tests.test_recorder import _FakeMSS

    _FakeMSS.instances.clear()
    result = patched_server.start_recording(
        fps=10,
        resolution_scale=1.0,
        region=(10, 20, 30, 40),
        region_dpr=2.0,
        session_name="dpr_smoke",
    )
    sid = result["session_id"]
    time.sleep(0.3)
    patched_server.stop_recording(sid)

    grabbed = _FakeMSS.instances[-1].grabbed
    assert grabbed, "expected at least one grab"
    assert grabbed[0] == {"left": 20, "top": 40, "width": 60, "height": 80}

    patched_server.cleanup_session(sid)

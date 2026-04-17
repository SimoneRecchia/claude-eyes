"""Tests for claude_eyes.continuous."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from claude_eyes.continuous import sample_frames
from claude_eyes.storage import FrameInfo
from tests.test_recorder import _FakeMSS  # reuse fake backend from Spec 1


def _frames(n: int) -> list[FrameInfo]:
    return [
        {"path": f"/tmp/frame_{i:05d}_{i * 100:010d}.jpg", "index": i, "timestamp_ms": i * 100}
        for i in range(n)
    ]


def test_sample_returns_input_unchanged_when_under_max() -> None:
    frames = _frames(5)
    assert sample_frames(frames, max_frames=30) == frames


def test_sample_picks_evenly_spaced_with_endpoints() -> None:
    frames = _frames(100)
    result = sample_frames(frames, max_frames=10)

    assert len(result) == 10
    assert result[0] == frames[0]
    assert result[-1] == frames[-1]
    ts = [f["timestamp_ms"] for f in result]
    assert ts == sorted(ts)


def test_sample_max_one_returns_newest() -> None:
    frames = _frames(50)
    result = sample_frames(frames, max_frames=1)
    assert result == [frames[-1]]


def test_sample_empty_input() -> None:
    assert sample_frames([], max_frames=10) == []


def test_sample_zero_max_returns_empty() -> None:
    assert sample_frames(_frames(10), max_frames=0) == []


@pytest.fixture
def fake_mss_for_continuous(monkeypatch: pytest.MonkeyPatch) -> None:
    import claude_eyes.continuous as cont_mod

    monkeypatch.setattr(cont_mod.mss, "mss", _FakeMSS)


def test_start_continuous_captures_frames(tmp_path: Path, fake_mss_for_continuous: None) -> None:
    from claude_eyes.continuous import start_continuous, stop_continuous

    sess = tmp_path / "_continuous"
    handle = start_continuous(
        session_dir=sess,
        fps=10,
        retention_s=60,
        resolution_scale=1.0,
        disk_cap_bytes=10 * 1024 * 1024,
        monitor_index=0,
    )
    time.sleep(0.45)
    frames_kept, bytes_kept = stop_continuous(handle)

    assert frames_kept >= 2
    assert bytes_kept > 0
    assert len(list(sess.glob("frame_*.jpg"))) == frames_kept


def test_start_continuous_stops_cleanly(tmp_path: Path, fake_mss_for_continuous: None) -> None:
    from claude_eyes.continuous import start_continuous, stop_continuous

    handle = start_continuous(
        session_dir=tmp_path / "_continuous",
        fps=5,
        retention_s=60,
        resolution_scale=1.0,
        disk_cap_bytes=10 * 1024 * 1024,
        monitor_index=0,
    )
    frames_kept, _ = stop_continuous(handle, timeout=2.0)
    assert frames_kept >= 0
    assert not handle.capture_thread.is_alive()
    assert not handle.cleanup_thread.is_alive()


def test_continuous_cleanup_prunes_by_age(tmp_path: Path, fake_mss_for_continuous: None) -> None:
    """Short retention so cleanup reaps frames while capture is still running."""
    from claude_eyes.continuous import start_continuous, stop_continuous

    sess = tmp_path / "_continuous"
    handle = start_continuous(
        session_dir=sess,
        fps=20,
        retention_s=1,
        resolution_scale=1.0,
        disk_cap_bytes=100 * 1024 * 1024,
        monitor_index=0,
    )
    time.sleep(6.5)  # let cleanup tick at least once with stale frames present
    frames_kept, _ = stop_continuous(handle)

    assert frames_kept < 130, f"expected cleanup to trim frames, got {frames_kept}"

"""Tests for claude_eyes.continuous."""
from __future__ import annotations

from claude_eyes.continuous import sample_frames
from claude_eyes.storage import FrameInfo


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

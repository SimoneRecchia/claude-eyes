"""Tests for claude_eyes.session."""
from __future__ import annotations

from pathlib import Path

from claude_eyes.session import RecordingSession


def test_create_session_generates_id_and_frames_dir(sessions_dir: Path) -> None:
    s = RecordingSession.create(
        name="",
        fps=5,
        resolution_scale=0.5,
        region=None,
        monitor=0,
        include_cursor=False,
        sessions_dir=sessions_dir,
    )

    assert s.session_id.startswith("sess_")
    assert len(s.session_id) == len("sess_") + 12
    assert s.name == s.session_id  # empty name falls back to id
    assert s.fps == 5
    assert s.resolution_scale == 0.5
    assert s.region is None
    assert s.stopped_at is None
    assert s.frames_count == 0
    assert s.frames_dir == str(sessions_dir / s.session_id)
    assert s.started_at.endswith("+00:00")  # UTC ISO


def test_create_session_preserves_explicit_name(sessions_dir: Path) -> None:
    s = RecordingSession.create(
        name="button-click",
        fps=3, resolution_scale=1.0, region=(10, 20, 30, 40),
        monitor=1, include_cursor=True, sessions_dir=sessions_dir,
    )

    assert s.name == "button-click"
    assert s.region == (10, 20, 30, 40)
    assert s.monitor == 1
    assert s.include_cursor is True


def test_session_to_dict_roundtrips(sessions_dir: Path) -> None:
    s = RecordingSession.create(
        name="x", fps=4, resolution_scale=1.0, region=None,
        monitor=0, include_cursor=False, sessions_dir=sessions_dir,
    )
    d = s.to_dict()
    s2 = RecordingSession(**d)
    assert s == s2

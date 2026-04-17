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


import pytest

from claude_eyes.session import SessionRegistry


def _make(sessions_dir: Path, name: str = "x") -> RecordingSession:
    return RecordingSession.create(
        name=name, fps=3, resolution_scale=1.0, region=None,
        monitor=0, include_cursor=False, sessions_dir=sessions_dir,
    )


def test_registry_add_get_remove(sessions_dir: Path) -> None:
    reg = SessionRegistry(sessions_dir)
    s = _make(sessions_dir)

    reg.add(s)

    assert reg.get(s.session_id) == s
    assert reg.all() == [s]

    reg.remove(s.session_id)

    assert reg.get(s.session_id) is None
    assert reg.all() == []


def test_registry_persists_across_instances(sessions_dir: Path) -> None:
    reg1 = SessionRegistry(sessions_dir)
    s = _make(sessions_dir, name="persisted")
    reg1.add(s)

    reg2 = SessionRegistry(sessions_dir)

    assert reg2.get(s.session_id) == s


def test_registry_update_changes_fields(sessions_dir: Path) -> None:
    reg = SessionRegistry(sessions_dir)
    s = _make(sessions_dir)
    reg.add(s)

    s.frames_count = 42
    s.stopped_at = "2026-01-01T00:00:00+00:00"
    reg.update(s)

    reg2 = SessionRegistry(sessions_dir)
    loaded = reg2.get(s.session_id)
    assert loaded is not None
    assert loaded.frames_count == 42
    assert loaded.stopped_at == "2026-01-01T00:00:00+00:00"


def test_registry_tolerates_corrupt_json(sessions_dir: Path) -> None:
    (sessions_dir / ".registry.json").write_text("{not json", encoding="utf-8")
    reg = SessionRegistry(sessions_dir)  # must not raise
    assert reg.all() == []

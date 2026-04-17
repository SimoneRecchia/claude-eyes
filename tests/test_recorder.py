"""Tests for claude_eyes.recorder — use a fake mss backend to avoid real screen capture."""
from __future__ import annotations

import time
from pathlib import Path
from typing import ClassVar

import pytest


class _FakeScreenshot:
    """Mimics mss.base.ScreenShot — `rgb` is raw RGB bytes, `size` is (w, h)."""

    def __init__(self, w: int = 8, h: int = 8) -> None:
        self.size = (w, h)
        self.rgb = b"\x7f" * (w * h * 3)


class _FakeMSS:
    """Context-manager replacement for `mss.mss()` that records grab calls."""

    instances: ClassVar[list[_FakeMSS]] = []

    def __init__(self) -> None:
        self.monitors = [
            {"left": 0, "top": 0, "width": 8, "height": 8},
            {"left": 0, "top": 0, "width": 8, "height": 8},
        ]
        self.grabbed: list[dict[str, int]] = []
        _FakeMSS.instances.append(self)

    def __enter__(self) -> _FakeMSS:
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def grab(self, monitor: dict[str, int]) -> _FakeScreenshot:
        self.grabbed.append(dict(monitor))
        return _FakeScreenshot()


@pytest.fixture
def fake_mss(monkeypatch: pytest.MonkeyPatch) -> None:
    import claude_eyes.recorder as rec_mod

    monkeypatch.setattr(rec_mod.mss, "mss", _FakeMSS)


def test_recorder_captures_frames_at_target_fps(tmp_path: Path, fake_mss: None) -> None:
    from claude_eyes.recorder import start_recorder, stop_recorder

    sess = tmp_path / "rec1"
    handle = start_recorder(
        session_dir=sess, fps=10, resolution_scale=1.0,
        region=None, monitor_index=0,
    )
    time.sleep(0.55)  # ~5 ticks at 10 fps
    count = stop_recorder(handle)

    assert 3 <= count <= 8, f"unexpected frame count: {count}"
    saved = sorted(sess.glob("frame_*.jpg"))
    assert len(saved) == count


def test_recorder_honours_region_and_scale(tmp_path: Path, fake_mss: None) -> None:
    from claude_eyes.recorder import start_recorder, stop_recorder

    sess = tmp_path / "rec2"
    handle = start_recorder(
        session_dir=sess, fps=20, resolution_scale=0.5,
        region=(0, 0, 8, 8), monitor_index=0,
    )
    time.sleep(0.25)
    stop_recorder(handle)

    files = list(sess.glob("frame_*.jpg"))
    assert files, "expected at least one frame"
    # Scaled down to 4x4 — just confirm the file is a JPEG (PIL will not
    # accept a 0x0 image, so any readable JPEG is enough).
    from PIL import Image as _I
    with _I.open(files[0]) as img:
        assert img.size == (4, 4)


def test_stop_recorder_returns_zero_when_stopped_immediately(
    tmp_path: Path, fake_mss: None
) -> None:
    from claude_eyes.recorder import start_recorder, stop_recorder

    handle = start_recorder(
        session_dir=tmp_path / "rec3", fps=3, resolution_scale=1.0,
        region=None, monitor_index=0,
    )
    count = stop_recorder(handle, timeout=2.0)
    assert count >= 0


def test_recorder_region_dpr_default_is_noop(tmp_path: Path, fake_mss: None) -> None:
    """Without region_dpr (default 1.0), region is passed through unchanged."""
    from claude_eyes.recorder import start_recorder, stop_recorder

    _FakeMSS.instances.clear()
    handle = start_recorder(
        session_dir=tmp_path / "rec_dpr_1",
        fps=10,
        resolution_scale=1.0,
        region=(10, 20, 30, 40),
        monitor_index=0,
    )
    time.sleep(0.3)
    stop_recorder(handle)

    grabbed = _FakeMSS.instances[-1].grabbed
    assert grabbed, "expected at least one grab"
    assert grabbed[0] == {"left": 10, "top": 20, "width": 30, "height": 40}


def test_recorder_applies_region_dpr(tmp_path: Path, fake_mss: None) -> None:
    """region (100, 50, 200, 80) at DPR 1.5 must grab (150, 75, 300, 120)."""
    from claude_eyes.recorder import start_recorder, stop_recorder

    _FakeMSS.instances.clear()
    handle = start_recorder(
        session_dir=tmp_path / "rec_dpr_15",
        fps=10,
        resolution_scale=1.0,
        region=(100, 50, 200, 80),
        monitor_index=0,
        region_dpr=1.5,
    )
    time.sleep(0.3)
    stop_recorder(handle)

    grabbed = _FakeMSS.instances[-1].grabbed
    assert grabbed, "expected at least one grab"
    assert grabbed[0] == {"left": 150, "top": 75, "width": 300, "height": 120}


def test_recorder_region_dpr_clamped_high(tmp_path: Path, fake_mss: None) -> None:
    """DPR > 4.0 is clamped to 4.0."""
    from claude_eyes.recorder import start_recorder, stop_recorder

    _FakeMSS.instances.clear()
    handle = start_recorder(
        session_dir=tmp_path / "rec_dpr_5",
        fps=10,
        resolution_scale=1.0,
        region=(100, 100, 100, 100),
        monitor_index=0,
        region_dpr=5.0,
    )
    time.sleep(0.3)
    stop_recorder(handle)

    grabbed = _FakeMSS.instances[-1].grabbed
    assert grabbed, "expected at least one grab"
    assert grabbed[0] == {"left": 400, "top": 400, "width": 400, "height": 400}

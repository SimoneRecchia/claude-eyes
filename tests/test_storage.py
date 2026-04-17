"""Tests for claude_eyes.storage."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from claude_eyes.storage import (
    cleanup_session_dir,
    frame_filename,
    list_frames,
    save_frame,
)


def _img(color: tuple[int, int, int] = (255, 0, 0)) -> Image.Image:
    return Image.new("RGB", (10, 10), color)


def test_frame_filename_format() -> None:
    assert frame_filename(0, 0) == "frame_00000_0000000000.jpg"
    assert frame_filename(42, 1234) == "frame_00042_0000001234.jpg"


def test_save_frame_writes_jpeg(tmp_path: Path) -> None:
    sess = tmp_path / "s1"
    p = save_frame(sess, index=0, timestamp_ms=0, image=_img())

    assert p.exists()
    assert p.suffix == ".jpg"
    assert p.stat().st_size > 0
    # re-open to confirm it's a valid JPEG
    reopened = Image.open(p)
    assert reopened.size == (10, 10)
    assert reopened.format == "JPEG"


def test_list_frames_returns_sorted_metadata(tmp_path: Path) -> None:
    sess = tmp_path / "s2"
    save_frame(sess, 2, 700, _img())
    save_frame(sess, 0, 100, _img())
    save_frame(sess, 1, 400, _img())

    frames = list_frames(sess)

    assert [f["index"] for f in frames] == [0, 1, 2]
    assert [f["timestamp_ms"] for f in frames] == [100, 400, 700]
    for f in frames:
        assert Path(f["path"]).exists()


def test_list_frames_empty_for_missing_dir(tmp_path: Path) -> None:
    assert list_frames(tmp_path / "nope") == []


def test_cleanup_session_dir_removes_and_reports_bytes(tmp_path: Path) -> None:
    sess = tmp_path / "s3"
    save_frame(sess, 0, 0, _img())
    save_frame(sess, 1, 100, _img())
    assert sess.exists()

    freed = cleanup_session_dir(sess)

    assert freed > 0
    assert not sess.exists()


def test_cleanup_session_dir_missing_is_noop(tmp_path: Path) -> None:
    assert cleanup_session_dir(tmp_path / "never-existed") == 0

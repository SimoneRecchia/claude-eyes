"""Tests for claude_eyes.storage."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from claude_eyes.storage import (
    cleanup_session_dir,
    frame_filename,
    frames_in_time_range,
    list_frames,
    prune_by_age,
    prune_by_size,
    save_frame,
)


def _img(color: tuple[int, int, int] = (255, 0, 0)) -> Image.Image:
    return Image.new("RGB", (10, 10), color)


def _touch_frame(session_dir: Path, index: int, ts_ms: int) -> Path:
    """Write a tiny JPEG with the right filename so it can be pruned by age."""
    return save_frame(session_dir, index, ts_ms, _img())


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


def test_prune_by_age_removes_only_old_frames(tmp_path: Path) -> None:
    sess = tmp_path / "p_age"
    _touch_frame(sess, 0, 1000)    # age 4000 ms at now=5000
    _touch_frame(sess, 1, 3000)    # age 2000 ms
    _touch_frame(sess, 2, 4800)    # age  200 ms

    removed = prune_by_age(sess, max_age_ms=2500, now_ms=5000)

    assert removed == 1
    remaining = sorted(p.name for p in sess.glob("frame_*.jpg"))
    assert remaining == [
        "frame_00001_0000003000.jpg",
        "frame_00002_0000004800.jpg",
    ]


def test_prune_by_age_ignores_missing_dir(tmp_path: Path) -> None:
    assert prune_by_age(tmp_path / "never", max_age_ms=1000, now_ms=2000) == 0


def test_prune_by_age_tolerates_malformed_filenames(tmp_path: Path) -> None:
    sess = tmp_path / "p_age_bad"
    sess.mkdir()
    (sess / "frame_bad_name.jpg").write_bytes(b"not a frame")
    _touch_frame(sess, 0, 1000)

    removed = prune_by_age(sess, max_age_ms=500, now_ms=5000)

    assert removed == 1
    assert (sess / "frame_bad_name.jpg").exists()


def test_prune_by_size_removes_oldest_first(tmp_path: Path) -> None:
    sess = tmp_path / "p_size"
    _touch_frame(sess, 0, 123_456_789)
    _touch_frame(sess, 1, 234_567_890)
    _touch_frame(sess, 2, 345_678_901)
    total = sum(p.stat().st_size for p in sess.glob("frame_*.jpg"))
    target = int(total * 0.4)

    removed = prune_by_size(sess, max_bytes=target)

    assert removed >= 1
    remaining = sorted(p.name for p in sess.glob("frame_*.jpg"))
    assert not any("00000" in name for name in remaining)
    assert any("00002" in name for name in remaining)


def test_prune_by_size_under_cap_is_noop(tmp_path: Path) -> None:
    sess = tmp_path / "p_size_noop"
    _touch_frame(sess, 0, 1000)
    _touch_frame(sess, 1, 2000)

    removed = prune_by_size(sess, max_bytes=10 * 1024 * 1024)

    assert removed == 0
    assert len(list(sess.glob("frame_*.jpg"))) == 2


def test_prune_by_size_missing_dir(tmp_path: Path) -> None:
    assert prune_by_size(tmp_path / "nope", max_bytes=1000) == 0


def test_frames_in_time_range_filters_and_sorts(tmp_path: Path) -> None:
    sess = tmp_path / "p_range"
    _touch_frame(sess, 0, 100)
    _touch_frame(sess, 1, 500)
    _touch_frame(sess, 2, 900)
    _touch_frame(sess, 3, 1300)

    result = frames_in_time_range(sess, oldest_ts_ms=400, newest_ts_ms=1000)

    assert [f["timestamp_ms"] for f in result] == [500, 900]
    assert [f["index"] for f in result] == [1, 2]


def test_frames_in_time_range_inclusive_bounds(tmp_path: Path) -> None:
    sess = tmp_path / "p_range_inc"
    _touch_frame(sess, 0, 1000)
    _touch_frame(sess, 1, 2000)

    result = frames_in_time_range(sess, oldest_ts_ms=1000, newest_ts_ms=2000)

    assert len(result) == 2


def test_frames_in_time_range_missing_dir(tmp_path: Path) -> None:
    assert frames_in_time_range(tmp_path / "nope", 0, 10_000) == []

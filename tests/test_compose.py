"""Tests for claude_eyes.compose — blend helpers and orchestrator."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image as _I

from claude_eyes.compose import (
    BucketInfo,
    _blend_avg,
    _blend_max,
    _blend_motion,
    compose_bucketed_preview,
)
from claude_eyes.storage import save_frame


def test_blend_avg_two_solid_colors() -> None:
    arr = np.array(
        [
            [[[255, 0, 0]]],
            [[[0, 0, 255]]],
        ],
        dtype=np.uint8,
    )
    result = _blend_avg(arr)
    assert result.shape == (1, 1, 3)
    assert result[0, 0, 0] == 127
    assert result[0, 0, 1] == 0
    assert result[0, 0, 2] == 127


def test_blend_max_lighten() -> None:
    arr = np.array(
        [
            [[[255, 0, 0]]],
            [[[0, 255, 0]]],
        ],
        dtype=np.uint8,
    )
    result = _blend_max(arr)
    assert list(result[0, 0]) == [255, 255, 0]


def test_blend_motion_static_is_zero() -> None:
    arr = np.array(
        [
            [[[100, 100, 100]]],
            [[[100, 100, 100]]],
        ],
        dtype=np.uint8,
    )
    result = _blend_motion(arr)
    assert (result == 0).all()


def test_blend_motion_highlights_change() -> None:
    arr = np.array(
        [
            [[[0, 0, 0]]],
            [[[100, 50, 25]]],
        ],
        dtype=np.uint8,
    )
    result = _blend_motion(arr)
    assert result[0, 0, 0] == 255
    assert abs(int(result[0, 0, 1]) - 127) <= 1
    assert abs(int(result[0, 0, 2]) - 63) <= 1


def test_blend_motion_single_frame_falls_back_to_avg() -> None:
    arr = np.array([[[[50, 60, 70]]]], dtype=np.uint8)
    result = _blend_motion(arr)
    assert list(result[0, 0]) == [50, 60, 70]


def _img(color: tuple[int, int, int] = (100, 100, 100)) -> _I.Image:
    return _I.new("RGB", (8, 8), color)


def test_compose_empty_session_returns_empty_list(tmp_path: Path) -> None:
    sess = tmp_path / "empty"
    sess.mkdir()
    assert compose_bucketed_preview(sess, bucket_s=1.0, mode="avg") == []


def test_compose_bucket_boundaries_respect_timestamps(tmp_path: Path) -> None:
    sess = tmp_path / "buckets"
    save_frame(sess, 0, 100, _img((255, 0, 0)))
    save_frame(sess, 1, 500, _img((255, 0, 0)))
    save_frame(sess, 2, 900, _img((255, 0, 0)))
    save_frame(sess, 3, 1200, _img((0, 0, 255)))
    save_frame(sess, 4, 1800, _img((0, 0, 255)))

    items = compose_bucketed_preview(sess, bucket_s=1.0, mode="avg")

    assert len(items) == 2
    assert items[0].bucket_index == 0
    assert items[0].frame_range == (0, 2)
    assert items[0].ts_start_ms == 0
    assert items[0].ts_end_ms == 999
    assert items[1].bucket_index == 1
    assert items[1].frame_range == (3, 4)
    assert items[1].ts_start_ms == 1000
    assert items[1].ts_end_ms == 1999
    for it in items:
        assert Path(it.preview_path).exists()


def test_compose_writes_files_under_previews_dir(tmp_path: Path) -> None:
    sess = tmp_path / "dir_check"
    save_frame(sess, 0, 100, _img())
    items = compose_bucketed_preview(sess, bucket_s=1.0, mode="avg")
    assert len(items) == 1
    assert (sess / "previews").is_dir()
    assert Path(items[0].preview_path).parent == sess / "previews"
    assert Path(items[0].preview_path).name.startswith("preview_avg_000_")


def test_compose_bucket_s_clamped_to_minimum(tmp_path: Path) -> None:
    sess = tmp_path / "clamp"
    save_frame(sess, 0, 0, _img())
    save_frame(sess, 1, 50, _img())
    items = compose_bucketed_preview(sess, bucket_s=0.05, mode="avg")
    assert len(items) == 1
    assert items[0].frame_range == (0, 1)


def test_compose_unknown_mode_defaults_to_avg(tmp_path: Path) -> None:
    sess = tmp_path / "bad_mode"
    save_frame(sess, 0, 100, _img())
    items = compose_bucketed_preview(sess, bucket_s=1.0, mode="unknown")  # type: ignore[arg-type]
    assert len(items) == 1
    assert "preview_avg_" in items[0].preview_path


def test_compose_returns_bucket_info_dataclass(tmp_path: Path) -> None:
    sess = tmp_path / "dataclass_check"
    save_frame(sess, 0, 100, _img())
    items = compose_bucketed_preview(sess, bucket_s=1.0, mode="avg")
    assert all(isinstance(it, BucketInfo) for it in items)

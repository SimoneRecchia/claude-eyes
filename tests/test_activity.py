"""Tests for claude_eyes.activity — activity detection and fps reporting."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image as _I

from claude_eyes.activity import (
    _adaptive_threshold,
    _compute_scores,
    _downscale_frame,
    compute_fps_effective,
    score_frame_motion,
)
from claude_eyes.storage import list_frames, save_frame


def _solid_img(color: tuple[int, int, int] = (100, 100, 100), size: int = 32) -> _I.Image:
    return _I.new("RGB", (size, size), color)


def test_score_frame_motion_identical_frames_returns_zero() -> None:
    arr = np.array([[[100, 100, 100]]], dtype=np.uint8)
    assert score_frame_motion(arr, arr) == 0.0


def test_score_frame_motion_fully_changed_returns_255() -> None:
    a = np.array([[[0, 0, 0]]], dtype=np.uint8)
    b = np.array([[[255, 255, 255]]], dtype=np.uint8)
    assert score_frame_motion(a, b) == 255.0


def test_score_frame_motion_returns_mean_abs_diff() -> None:
    a = np.array([[[0, 0, 0]]], dtype=np.uint8)
    b = np.array([[[120, 60, 30]]], dtype=np.uint8)
    assert score_frame_motion(a, b) == 70.0


def test_compute_fps_effective_basic() -> None:
    assert compute_fps_effective(100, 4.0) == 25.0


def test_compute_fps_effective_zero_duration_returns_zero() -> None:
    assert compute_fps_effective(10, 0.0) == 0.0


def test_compute_fps_effective_negative_duration_returns_zero() -> None:
    assert compute_fps_effective(10, -1.0) == 0.0


def test_compute_fps_effective_single_frame_returns_zero() -> None:
    assert compute_fps_effective(1, 1.0) == 0.0


def test_compute_fps_effective_rounded_to_two_decimals() -> None:
    assert compute_fps_effective(100, 3.333) == 30.0


def test_downscale_frame_returns_128x72_uint8(tmp_path: Path) -> None:
    img = _I.new("RGB", (800, 600), (50, 100, 150))
    p = tmp_path / "test.jpg"
    img.save(p, "JPEG", quality=85)

    result = _downscale_frame(p)

    assert result.shape == (72, 128, 3)
    assert result.dtype == np.uint8
    assert abs(int(result[0, 0, 0]) - 50) < 5
    assert abs(int(result[0, 0, 1]) - 100) < 5
    assert abs(int(result[0, 0, 2]) - 150) < 5


def test_adaptive_threshold_static_scene_clamps_mad_floor() -> None:
    scores = [0.0, 0.0, 0.0, 0.0]
    t = _adaptive_threshold(scores)
    assert abs(t - 1.5) < 0.01


def test_adaptive_threshold_sits_between_baseline_and_spike() -> None:
    scores = [1.0] * 20 + [50.0] + [1.0] * 20
    t = _adaptive_threshold(scores)
    assert 1.0 < t < 50.0


def test_compute_scores_returns_n_minus_one(tmp_path: Path) -> None:
    sess = tmp_path / "scores"
    for i in range(4):
        save_frame(sess, i, i * 100, _solid_img((100, 100, 100)))

    frames = list_frames(sess)
    scores = _compute_scores(frames)

    assert len(scores) == 3
    assert all(s < 1.0 for s in scores)


def test_compute_scores_separates_motion_from_static(tmp_path: Path) -> None:
    sess = tmp_path / "mix"
    static_img = _solid_img((100, 100, 100))
    moving_img = _solid_img((200, 50, 50))
    save_frame(sess, 0, 0, static_img)
    save_frame(sess, 1, 100, static_img)
    save_frame(sess, 2, 200, static_img)
    save_frame(sess, 3, 300, moving_img)
    save_frame(sess, 4, 400, static_img)
    save_frame(sess, 5, 500, static_img)
    save_frame(sess, 6, 600, static_img)

    frames = list_frames(sess)
    scores = _compute_scores(frames)

    assert len(scores) == 6
    assert scores[2] > 50
    assert scores[3] > 50
    assert scores[0] < 1.0
    assert scores[1] < 1.0
    assert scores[4] < 1.0
    assert scores[5] < 1.0

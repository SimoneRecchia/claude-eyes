"""Tests for claude_eyes.activity — activity detection and fps reporting."""
from __future__ import annotations

import numpy as np

from claude_eyes.activity import compute_fps_effective, score_frame_motion


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

"""Tests for claude_eyes.compose — blend helpers and orchestrator."""
from __future__ import annotations

import numpy as np

from claude_eyes.compose import _blend_avg, _blend_max, _blend_motion


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

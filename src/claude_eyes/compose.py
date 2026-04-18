"""Temporal compositing — bundle frames into preview images.

This module produces one composite JPEG per time bucket so the
frame-analyzer subagent can scan a coarse timeline instead of reading
every raw frame. Three blend modes:

- avg     pixel-wise mean across the bucket; faithful but static-dominant
- max     pixel-wise maximum (lighten); trails and moving content pop
- motion  summed absolute differences between consecutive frames,
          normalised to 0-255; a heatmap of where change happened
"""
from __future__ import annotations

from typing import Literal, cast

import numpy as np

BlendMode = Literal["avg", "max", "motion"]


def _blend_avg(arr: np.ndarray) -> np.ndarray:
    """Pixel-wise mean across frames.

    arr shape: (N, H, W, 3) uint8. Returns (H, W, 3) uint8.
    """
    return cast(np.ndarray, arr.mean(axis=0).astype(np.uint8))


def _blend_max(arr: np.ndarray) -> np.ndarray:
    """Pixel-wise max across frames (lighten blend).

    arr shape: (N, H, W, 3) uint8. Returns (H, W, 3) uint8.
    """
    return cast(np.ndarray, arr.max(axis=0))


def _blend_motion(arr: np.ndarray) -> np.ndarray:
    """Sum of absolute diffs between consecutive frames, normalised to 0-255.

    If fewer than 2 frames are present, falls back to :func:`_blend_avg`
    (motion is undefined on a single frame).
    """
    if arr.shape[0] < 2:
        return _blend_avg(arr)
    diffs = np.abs(np.diff(arr.astype(np.int16), axis=0))
    summed = diffs.sum(axis=0)
    max_val = int(summed.max())
    if max_val == 0:
        return np.zeros_like(summed, dtype=np.uint8)
    normalised = summed.astype(np.float32) * (255.0 / max_val)
    return cast(np.ndarray, normalised.astype(np.uint8))

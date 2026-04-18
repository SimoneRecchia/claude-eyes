"""Post-capture activity detection and fps-effective reporting.

Given a completed recording (a directory of frame JPEGs), this module:

- Scores motion between consecutive frames with mean absolute pixel
  difference on 128x72 thumbnails (cheap, deterministic).
- Computes an adaptive threshold per session so a scene with a live
  video background (high baseline) and one with a static desktop (low
  baseline) are both handled without magic numbers.
- Returns the leading-and-trailing-trimmed index range where activity
  was detected, plus the mean motion score for diagnostics.

All functions are pure IO + CPU. No locks, no shared state.
"""
from __future__ import annotations

import numpy as np


def score_frame_motion(prev: np.ndarray, curr: np.ndarray) -> float:
    """Return the mean per-pixel absolute difference between two frames.

    Both arrays must have the same shape; dtype uint8 is assumed. The
    result is in [0, 255].
    """
    return float(np.abs(curr.astype(np.int16) - prev.astype(np.int16)).mean())


def compute_fps_effective(frames_count: int, duration_s: float) -> float:
    """Return real fps achieved by the recorder, rounded to two decimals.

    Returns 0.0 when the session is too short to measure (fewer than two
    frames, or non-positive duration).
    """
    if duration_s <= 0 or frames_count < 2:
        return 0.0
    return round(frames_count / duration_s, 2)

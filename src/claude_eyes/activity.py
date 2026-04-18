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

from pathlib import Path

import numpy as np
from PIL import Image

from .storage import FrameInfo

_THUMB_SIZE = (128, 72)            # (W, H) for PIL; 16:9; ~9216 pixels
_CHUNK_SIZE = 500                  # frames per batch (memory cap)


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


def _downscale_frame(path: Path) -> np.ndarray:
    """Load a JPEG, resize to _THUMB_SIZE via bilinear, return (H, W, 3) uint8."""
    with Image.open(path) as img:
        rgb = img.convert("RGB").resize(_THUMB_SIZE, Image.Resampling.BILINEAR)
        return np.asarray(rgb, dtype=np.uint8)


def _compute_scores(frames: list[FrameInfo]) -> list[float]:
    """Return the N-1 motion scores between consecutive frames in ``frames``.

    Frames are loaded lazily, downscaled, and discarded as the window rolls —
    peak memory is bounded to two thumbnails regardless of session length.
    Chunking is logical only (no cross-chunk boundary effects) because we
    keep a running ``prev_thumb`` reference.
    """
    scores: list[float] = []
    prev_thumb: np.ndarray | None = None
    for chunk_start in range(0, len(frames), _CHUNK_SIZE):
        chunk = frames[chunk_start : chunk_start + _CHUNK_SIZE]
        for f in chunk:
            curr_thumb = _downscale_frame(Path(f["path"]))
            if prev_thumb is not None:
                scores.append(score_frame_motion(prev_thumb, curr_thumb))
            prev_thumb = curr_thumb
    return scores


def _adaptive_threshold(scores: list[float]) -> float:
    """Threshold = ``percentile(scores, 25) + 3 x max(MAD, 0.5)``.

    The 0.5 floor on MAD prevents zero-threshold drift on scenes where
    every frame pair produces an identical score (threshold would otherwise
    be equal to the baseline, meaning every score would trigger "active").
    """
    arr = np.array(scores)
    baseline = float(np.percentile(arr, 25))
    mad = float(np.median(np.abs(arr - np.median(arr))))
    return baseline + 3 * max(mad, 0.5)

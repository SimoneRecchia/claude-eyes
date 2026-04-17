"""Continuous rolling-buffer capture and query-time sampling."""
from __future__ import annotations

from .storage import FrameInfo


def sample_frames(frames: list[FrameInfo], max_frames: int) -> list[FrameInfo]:
    """Return up to ``max_frames`` frames evenly spaced across the input.

    - If ``max_frames <= 0``: returns ``[]``.
    - If ``len(frames) == 0``: returns ``[]``.
    - If ``len(frames) <= max_frames``: returns the input unchanged.
    - If ``max_frames == 1``: returns ``[frames[-1]]`` (the newest).
    - Otherwise: returns ``max_frames`` items evenly spaced by index, always
      including ``frames[0]`` and ``frames[-1]``.
    """
    if max_frames <= 0:
        return []
    n = len(frames)
    if n == 0:
        return []
    if n <= max_frames:
        return list(frames)
    if max_frames == 1:
        return [frames[-1]]
    step = (n - 1) / (max_frames - 1)
    seen: set[int] = set()
    result: list[FrameInfo] = []
    for i in range(max_frames):
        idx = round(i * step)
        if idx not in seen:
            seen.add(idx)
            result.append(frames[idx])
    return result

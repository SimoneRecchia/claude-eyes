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

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import numpy as np
from PIL import Image

from .config import JPEG_QUALITY
from .storage import FrameInfo, list_frames

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


@dataclass
class BucketInfo:
    """Metadata for one composited bucket."""

    bucket_index: int
    preview_path: str
    frame_range: tuple[int, int]
    ts_start_ms: int
    ts_end_ms: int


def compose_bucketed_preview(
    session_dir: Path,
    bucket_s: float = 1.0,
    mode: BlendMode = "avg",
) -> list[BucketInfo]:
    """Group frames into buckets of ``bucket_s`` seconds, blend each into
    one preview image written to ``session_dir/previews/``.

    Returns per-bucket metadata in ascending ``bucket_index`` order.
    Missing or empty session returns ``[]``. ``bucket_s`` is clamped to
    ``>= 0.1``. Unknown ``mode`` falls back to ``"avg"``. Motion on a
    single-frame bucket falls back to avg inside the helper.
    """
    if bucket_s < 0.1:
        bucket_s = 0.1
    if mode not in ("avg", "max", "motion"):
        mode = "avg"

    frames = list_frames(session_dir)
    if not frames:
        return []

    preview_dir = session_dir / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)

    bucket_ms = int(bucket_s * 1000)

    buckets: dict[int, list[FrameInfo]] = {}
    for f in frames:
        bidx = f["timestamp_ms"] // bucket_ms
        buckets.setdefault(bidx, []).append(f)

    result: list[BucketInfo] = []
    for bidx in sorted(buckets):
        bucket_frames = buckets[bidx]
        if not bucket_frames:
            continue

        target_size: tuple[int, int] | None = None
        arrays: list[np.ndarray] = []
        for fi in bucket_frames:
            with Image.open(fi["path"]) as img:
                rgb = img.convert("RGB")
                if target_size is None:
                    target_size = rgb.size
                elif rgb.size != target_size:
                    rgb = rgb.resize(target_size, Image.Resampling.LANCZOS)
                arrays.append(np.asarray(rgb, dtype=np.uint8))
        stacked = np.stack(arrays, axis=0)

        if mode == "avg":
            composite = _blend_avg(stacked)
        elif mode == "max":
            composite = _blend_max(stacked)
        else:
            composite = _blend_motion(stacked)

        ts_start = bidx * bucket_ms
        ts_end = ts_start + bucket_ms - 1
        filename = f"preview_{mode}_{bidx:03d}_{ts_start:010d}.jpg"
        out_path = preview_dir / filename

        try:
            Image.fromarray(composite).save(
                out_path, format="JPEG", quality=JPEG_QUALITY, optimize=True
            )
        except OSError as exc:
            print(
                f"[claude-eyes] preview write failed for bucket {bidx}: {exc}",
                file=sys.stderr,
            )
            continue

        result.append(
            BucketInfo(
                bucket_index=bidx,
                preview_path=str(out_path),
                frame_range=(bucket_frames[0]["index"], bucket_frames[-1]["index"]),
                ts_start_ms=ts_start,
                ts_end_ms=ts_end,
            )
        )

    return result

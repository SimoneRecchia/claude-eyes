"""Frame file layout on disk + cleanup."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import TypedDict

from PIL import Image

from .config import JPEG_QUALITY


class FrameInfo(TypedDict):
    path: str
    index: int
    timestamp_ms: int


def frame_filename(index: int, timestamp_ms: int) -> str:
    return f"frame_{index:05d}_{timestamp_ms:010d}.jpg"


def save_frame(
    session_dir: Path,
    index: int,
    timestamp_ms: int,
    image: Image.Image,
) -> Path:
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / frame_filename(index, timestamp_ms)
    image.save(path, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return path


def list_frames(session_dir: Path) -> list[FrameInfo]:
    if not session_dir.is_dir():
        return []
    out: list[FrameInfo] = []
    for p in sorted(session_dir.glob("frame_*.jpg")):
        parts = p.stem.split("_")
        if len(parts) != 3:
            continue
        try:
            idx = int(parts[1])
            ts = int(parts[2])
        except ValueError:
            continue
        out.append({"path": str(p), "index": idx, "timestamp_ms": ts})
    return out


def cleanup_session_dir(session_dir: Path) -> int:
    """Remove session_dir recursively. Returns total bytes freed.

    If the directory does not exist, returns 0.
    """
    if not session_dir.is_dir():
        return 0
    total = sum(f.stat().st_size for f in session_dir.rglob("*") if f.is_file())
    shutil.rmtree(session_dir)
    return total


def prune_by_age(session_dir: Path, max_age_ms: int, now_ms: int) -> int:
    """Remove frames whose encoded timestamp is older than ``now_ms - max_age_ms``.

    Returns the number of frames removed. Missing directory is a no-op.
    Malformed filenames are skipped (not counted, not deleted).
    """
    if not session_dir.is_dir():
        return 0
    cutoff_ms = now_ms - max_age_ms
    removed = 0
    for p in session_dir.glob("frame_*.jpg"):
        parts = p.stem.split("_")
        if len(parts) != 3:
            continue
        try:
            ts = int(parts[2])
        except ValueError:
            continue
        if ts < cutoff_ms:
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def prune_by_size(session_dir: Path, max_bytes: int) -> int:
    """If the total size of ``frame_*.jpg`` exceeds ``max_bytes``, delete oldest-first
    until under the cap. Returns the number of frames removed.

    Oldest-first is decided lexicographically by filename, which works because the
    index is zero-padded to 5 digits (see :func:`frame_filename`).
    """
    if not session_dir.is_dir():
        return 0
    frames = sorted(session_dir.glob("frame_*.jpg"), key=lambda p: p.name)
    sizes = [(p, p.stat().st_size) for p in frames if p.is_file()]
    total = sum(size for _, size in sizes)
    removed = 0
    for p, size in sizes:
        if total <= max_bytes:
            break
        try:
            p.unlink()
            total -= size
            removed += 1
        except OSError:
            pass
    return removed


def frames_in_time_range(
    session_dir: Path,
    oldest_ts_ms: int,
    newest_ts_ms: int,
) -> list[FrameInfo]:
    """Return frames whose ``timestamp_ms`` is in ``[oldest_ts_ms, newest_ts_ms]``
    (inclusive), sorted ascending by timestamp.
    """
    if not session_dir.is_dir():
        return []
    out: list[FrameInfo] = []
    for p in session_dir.glob("frame_*.jpg"):
        parts = p.stem.split("_")
        if len(parts) != 3:
            continue
        try:
            idx = int(parts[1])
            ts = int(parts[2])
        except ValueError:
            continue
        if oldest_ts_ms <= ts <= newest_ts_ms:
            out.append({"path": str(p), "index": idx, "timestamp_ms": ts})
    out.sort(key=lambda f: f["timestamp_ms"])
    return out

"""Continuous rolling-buffer capture and query-time sampling."""
from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import mss
from PIL import Image

from .config import CLEANUP_TICK_SECONDS
from .storage import (
    FrameInfo,
    prune_by_age,
    prune_by_size,
    save_frame,
)


@dataclass
class ContinuousConfig:
    fps: int
    retention_s: int
    resolution_scale: float
    disk_cap_bytes: int
    monitor: int


@dataclass
class ContinuousHandle:
    capture_thread: threading.Thread
    cleanup_thread: threading.Thread
    stop_event: threading.Event
    session_dir: Path
    started_monotonic: float
    started_at_iso: str
    config: ContinuousConfig


def _capture_loop(
    *,
    stop_event: threading.Event,
    session_dir: Path,
    fps: int,
    resolution_scale: float,
    monitor_index: int,
    started_monotonic: float,
) -> None:
    interval = 1.0 / fps
    next_tick = started_monotonic
    index = 0
    with mss.mss() as sct:
        monitor = sct.monitors[monitor_index]
        while not stop_event.is_set():
            now = time.monotonic()
            if now < next_tick and stop_event.wait(timeout=next_tick - now):
                break
            ts_ms = int((time.monotonic() - started_monotonic) * 1000)
            try:
                raw = sct.grab(monitor)
                img = Image.frombytes("RGB", raw.size, raw.rgb)
                if resolution_scale != 1.0:
                    new_size = (
                        max(1, int(img.width * resolution_scale)),
                        max(1, int(img.height * resolution_scale)),
                    )
                    img = img.resize(new_size, Image.Resampling.LANCZOS)
                save_frame(session_dir, index, ts_ms, img)
                index += 1
            except OSError as exc:
                print(
                    f"[claude-eyes] continuous capture write failed: {exc}",
                    file=sys.stderr,
                )
            next_tick += interval


def _cleanup_loop(
    *,
    stop_event: threading.Event,
    session_dir: Path,
    started_monotonic: float,
    retention_s: int,
    disk_cap_bytes: int,
) -> None:
    retention_ms = retention_s * 1000
    grace_ms = 1000  # never touch frames younger than 1 s
    while not stop_event.wait(CLEANUP_TICK_SECONDS):
        now_ms = int((time.monotonic() - started_monotonic) * 1000)
        prune_by_age(session_dir, max_age_ms=retention_ms, now_ms=now_ms - grace_ms)
        prune_by_size(session_dir, max_bytes=disk_cap_bytes)


def start_continuous(
    *,
    session_dir: Path,
    fps: int,
    retention_s: int,
    resolution_scale: float,
    disk_cap_bytes: int,
    monitor_index: int,
) -> ContinuousHandle:
    session_dir.mkdir(parents=True, exist_ok=True)
    stop_event = threading.Event()
    started_mono = time.monotonic()
    started_iso = datetime.now(UTC).isoformat()
    config = ContinuousConfig(
        fps=fps,
        retention_s=retention_s,
        resolution_scale=resolution_scale,
        disk_cap_bytes=disk_cap_bytes,
        monitor=monitor_index,
    )
    capture = threading.Thread(
        target=_capture_loop,
        kwargs={
            "stop_event": stop_event,
            "session_dir": session_dir,
            "fps": fps,
            "resolution_scale": resolution_scale,
            "monitor_index": monitor_index,
            "started_monotonic": started_mono,
        },
        daemon=True,
        name="claude-eyes-continuous-capture",
    )
    cleanup = threading.Thread(
        target=_cleanup_loop,
        kwargs={
            "stop_event": stop_event,
            "session_dir": session_dir,
            "started_monotonic": started_mono,
            "retention_s": retention_s,
            "disk_cap_bytes": disk_cap_bytes,
        },
        daemon=True,
        name="claude-eyes-continuous-cleanup",
    )
    capture.start()
    cleanup.start()
    return ContinuousHandle(
        capture_thread=capture,
        cleanup_thread=cleanup,
        stop_event=stop_event,
        session_dir=session_dir,
        started_monotonic=started_mono,
        started_at_iso=started_iso,
        config=config,
    )


def stop_continuous(handle: ContinuousHandle, timeout: float = 5.0) -> tuple[int, int]:
    """Stop both threads, wait for them to finish, return (frames_kept, bytes_kept)."""
    handle.stop_event.set()
    handle.capture_thread.join(timeout=timeout)
    handle.cleanup_thread.join(timeout=timeout)
    frames = [p for p in handle.session_dir.glob("frame_*.jpg") if p.is_file()]
    total_bytes = sum(p.stat().st_size for p in frames)
    return len(frames), total_bytes


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

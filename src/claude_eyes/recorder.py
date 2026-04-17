"""Screen capture worker — runs in a daemon thread around ``mss``."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

import mss
from PIL import Image

from .config import SAFETY_CAP_SECONDS
from .storage import save_frame


@dataclass
class RecorderHandle:
    thread: threading.Thread
    stop_event: threading.Event
    frames_counter: list[int]  # 1-element mutable for cross-thread count
    started_monotonic: float


def _capture_loop(
    *,
    stop_event: threading.Event,
    session_dir: Path,
    fps: int,
    resolution_scale: float,
    region: tuple[int, int, int, int] | None,
    monitor_index: int,
    frames_counter: list[int],
    started_monotonic: float,
) -> None:
    interval = 1.0 / fps
    next_tick = started_monotonic
    with mss.mss() as sct:
        if region is not None:
            x, y, w, h = region
            target = {"left": x, "top": y, "width": w, "height": h}
        else:
            # monitors[0] is the full virtual screen across all displays
            target = sct.monitors[monitor_index]

        while not stop_event.is_set():
            now = time.monotonic()
            if now - started_monotonic > SAFETY_CAP_SECONDS:
                break
            if now < next_tick:
                if stop_event.wait(timeout=next_tick - now):
                    break

            ts_ms = int((time.monotonic() - started_monotonic) * 1000)
            raw = sct.grab(target)
            img = Image.frombytes("RGB", raw.size, raw.rgb)
            if resolution_scale != 1.0:
                new_size = (
                    max(1, int(img.width * resolution_scale)),
                    max(1, int(img.height * resolution_scale)),
                )
                img = img.resize(new_size, Image.LANCZOS)

            save_frame(session_dir, frames_counter[0], ts_ms, img)
            frames_counter[0] += 1
            next_tick += interval


def start_recorder(
    *,
    session_dir: Path,
    fps: int,
    resolution_scale: float,
    region: tuple[int, int, int, int] | None,
    monitor_index: int,
) -> RecorderHandle:
    session_dir.mkdir(parents=True, exist_ok=True)
    stop_event = threading.Event()
    counter: list[int] = [0]
    started = time.monotonic()
    thread = threading.Thread(
        target=_capture_loop,
        kwargs=dict(
            stop_event=stop_event,
            session_dir=session_dir,
            fps=fps,
            resolution_scale=resolution_scale,
            region=region,
            monitor_index=monitor_index,
            frames_counter=counter,
            started_monotonic=started,
        ),
        daemon=True,
        name=f"claude-eyes-recorder-{session_dir.name}",
    )
    thread.start()
    return RecorderHandle(
        thread=thread,
        stop_event=stop_event,
        frames_counter=counter,
        started_monotonic=started,
    )


def stop_recorder(handle: RecorderHandle, timeout: float = 5.0) -> int:
    handle.stop_event.set()
    handle.thread.join(timeout=timeout)
    return handle.frames_counter[0]

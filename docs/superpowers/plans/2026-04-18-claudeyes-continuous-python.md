# claudeEyes Continuous Mode — Python Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the continuous rolling-buffer recording mode on top of the Spec 1 foundation — three new MCP tools (`start_continuous_buffer`, `stop_continuous_buffer`, `query_buffer`), one new Python module (`continuous.py`), storage extensions for age-based / size-based pruning, a new Claude skill, a privacy-guardrail hook, and CLAUDE.md updates.

**Architecture:** The continuous buffer is a pair of daemon threads (capture + cleanup) that share one `stop_event` and write into a reserved `sessions/_continuous/` directory. The existing on-demand recording (Spec 1) coexists untouched on its own `sessions/sess_xxx/` directories. Token-efficiency for the subagent is handled at query time by a pure uniform-in-time sampling function — no capture-time dedupe.

**Tech Stack:** Python 3.13, `mcp>=1.0` (FastMCP / stdio), `mss>=9.0`, `Pillow>=10.0`, `pytest`. All already installed.

**Prerequisite:** Spec 1 / Foundation is landed on `feat/foundation`. 35 tests green. Real-screen smoke passed. Spec 2 design doc at `docs/superpowers/specs/2026-04-18-claudeyes-continuous-design.md`.

---

## File structure

```
src/claude_eyes/
├── config.py         # Task 1   — new constants + ServerConfig fields + env
├── session.py        # unchanged
├── storage.py        # Tasks 2-4 — prune_by_age, prune_by_size, frames_in_time_range
├── recorder.py       # unchanged
├── continuous.py     # Tasks 5-6 — NEW (sample_frames, ContinuousHandle, threads)
└── server.py         # Tasks 7-9 — three new MCP tools + module state + lock

tests/
├── conftest.py       # unchanged
├── test_config.py    # Task 1 — extend
├── test_session.py   # unchanged
├── test_storage.py   # Tasks 2-4 — extend
├── test_recorder.py  # unchanged
├── test_continuous.py # Tasks 5-6 — NEW
└── test_server.py    # Tasks 7-10 — extend

.claude/
├── skills/
│   ├── analyze-screen/SKILL.md         # unchanged
│   └── review-recent-activity/SKILL.md # Task 11 — NEW
├── hooks/
│   ├── cleanup_orphan_sessions.py      # unchanged
│   ├── log_recording.py                # unchanged
│   └── log_continuous_start.py         # Task 12 — NEW
└── settings.json                       # Task 12 — extend

CLAUDE.md           # Task 13 — extend
```

---

## Task 1: Config extensions (constants + ServerConfig fields + env)

**Files:**
- Modify: `src/claude_eyes/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_config.py`:

```python
from claude_eyes.config import (
    CLEANUP_TICK_SECONDS,
    CONTINUOUS_SESSION_DIR_NAME,
    DEFAULT_CONTINUOUS_DISK_CAP_MB,
    DEFAULT_CONTINUOUS_FPS,
    DEFAULT_CONTINUOUS_RESOLUTION_SCALE,
    DEFAULT_CONTINUOUS_RETENTION_S,
    DEFAULT_QUERY_MAX_FRAMES,
)


def test_continuous_constants_defaults() -> None:
    assert DEFAULT_CONTINUOUS_FPS == 2
    assert DEFAULT_CONTINUOUS_RETENTION_S == 300
    assert DEFAULT_CONTINUOUS_RESOLUTION_SCALE == 0.75
    assert DEFAULT_CONTINUOUS_DISK_CAP_MB == 1024
    assert DEFAULT_QUERY_MAX_FRAMES == 30
    assert CONTINUOUS_SESSION_DIR_NAME == "_continuous"
    assert CLEANUP_TICK_SECONDS == 5


def test_server_config_reads_continuous_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_EYES_CONTINUOUS_FPS", "5")
    monkeypatch.setenv("CLAUDE_EYES_RETENTION_S", "600")
    monkeypatch.setenv("CLAUDE_EYES_CONTINUOUS_RESOLUTION_SCALE", "0.5")
    monkeypatch.setenv("CLAUDE_EYES_DISK_CAP_MB", "2048")

    cfg = ServerConfig.from_env()

    assert cfg.continuous_fps == 5
    assert cfg.continuous_retention_s == 600
    assert cfg.continuous_resolution_scale == 0.5
    assert cfg.continuous_disk_cap_mb == 2048


def test_server_config_continuous_defaults_when_env_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "CLAUDE_EYES_CONTINUOUS_FPS",
        "CLAUDE_EYES_RETENTION_S",
        "CLAUDE_EYES_CONTINUOUS_RESOLUTION_SCALE",
        "CLAUDE_EYES_DISK_CAP_MB",
    ):
        monkeypatch.delenv(var, raising=False)

    cfg = ServerConfig.from_env()

    assert cfg.continuous_fps == DEFAULT_CONTINUOUS_FPS
    assert cfg.continuous_retention_s == DEFAULT_CONTINUOUS_RETENTION_S
    assert cfg.continuous_resolution_scale == DEFAULT_CONTINUOUS_RESOLUTION_SCALE
    assert cfg.continuous_disk_cap_mb == DEFAULT_CONTINUOUS_DISK_CAP_MB
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_config.py -v
```
Expected: 3 collection/import errors — the new names don't exist yet.

- [ ] **Step 3: Extend `src/claude_eyes/config.py`**

Add the following constants **after** the existing ones (keep existing constants exactly as they are):

```python
DEFAULT_CONTINUOUS_FPS: int = 2
DEFAULT_CONTINUOUS_RETENTION_S: int = 300
DEFAULT_CONTINUOUS_RESOLUTION_SCALE: float = 0.75
DEFAULT_CONTINUOUS_DISK_CAP_MB: int = 1024
DEFAULT_QUERY_MAX_FRAMES: int = 30
CONTINUOUS_SESSION_DIR_NAME: str = "_continuous"
CLEANUP_TICK_SECONDS: int = 5
```

Add four fields to `ServerConfig` (keep the existing three fields first, defaults preserve backward compatibility):

```python
@dataclass(frozen=True)
class ServerConfig:
    """User-controlled config, read once from env vars at server startup."""

    monitor: int = 0
    include_cursor: bool = False
    sessions_dir: Path = Path("sessions")
    continuous_fps: int = DEFAULT_CONTINUOUS_FPS
    continuous_retention_s: int = DEFAULT_CONTINUOUS_RETENTION_S
    continuous_resolution_scale: float = DEFAULT_CONTINUOUS_RESOLUTION_SCALE
    continuous_disk_cap_mb: int = DEFAULT_CONTINUOUS_DISK_CAP_MB

    @classmethod
    def from_env(cls) -> ServerConfig:
        return cls(
            monitor=int(os.environ.get("CLAUDE_EYES_MONITOR", "0")),
            include_cursor=_parse_bool(os.environ.get("CLAUDE_EYES_INCLUDE_CURSOR", "false")),
            sessions_dir=Path(os.environ.get("CLAUDE_EYES_SESSIONS_DIR", "sessions")),
            continuous_fps=int(
                os.environ.get("CLAUDE_EYES_CONTINUOUS_FPS", str(DEFAULT_CONTINUOUS_FPS))
            ),
            continuous_retention_s=int(
                os.environ.get("CLAUDE_EYES_RETENTION_S", str(DEFAULT_CONTINUOUS_RETENTION_S))
            ),
            continuous_resolution_scale=float(
                os.environ.get(
                    "CLAUDE_EYES_CONTINUOUS_RESOLUTION_SCALE",
                    str(DEFAULT_CONTINUOUS_RESOLUTION_SCALE),
                )
            ),
            continuous_disk_cap_mb=int(
                os.environ.get("CLAUDE_EYES_DISK_CAP_MB", str(DEFAULT_CONTINUOUS_DISK_CAP_MB))
            ),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_config.py -v
```
Expected: all existing config tests + 3 new tests green.

- [ ] **Step 5: Commit**

```bash
git add src/claude_eyes/config.py tests/test_config.py
git commit -m "feat(config): add continuous-mode constants and ServerConfig fields"
```

---

## Task 2: Storage — `prune_by_age`

**Files:**
- Modify: `src/claude_eyes/storage.py`
- Modify: `tests/test_storage.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_storage.py`:

```python
from claude_eyes.storage import prune_by_age


def _touch_frame(session_dir: Path, index: int, ts_ms: int) -> Path:
    """Write a tiny JPEG with the right filename so it can be pruned by age."""
    return save_frame(session_dir, index, ts_ms, _img())


def test_prune_by_age_removes_only_old_frames(tmp_path: Path) -> None:
    sess = tmp_path / "p_age"
    _touch_frame(sess, 0, 1000)    # age 4000 ms at now=5000
    _touch_frame(sess, 1, 3000)    # age 2000 ms
    _touch_frame(sess, 2, 4800)    # age  200 ms

    removed = prune_by_age(sess, max_age_ms=2500, now_ms=5000)

    assert removed == 1
    remaining = sorted(p.name for p in sess.glob("frame_*.jpg"))
    assert remaining == [
        "frame_00001_0000003000.jpg",
        "frame_00002_0000004800.jpg",
    ]


def test_prune_by_age_ignores_missing_dir(tmp_path: Path) -> None:
    assert prune_by_age(tmp_path / "never", max_age_ms=1000, now_ms=2000) == 0


def test_prune_by_age_tolerates_malformed_filenames(tmp_path: Path) -> None:
    sess = tmp_path / "p_age_bad"
    sess.mkdir()
    (sess / "frame_bad_name.jpg").write_bytes(b"not a frame")
    _touch_frame(sess, 0, 1000)

    removed = prune_by_age(sess, max_age_ms=500, now_ms=5000)

    assert removed == 1                        # only the well-named stale frame
    assert (sess / "frame_bad_name.jpg").exists()  # malformed file untouched
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_storage.py -v
```
Expected: `ImportError: cannot import name 'prune_by_age'`.

- [ ] **Step 3: Append implementation to `src/claude_eyes/storage.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_storage.py -v
```
Expected: all existing storage tests + 3 new tests green.

- [ ] **Step 5: Commit**

```bash
git add src/claude_eyes/storage.py tests/test_storage.py
git commit -m "feat(storage): add prune_by_age helper"
```

---

## Task 3: Storage — `prune_by_size`

**Files:**
- Modify: `src/claude_eyes/storage.py`
- Modify: `tests/test_storage.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_storage.py`:

```python
from claude_eyes.storage import prune_by_size


def test_prune_by_size_removes_oldest_first(tmp_path: Path) -> None:
    sess = tmp_path / "p_size"
    _touch_frame(sess, 0, 1000)
    _touch_frame(sess, 1, 2000)
    _touch_frame(sess, 2, 3000)
    total = sum(p.stat().st_size for p in sess.glob("frame_*.jpg"))
    # target: keep roughly the last one
    target = int(total * 0.4)

    removed = prune_by_size(sess, max_bytes=target)

    assert removed >= 1
    remaining = sorted(p.name for p in sess.glob("frame_*.jpg"))
    # oldest (index 0) must be gone; newest (index 2) must survive
    assert not any("00000" in name for name in remaining)
    assert any("00002" in name for name in remaining)


def test_prune_by_size_under_cap_is_noop(tmp_path: Path) -> None:
    sess = tmp_path / "p_size_noop"
    _touch_frame(sess, 0, 1000)
    _touch_frame(sess, 1, 2000)

    removed = prune_by_size(sess, max_bytes=10 * 1024 * 1024)

    assert removed == 0
    assert len(list(sess.glob("frame_*.jpg"))) == 2


def test_prune_by_size_missing_dir(tmp_path: Path) -> None:
    assert prune_by_size(tmp_path / "nope", max_bytes=1000) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_storage.py -v
```
Expected: `ImportError: cannot import name 'prune_by_size'`.

- [ ] **Step 3: Append implementation**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_storage.py -v
```
Expected: all storage tests green.

- [ ] **Step 5: Commit**

```bash
git add src/claude_eyes/storage.py tests/test_storage.py
git commit -m "feat(storage): add prune_by_size helper"
```

---

## Task 4: Storage — `frames_in_time_range`

**Files:**
- Modify: `src/claude_eyes/storage.py`
- Modify: `tests/test_storage.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_storage.py`:

```python
from claude_eyes.storage import frames_in_time_range


def test_frames_in_time_range_filters_and_sorts(tmp_path: Path) -> None:
    sess = tmp_path / "p_range"
    _touch_frame(sess, 0, 100)
    _touch_frame(sess, 1, 500)
    _touch_frame(sess, 2, 900)
    _touch_frame(sess, 3, 1300)

    result = frames_in_time_range(sess, oldest_ts_ms=400, newest_ts_ms=1000)

    assert [f["timestamp_ms"] for f in result] == [500, 900]
    assert [f["index"] for f in result] == [1, 2]


def test_frames_in_time_range_inclusive_bounds(tmp_path: Path) -> None:
    sess = tmp_path / "p_range_inc"
    _touch_frame(sess, 0, 1000)
    _touch_frame(sess, 1, 2000)

    result = frames_in_time_range(sess, oldest_ts_ms=1000, newest_ts_ms=2000)

    assert len(result) == 2


def test_frames_in_time_range_missing_dir(tmp_path: Path) -> None:
    assert frames_in_time_range(tmp_path / "nope", 0, 10_000) == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_storage.py -v
```
Expected: `ImportError: cannot import name 'frames_in_time_range'`.

- [ ] **Step 3: Append implementation**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_storage.py -v
```
Expected: all storage tests green.

- [ ] **Step 5: Commit**

```bash
git add src/claude_eyes/storage.py tests/test_storage.py
git commit -m "feat(storage): add frames_in_time_range helper"
```

---

## Task 5: `sample_frames` pure function

**Files:**
- Create: `src/claude_eyes/continuous.py` (initial skeleton with just `sample_frames`)
- Create: `tests/test_continuous.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_continuous.py`:
```python
"""Tests for claude_eyes.continuous."""
from __future__ import annotations

from claude_eyes.continuous import sample_frames
from claude_eyes.storage import FrameInfo


def _frames(n: int) -> list[FrameInfo]:
    return [
        {"path": f"/tmp/frame_{i:05d}_{i * 100:010d}.jpg", "index": i, "timestamp_ms": i * 100}
        for i in range(n)
    ]


def test_sample_returns_input_unchanged_when_under_max() -> None:
    frames = _frames(5)
    assert sample_frames(frames, max_frames=30) == frames


def test_sample_picks_evenly_spaced_with_endpoints() -> None:
    frames = _frames(100)
    result = sample_frames(frames, max_frames=10)

    assert len(result) == 10
    # endpoints preserved
    assert result[0] == frames[0]
    assert result[-1] == frames[-1]
    # monotonically increasing timestamps
    ts = [f["timestamp_ms"] for f in result]
    assert ts == sorted(ts)


def test_sample_max_one_returns_newest() -> None:
    frames = _frames(50)
    result = sample_frames(frames, max_frames=1)
    assert result == [frames[-1]]


def test_sample_empty_input() -> None:
    assert sample_frames([], max_frames=10) == []


def test_sample_zero_max_returns_empty() -> None:
    assert sample_frames(_frames(10), max_frames=0) == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_continuous.py -v
```
Expected: `ModuleNotFoundError: No module named 'claude_eyes.continuous'`.

- [ ] **Step 3: Create the module with `sample_frames` only (threads come in Task 6)**

`src/claude_eyes/continuous.py`:
```python
"""Continuous rolling-buffer capture and query-time sampling."""
from __future__ import annotations

from .storage import FrameInfo


def sample_frames(frames: list[FrameInfo], max_frames: int) -> list[FrameInfo]:
    """Return up to ``max_frames`` frames evenly spaced across the input.

    - If ``max_frames <= 0``: returns ``[]``.
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_continuous.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/claude_eyes/continuous.py tests/test_continuous.py
git commit -m "feat(continuous): add uniform-in-time frame sampling"
```

---

## Task 6: Continuous capture + cleanup threads (`start_continuous`, `stop_continuous`)

**Files:**
- Modify: `src/claude_eyes/continuous.py`
- Modify: `tests/test_continuous.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_continuous.py`:

```python
import time
from pathlib import Path

import pytest

from tests.test_recorder import _FakeMSS  # reuse fake backend from Spec 1


@pytest.fixture
def fake_mss_for_continuous(monkeypatch: pytest.MonkeyPatch) -> None:
    import claude_eyes.continuous as cont_mod

    monkeypatch.setattr(cont_mod.mss, "mss", _FakeMSS)


def test_start_continuous_captures_frames(tmp_path: Path, fake_mss_for_continuous: None) -> None:
    from claude_eyes.continuous import start_continuous, stop_continuous

    sess = tmp_path / "_continuous"
    handle = start_continuous(
        session_dir=sess,
        fps=10,
        retention_s=60,
        resolution_scale=1.0,
        disk_cap_bytes=10 * 1024 * 1024,
        monitor_index=0,
    )
    time.sleep(0.45)
    frames_kept, bytes_kept = stop_continuous(handle)

    assert frames_kept >= 2
    assert bytes_kept > 0
    assert len(list(sess.glob("frame_*.jpg"))) == frames_kept


def test_start_continuous_stops_cleanly(tmp_path: Path, fake_mss_for_continuous: None) -> None:
    from claude_eyes.continuous import start_continuous, stop_continuous

    handle = start_continuous(
        session_dir=tmp_path / "_continuous",
        fps=5,
        retention_s=60,
        resolution_scale=1.0,
        disk_cap_bytes=10 * 1024 * 1024,
        monitor_index=0,
    )
    frames_kept, _ = stop_continuous(handle, timeout=2.0)
    assert frames_kept >= 0
    assert not handle.capture_thread.is_alive()
    assert not handle.cleanup_thread.is_alive()


def test_continuous_cleanup_prunes_by_age(tmp_path: Path, fake_mss_for_continuous: None) -> None:
    """Short retention so cleanup reaps frames while capture is still running."""
    from claude_eyes.continuous import start_continuous, stop_continuous

    sess = tmp_path / "_continuous"
    # retention_s = 1 + CLEANUP_TICK_SECONDS (5) = cleanup triggers once,
    # but at fps=20 we generate plenty for it to bite.
    handle = start_continuous(
        session_dir=sess,
        fps=20,
        retention_s=1,
        resolution_scale=1.0,
        disk_cap_bytes=100 * 1024 * 1024,
        monitor_index=0,
    )
    time.sleep(6.5)  # let cleanup tick at least once with stale frames present
    frames_kept, _ = stop_continuous(handle)

    # we generated ~130 frames over 6.5s at fps=20; after cleanup most should be gone
    # (retention 1s at 20fps = ~20 frames + 1s grace window; cap well above the ~100 frames expected)
    assert frames_kept < 130, f"expected cleanup to trim frames, got {frames_kept}"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_continuous.py -v
```
Expected: `ImportError: cannot import name 'start_continuous' from 'claude_eyes.continuous'`.

- [ ] **Step 3: Extend `src/claude_eyes/continuous.py` with the full implementation**

Replace the current short module with the full version below. The `sample_frames` function above is preserved — the rewrite just adds imports, dataclasses, and the thread functions. Use Write (full rewrite).

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_continuous.py -v
```
Expected: 8 passed (5 from Task 5 + 3 new).

**Note:** `test_continuous_cleanup_prunes_by_age` sleeps 6.5 s so the cleanup thread (5 s tick) fires once. If it's flaky on a slow machine, re-run once. If it still fails, report.

- [ ] **Step 5: Run the full suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```
Expected: all prior tests green + 8 new continuous tests.

- [ ] **Step 6: Commit**

```bash
git add src/claude_eyes/continuous.py tests/test_continuous.py
git commit -m "feat(continuous): add capture+cleanup threads with rolling retention"
```

---

## Task 7: MCP tool `start_continuous_buffer`

**Files:**
- Modify: `src/claude_eyes/server.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Append failing test**

Append to `tests/test_server.py`:
```python
def test_start_continuous_buffer_activates_and_echoes_config(patched_server, tmp_path: Path) -> None:
    result = patched_server.start_continuous_buffer(fps=5, retention_s=60, resolution_scale=0.5)

    assert result["active"] is True
    assert result["config"]["fps"] == 5
    assert result["config"]["retention_s"] == 60
    assert result["config"]["resolution_scale"] == 0.5
    assert result["config"]["monitor"] == 0
    assert (tmp_path / "sessions" / "_continuous").exists()

    # cleanup so the handle doesn't leak into the next test
    patched_server.stop_continuous_buffer()


def test_start_continuous_buffer_rejects_double_start(patched_server) -> None:
    first = patched_server.start_continuous_buffer(fps=5)
    second = patched_server.start_continuous_buffer(fps=5)

    assert first["active"] is True
    assert "error" in second
    assert "already active" in second["error"]
    assert second["started_at"] == first["started_at"]

    patched_server.stop_continuous_buffer()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_server.py -v
```
Expected: `AttributeError: module 'claude_eyes.server' has no attribute 'start_continuous_buffer'`.

- [ ] **Step 3: Extend `src/claude_eyes/server.py`**

Add imports near the existing Spec 1 imports (keep existing imports exactly as they are):
```python
import threading
from .config import (
    CONTINUOUS_SESSION_DIR_NAME,
    DEFAULT_CONTINUOUS_FPS,
    DEFAULT_CONTINUOUS_RESOLUTION_SCALE,
    DEFAULT_CONTINUOUS_RETENTION_S,
    DEFAULT_QUERY_MAX_FRAMES,
)
from .continuous import ContinuousHandle, sample_frames, start_continuous, stop_continuous
from .storage import frames_in_time_range
```

Add module-level state **after** the existing `_active` dict:
```python
_continuous_handle: ContinuousHandle | None = None
_continuous_lock: threading.Lock = threading.Lock()
```

Add the tool **between** `cleanup_session` and `main()`:
```python
@mcp.tool()
def start_continuous_buffer(
    fps: int = DEFAULT_CONTINUOUS_FPS,
    retention_s: int = DEFAULT_CONTINUOUS_RETENTION_S,
    resolution_scale: float = DEFAULT_CONTINUOUS_RESOLUTION_SCALE,
) -> dict[str, Any]:
    """Begin continuous rolling-buffer capture.

    ONLY call this when the user has explicitly asked for the buffer to start.
    Never start it on your own — the user must know their screen is being
    recorded continuously. Stop with ``stop_continuous_buffer`` when the user
    no longer needs it.
    """
    global _continuous_handle
    with _continuous_lock:
        if _continuous_handle is not None:
            return {
                "error": "continuous buffer already active",
                "started_at": _continuous_handle.started_at_iso,
            }
        session_dir = _config.sessions_dir / CONTINUOUS_SESSION_DIR_NAME
        disk_cap_bytes = _config.continuous_disk_cap_mb * 1024 * 1024
        handle = start_continuous(
            session_dir=session_dir,
            fps=fps,
            retention_s=retention_s,
            resolution_scale=resolution_scale,
            disk_cap_bytes=disk_cap_bytes,
            monitor_index=_config.monitor,
        )
        _continuous_handle = handle
        return {
            "active": True,
            "started_at": handle.started_at_iso,
            "config": {
                "fps": fps,
                "retention_s": retention_s,
                "resolution_scale": resolution_scale,
                "disk_cap_mb": _config.continuous_disk_cap_mb,
                "monitor": _config.monitor,
            },
        }
```

Also update the `patched_server` fixture in `tests/test_server.py` so the fake-mss monkeypatch ALSO covers `claude_eyes.continuous.mss`. Replace the body of the `patched_server` fixture with:

```python
@pytest.fixture
def patched_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Patch env + mss BEFORE importing server, so module-level init uses them."""
    monkeypatch.setenv("CLAUDE_EYES_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("CLAUDE_EYES_MONITOR", "0")
    monkeypatch.setenv("CLAUDE_EYES_INCLUDE_CURSOR", "false")

    import importlib

    import claude_eyes.continuous as cont_mod
    import claude_eyes.recorder as rec_mod

    monkeypatch.setattr(rec_mod.mss, "mss", _FakeMSS)
    monkeypatch.setattr(cont_mod.mss, "mss", _FakeMSS)

    import claude_eyes.server as server

    importlib.reload(server)
    return server
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_server.py -v
```
Expected: all prior server tests + 2 new tests green.

- [ ] **Step 5: Commit**

```bash
git add src/claude_eyes/server.py tests/test_server.py
git commit -m "feat(server): add start_continuous_buffer tool"
```

---

## Task 8: MCP tool `stop_continuous_buffer`

**Files:**
- Modify: `src/claude_eyes/server.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_server.py`:
```python
def test_stop_continuous_buffer_returns_stats(patched_server) -> None:
    patched_server.start_continuous_buffer(fps=10)
    time.sleep(0.25)

    result = patched_server.stop_continuous_buffer()

    assert result["stopped"] is True
    assert result["frames_kept"] >= 1
    assert result["bytes_kept"] > 0


def test_stop_continuous_buffer_rejects_when_idle(patched_server) -> None:
    result = patched_server.stop_continuous_buffer()
    assert "error" in result
    assert "no active" in result["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_server.py -v
```
Expected: `AttributeError: ... 'stop_continuous_buffer'`.

- [ ] **Step 3: Append the tool to `server.py`** (immediately after `start_continuous_buffer`):

```python
@mcp.tool()
def stop_continuous_buffer() -> dict[str, Any]:
    """Stop the continuous rolling buffer. Frames on disk are left in place
    (the session-end hook will wipe them when Claude Code exits)."""
    global _continuous_handle
    with _continuous_lock:
        if _continuous_handle is None:
            return {"error": "no active continuous buffer"}
        frames_kept, bytes_kept = stop_continuous(_continuous_handle)
        _continuous_handle = None
        return {
            "stopped": True,
            "frames_kept": frames_kept,
            "bytes_kept": bytes_kept,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_server.py -v
```
Expected: all server tests green.

- [ ] **Step 5: Commit**

```bash
git add src/claude_eyes/server.py tests/test_server.py
git commit -m "feat(server): add stop_continuous_buffer tool"
```

---

## Task 9: MCP tool `query_buffer`

**Files:**
- Modify: `src/claude_eyes/server.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_server.py`:
```python
def test_query_buffer_returns_sampled_frames(patched_server) -> None:
    patched_server.start_continuous_buffer(fps=20)
    time.sleep(0.6)  # ~12 frames
    result = patched_server.query_buffer(time_range_s=10, max_frames=5)

    assert "frames" in result
    assert 1 <= len(result["frames"]) <= 5
    assert result["total_in_range"] >= len(result["frames"])
    assert all(set(f.keys()) >= {"path", "index", "timestamp_ms", "age_s"} for f in result["frames"])

    patched_server.stop_continuous_buffer()


def test_query_buffer_idle_returns_error(patched_server) -> None:
    result = patched_server.query_buffer(time_range_s=60)
    assert "error" in result


def test_query_buffer_empty_buffer_returns_empty_frames(patched_server) -> None:
    patched_server.start_continuous_buffer(fps=1)
    # immediately query — no frame captured yet
    result = patched_server.query_buffer(time_range_s=10, max_frames=5)

    assert result["frames"] == []
    assert result["total_in_range"] == 0

    patched_server.stop_continuous_buffer()


def test_query_buffer_clamps_time_range_beyond_retention(patched_server) -> None:
    patched_server.start_continuous_buffer(fps=10, retention_s=10)
    time.sleep(0.4)
    result = patched_server.query_buffer(time_range_s=9999, max_frames=5)

    assert "warning" in result
    assert "clamped" in result["warning"]

    patched_server.stop_continuous_buffer()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_server.py -v
```
Expected: `AttributeError: ... 'query_buffer'`.

- [ ] **Step 3: Append the tool to `server.py`** (immediately after `stop_continuous_buffer`):

```python
@mcp.tool()
def query_buffer(
    time_range_s: int,
    max_frames: int = DEFAULT_QUERY_MAX_FRAMES,
) -> dict[str, Any]:
    """Return an evenly-sampled subset of continuous-buffer frames from the
    last ``time_range_s`` seconds (capped at buffer retention)."""
    global _continuous_handle
    with _continuous_lock:
        if _continuous_handle is None:
            return {"error": "no active continuous buffer"}
        handle = _continuous_handle
        now_ms = int((time.monotonic() - handle.started_monotonic) * 1000)
        requested_oldest = now_ms - (time_range_s * 1000)
        buffer_oldest = max(0, now_ms - (handle.config.retention_s * 1000))
        clamped = requested_oldest < buffer_oldest
        oldest = buffer_oldest if clamped else requested_oldest

        all_frames = frames_in_time_range(
            handle.session_dir,
            oldest_ts_ms=oldest,
            newest_ts_ms=now_ms,
        )
        sampled = sample_frames(all_frames, max_frames)

        enriched = [
            {
                "path": f["path"],
                "index": f["index"],
                "timestamp_ms": f["timestamp_ms"],
                "age_s": round((now_ms - f["timestamp_ms"]) / 1000, 2),
            }
            for f in sampled
        ]
        result: dict[str, Any] = {
            "frames": enriched,
            "total_in_range": len(all_frames),
            "oldest_frame_age_s": enriched[0]["age_s"] if enriched else 0.0,
            "newest_frame_age_s": enriched[-1]["age_s"] if enriched else 0.0,
        }
        if clamped:
            effective_s = max(0, (now_ms - buffer_oldest) // 1000)
            result["warning"] = (
                f"time_range_s exceeded buffer age; clamped to {effective_s}s"
            )
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_server.py -v
```
Expected: all server tests green.

- [ ] **Step 5: Commit**

```bash
git add src/claude_eyes/server.py tests/test_server.py
git commit -m "feat(server): add query_buffer tool with clamped time range"
```

---

## Task 10: Coexistence integration test

**Files:**
- Modify: `tests/test_server.py`

- [ ] **Step 1: Append failing-or-passing test (implementation already covers it; this locks it down)**

Append to `tests/test_server.py`:
```python
def test_continuous_and_on_demand_coexist(patched_server, tmp_path: Path) -> None:
    """Buffer + on-demand run side-by-side on different directories."""
    cont = patched_server.start_continuous_buffer(fps=5)
    assert cont["active"] is True

    od = patched_server.start_recording(fps=10, resolution_scale=1.0, region=None, session_name="coexist")
    sid = od["session_id"]
    time.sleep(0.35)
    od_stop = patched_server.stop_recording(sid)
    assert od_stop["frames_count"] >= 1

    continuous_dir = tmp_path / "sessions" / "_continuous"
    on_demand_dir = tmp_path / "sessions" / sid
    assert continuous_dir.exists()
    assert on_demand_dir.exists()
    assert continuous_dir != on_demand_dir

    # continuous still active, no cross-contamination
    q = patched_server.query_buffer(time_range_s=30, max_frames=10)
    assert "frames" in q
    cont_stop = patched_server.stop_continuous_buffer()
    assert cont_stop["stopped"] is True

    patched_server.cleanup_session(sid)
```

- [ ] **Step 2: Run the test**

```bash
.venv/Scripts/python.exe -m pytest tests/test_server.py::test_continuous_and_on_demand_coexist -v
```
Expected: pass.

- [ ] **Step 3: Run the full suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```
Expected: ~47 passed (35 prior + 12 new across Tasks 1-10).

- [ ] **Step 4: Commit**

```bash
git add tests/test_server.py
git commit -m "test(server): lock down continuous + on-demand coexistence"
```

---

## Task 11: `review-recent-activity` skill

**Files:**
- Create: `.claude/skills/review-recent-activity/SKILL.md`

- [ ] **Step 1: Create the skill file**

`.claude/skills/review-recent-activity/SKILL.md`:
```markdown
---
name: review-recent-activity
description: Use when the user asks about something they recently did on screen — "what did I just do", "cosa ho fatto", "riassumi gli ultimi N minuti", "cosa è successo nel buffer", "ricordami cosa stavo facendo". Requires the continuous buffer to already be active (the user must have started it explicitly).
---

# review-recent-activity

Orchestrates a query against the continuous rolling buffer: pick a time range, sample frames, dispatch the `frame-analyzer` subagent, synthesize the answer.

## When to use

**Use when:**
- The user references recent past activity on their own screen.
- Phrasing includes "what did I do", "cosa ho fatto", "ultimi minuti", "just now", "a minute ago".
- The continuous buffer is (or was recently) active.

**Do NOT use when:**
- The user wants to analyse a specific animation or UI flow happening now → use `analyze-screen` instead.
- The user has not started the continuous buffer → tell them how to start it and stop.
- A single fresh screenshot would answer the question → use the native screenshot tool.

## Workflow

1. **Check the buffer is active.** If a previous `query_buffer` / `start_continuous_buffer` response indicated the buffer is idle, say so and ask the user whether to start it. Don't start it silently.

2. **Pick `time_range_s` from phrasing.** Defaults:
   - "just now" / "a moment ago" → 60 s
   - "the last minute" → 60 s
   - "the last few minutes" / "gli ultimi minuti" → 180 s
   - "the last N minutes" → N * 60 s
   - No explicit range → 120 s

3. **Call `mcp__claude_eyes__query_buffer(time_range_s, max_frames=30)`.**
   - If `"error"` is in the result: tell the user the buffer is not active.
   - If `frames` is empty: tell the user nothing was captured in the requested range.
   - If `warning` is present: tell the user the range was clamped to the actual buffer age.

4. **Dispatch `frame-analyzer`** via the `Task` tool:
   - `subagent_type: "frame-analyzer"`
   - Prompt includes the frame paths (one per line, in order), the user's question, and the `age_s` of the oldest/newest frames so the subagent has temporal context.

5. **Synthesize** the subagent's report into a direct answer. Reference specific moments by their age ("~45 s ago you…") rather than file indices.

6. **Do not call `cleanup_session`.** The continuous buffer is not a regular session — it's managed by `start_continuous_buffer` / `stop_continuous_buffer`.

## Common mistakes to avoid

- **Starting the buffer silently.** The user must ask explicitly. Privacy is at stake.
- **Passing all frames to the subagent.** `max_frames=30` is the default for a reason; don't override upward without cause.
- **Treating the buffer as a regular session.** No `cleanup_session` — `stop_continuous_buffer` is the correct teardown.
- **Answering from an empty result.** If the subagent returns "nothing notable", relay that honestly; don't invent activity.

## Related

- Subagent: `.claude/agents/frame-analyzer.md` (reused, no changes)
- Sibling skill: `.claude/skills/analyze-screen/SKILL.md` (on-demand animation analysis)
- Project guidance: `CLAUDE.md`
```

- [ ] **Step 2: Commit**

```bash
git add .claude/skills/review-recent-activity/SKILL.md
git commit -m "feat(skill): add review-recent-activity for continuous-buffer queries"
```

---

## Task 12: Privacy-guardrail hook

**Files:**
- Create: `.claude/hooks/log_continuous_start.py`
- Modify: `.claude/settings.json`

- [ ] **Step 1: Create the hook script**

`.claude/hooks/log_continuous_start.py`:
```python
#!/usr/bin/env python3
"""PostToolUse hook for ``mcp__claude_eyes__start_continuous_buffer``.

Logs the event to ``.claude/logs/continuous.jsonl`` and injects an
``additionalContext`` reminder so Claude tells the user that their screen
is now being recorded continuously (privacy guardrail).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", "."))
    log_dir = project_dir / ".claude" / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"[claude-eyes] cannot create log dir: {exc}", file=sys.stderr)
        return 0

    tool_input = payload.get("tool_input") or {}
    tool_response = payload.get("tool_response") or {}

    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "event": "continuous_buffer_started",
        "fps": tool_input.get("fps"),
        "retention_s": tool_input.get("retention_s"),
        "resolution_scale": tool_input.get("resolution_scale"),
        "started_at": tool_response.get("started_at"),
    }

    try:
        with (log_dir / "continuous.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError as exc:
        print(f"[claude-eyes] log write failed: {exc}", file=sys.stderr)

    reminder = (
        "[claude-eyes] The continuous screen buffer is now ACTIVE. "
        "You MUST tell the user in your next response that their screen is "
        "being recorded continuously, and remind them they can stop it with "
        "stop_continuous_buffer at any time."
    )
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": reminder,
        }
    }
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Add the hook entry to `.claude/settings.json`**

Edit `.claude/settings.json` so the `PostToolUse` array contains both the existing `log_recording.py` matcher AND the new `log_continuous_start.py` matcher:

```json
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "hooks": {
    "SessionEnd": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python \"$CLAUDE_PROJECT_DIR/.claude/hooks/cleanup_orphan_sessions.py\"",
            "timeout": 30
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "mcp__claude_eyes__stop_recording",
        "hooks": [
          {
            "type": "command",
            "command": "python \"$CLAUDE_PROJECT_DIR/.claude/hooks/log_recording.py\"",
            "timeout": 10
          }
        ]
      },
      {
        "matcher": "mcp__claude_eyes__start_continuous_buffer",
        "hooks": [
          {
            "type": "command",
            "command": "python \"$CLAUDE_PROJECT_DIR/.claude/hooks/log_continuous_start.py\"",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 3: Validate JSON and Python syntax**

```bash
python -c "import json; json.load(open('.claude/settings.json')); print('settings.json OK')"
python -c "import ast; ast.parse(open('.claude/hooks/log_continuous_start.py').read()); print('hook OK')"
```
Expected: both print OK.

- [ ] **Step 4: Commit**

```bash
git add .claude/hooks/log_continuous_start.py .claude/settings.json
git commit -m "feat(hooks): privacy reminder on continuous-buffer start"
```

---

## Task 13: CLAUDE.md — add "Continuous mode" section

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Append the new section before the final `## Related files` section**

Open `CLAUDE.md` and insert the following block **immediately before** the `## Related files` heading:

```markdown
## Continuous mode (rolling buffer)

claudeEyes also supports a **continuous rolling buffer**: a low-fps background capture that keeps the last N minutes of screen activity on disk, for "what did I just do" style questions. It is separate from on-demand recording and coexists with it.

### Hard rules

- **Never start the buffer on your own.** It starts ONLY when the user explicitly asks ("parti con il buffer", "attiva la registrazione continua", "start the continuous buffer", "record my screen in the background").
- **Always inform the user when the buffer starts or stops.** The privacy guardrail hook will inject a reminder when it starts; act on it.
- **Use `review-recent-activity` skill** for queries against the buffer. Use `analyze-screen` skill for on-demand animation / UI analysis. They do not overlap.

### The three continuous-mode tools

| Tool | When |
|---|---|
| `start_continuous_buffer(fps=2, retention_s=300, resolution_scale=0.75)` | User explicitly asks to begin. |
| `stop_continuous_buffer()` | User explicitly asks to stop, or when Claude Code session ends. |
| `query_buffer(time_range_s, max_frames=30)` | User asks about recent activity. Sampled frames are then passed to the `frame-analyzer` subagent. |

Defaults are chosen to be cheap on disk (~200 MB for 5 min at 2 fps / scale 0.75). User can override via env vars (`CLAUDE_EYES_CONTINUOUS_FPS`, `CLAUDE_EYES_RETENTION_S`, `CLAUDE_EYES_CONTINUOUS_RESOLUTION_SCALE`, `CLAUDE_EYES_DISK_CAP_MB`).

### Response contract

- Tool errors are structured (`{"error": "..."}`) — never raise. Handle them by telling the user what to do next.
- `query_buffer` may return a `warning` field when the requested range exceeds actual buffer age; relay that honestly.
```

- [ ] **Step 2: Verify the file still reads cleanly end-to-end**

```bash
wc -l CLAUDE.md
```
Expected: somewhere between 120 and 180 lines (was ~90 + ~40 added). Still well under the 200-line guideline.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): add Continuous mode guidance and hard rules"
```

---

## Task 14: Full suite green + mypy + ruff + final smoke

**Files:**
- Modify: `pyproject.toml` (only if mypy complains about missing stubs)

- [ ] **Step 1: Run the full suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```
Expected: **~47 passed** (35 from Spec 1 + 12 new). No failures.

- [ ] **Step 2: Run mypy**

```bash
.venv/Scripts/python.exe -m mypy src/claude_eyes
```
Expected: `Success: no issues found in 7 source files`.

If mypy complains about a missing return annotation, Optional typing, or tuple unpacking, fix it minimally (match the style of existing modules — `from __future__ import annotations`, PEP-604 unions). Re-run until clean.

- [ ] **Step 3: Run ruff**

```bash
.venv/Scripts/python.exe -m ruff check src tests
```
Expected: `All checks passed!`.

If ruff flags unused imports in `server.py` (e.g. `threading`, `ContinuousHandle`): verify they are actually used by the new tools/state. Remove only if genuinely unused.

- [ ] **Step 4: Real-screen smoke**

Run (replaces any leftover `sessions/` state):
```bash
.venv/Scripts/python.exe -c "
import time
from claude_eyes.server import (
    start_continuous_buffer,
    query_buffer,
    stop_continuous_buffer,
    start_recording,
    stop_recording,
    cleanup_session,
)
print('start continuous:', start_continuous_buffer(fps=3, retention_s=60, resolution_scale=0.5))
time.sleep(2.0)
print('mid query:', {k: v if k != 'frames' else f'<{len(v)} frames>' for k, v in query_buffer(time_range_s=5, max_frames=5).items()})
od = start_recording(fps=5, resolution_scale=0.5, region=None, session_name='ondemand_during_continuous')
time.sleep(0.5)
od_stop = stop_recording(od['session_id'])
print('on-demand frames:', od_stop['frames_count'])
cleanup_session(od['session_id'])
print('stop continuous:', stop_continuous_buffer())
"
```
Expected: continuous starts, mid-query returns sampled frames, on-demand succeeds in parallel, stop returns stats. No tracebacks.

- [ ] **Step 5: Verify no leftover files**

```bash
ls sessions/ 2>/dev/null
cat sessions/.registry.json 2>/dev/null
```
Expected: no leftover session folders; `.registry.json` is `{}` (or absent).

- [ ] **Step 6: Commit any lint/type fixes from Steps 2-3**

If Steps 2 or 3 required edits, commit them now:
```bash
git add -p
git commit -m "chore: satisfy mypy/ruff after continuous-mode implementation"
```

If nothing was changed in Steps 2-3, this step is a no-op.

---

## Self-Review

**1. Spec coverage.** Each spec section maps to at least one task:

| Spec section | Task(s) |
|---|---|
| `start_continuous_buffer` tool | 7 |
| `stop_continuous_buffer` tool | 8 |
| `query_buffer` tool | 9 |
| `ContinuousHandle` dataclass | 6 |
| Capture thread | 6 |
| Cleanup thread | 6 |
| `sample_frames` function | 5 (extended in 6) |
| `prune_by_age` | 2 |
| `prune_by_size` | 3 |
| `frames_in_time_range` | 4 |
| Config constants + env vars | 1 |
| Coexistence with on-demand | 10 |
| `review-recent-activity` skill | 11 |
| Privacy-guardrail hook | 12 |
| CLAUDE.md "Continuous mode" section | 13 |
| Lint/type/full-suite green | 14 |
| Real-screen smoke | 14 (step 4) |

No spec requirement is left without a task.

**2. Placeholder scan.** No "TBD", "TODO", "add appropriate error handling", "similar to…", or undefined symbols. Every code step shows full code. Every test step shows exact command and expected output.

**3. Type consistency.**
- `ContinuousHandle` fields introduced in Task 6 and consumed in Tasks 7-9 — name/type match.
- `ContinuousConfig` introduced in Task 6 and referenced (`.config.retention_s`) in Task 9 — match.
- `FrameInfo` TypedDict from Spec 1 used unchanged in Tasks 2-5, 9 — match.
- `frames_in_time_range(session_dir, oldest_ts_ms, newest_ts_ms)` — same keyword arg names in Task 4 definition and Task 9 call site.
- `sample_frames(frames, max_frames)` — same signature from Task 5 through Task 9.
- `start_continuous(*, session_dir, fps, retention_s, resolution_scale, disk_cap_bytes, monitor_index)` — keyword-only; call site in Task 7 matches.
- `stop_continuous(handle, timeout=5.0) -> tuple[int, int]` — consumed in Task 8 without positional timeout; match.
- Server module-level `_continuous_handle: ContinuousHandle | None` and `_continuous_lock: threading.Lock` — introduced once in Task 7, reused in Tasks 8-9 unchanged.

No drift found. Plan is ready to execute.

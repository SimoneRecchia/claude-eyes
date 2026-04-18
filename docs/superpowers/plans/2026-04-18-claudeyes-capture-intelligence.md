# claudeEyes Capture-time Intelligence — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Spec 5 — a new `activity.py` module that detects leading/trailing dead-frame ranges and computes effective fps; wire results into `stop_recording` and `query_buffer` responses; add a new opt-in `trim_session` MCP tool; update skills and `CLAUDE.md`.

**Architecture:** A post-capture Python pass downscales every frame to 128×72 (PIL bilinear), computes mean-absolute-diff scores between consecutive thumbnails, derives an adaptive threshold (`baseline_25pct + 3 × MAD`, clamped), and returns `(first_score, last_score + 1)` as the active range (or `None` if nothing exceeds threshold). Scoring is chunked at 500 frames to cap peak memory. `stop_recording` and `query_buffer` swallow exceptions so capture never breaks; `trim_session` is the only destructive tool.

**Tech Stack:** Python 3.13, `numpy>=1.26`, `Pillow>=10.0`, `mcp>=1.0`, `pytest`. No new dependencies.

**Prerequisite:** Spec 1+2+3+4 shipped on `main`. Spec 5 design at `docs/superpowers/specs/2026-04-18-claudeyes-capture-intelligence-design.md`. New branch `feat/capture-intelligence` already created with the spec commit.

---

## File structure

```
src/claude_eyes/
├── activity.py            # Tasks 1-3 — NEW: score, fps, detect, helpers
└── server.py              # Tasks 4-6 — stop_recording+query_buffer+trim_session

tests/
├── test_activity.py       # Tasks 1-3 — NEW
└── test_server.py         # Tasks 4-6 — extend

.claude/skills/
├── analyze-screen/SKILL.md              # Task 7
├── analyze-page-animation/SKILL.md      # Task 7
└── review-recent-activity/SKILL.md      # Task 7

CLAUDE.md                  # Task 8
```

---

## Task 1: `score_frame_motion` and `compute_fps_effective`

**Files:**
- Create: `src/claude_eyes/activity.py` (starts with 2 pure functions + module docstring)
- Create: `tests/test_activity.py`

- [ ] **Step 1: Write failing tests**

`tests/test_activity.py`:
```python
"""Tests for claude_eyes.activity — activity detection and fps reporting."""
from __future__ import annotations

import numpy as np

from claude_eyes.activity import compute_fps_effective, score_frame_motion


def test_score_frame_motion_identical_frames_returns_zero() -> None:
    arr = np.array([[[100, 100, 100]]], dtype=np.uint8)
    assert score_frame_motion(arr, arr) == 0.0


def test_score_frame_motion_fully_changed_returns_255() -> None:
    a = np.array([[[0, 0, 0]]], dtype=np.uint8)
    b = np.array([[[255, 255, 255]]], dtype=np.uint8)
    assert score_frame_motion(a, b) == 255.0


def test_score_frame_motion_returns_mean_abs_diff() -> None:
    a = np.array([[[0, 0, 0]]], dtype=np.uint8)
    b = np.array([[[120, 60, 30]]], dtype=np.uint8)
    # (120 + 60 + 30) / 3 = 70.0
    assert score_frame_motion(a, b) == 70.0


def test_compute_fps_effective_basic() -> None:
    assert compute_fps_effective(100, 4.0) == 25.0


def test_compute_fps_effective_zero_duration_returns_zero() -> None:
    assert compute_fps_effective(10, 0.0) == 0.0


def test_compute_fps_effective_negative_duration_returns_zero() -> None:
    assert compute_fps_effective(10, -1.0) == 0.0


def test_compute_fps_effective_single_frame_returns_zero() -> None:
    assert compute_fps_effective(1, 1.0) == 0.0


def test_compute_fps_effective_rounded_to_two_decimals() -> None:
    # 100 / 3.333 = 30.003… -> 30.0
    assert compute_fps_effective(100, 3.333) == 30.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_activity.py -v
```
Expected: `ModuleNotFoundError: No module named 'claude_eyes.activity'`.

- [ ] **Step 3: Create `src/claude_eyes/activity.py` with only the two helpers**

```python
"""Post-capture activity detection and fps-effective reporting.

Given a completed recording (a directory of frame JPEGs), this module:

- Scores motion between consecutive frames with mean absolute pixel
  difference on 128×72 thumbnails (cheap, deterministic).
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_activity.py -v
```
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/claude_eyes/activity.py tests/test_activity.py
git commit -m "feat(activity): add score_frame_motion and compute_fps_effective"
```

---

## Task 2: `_downscale_frame`, `_compute_scores`, `_adaptive_threshold`

**Files:**
- Modify: `src/claude_eyes/activity.py` (append helpers)
- Modify: `tests/test_activity.py` (append tests)

- [ ] **Step 1: Append failing tests**

```python
from pathlib import Path

from PIL import Image as _I

from claude_eyes.activity import _adaptive_threshold, _compute_scores, _downscale_frame
from claude_eyes.storage import save_frame


def _solid_img(color: tuple[int, int, int] = (100, 100, 100), size: int = 32) -> _I.Image:
    return _I.new("RGB", (size, size), color)


def test_downscale_frame_returns_128x72_uint8(tmp_path: Path) -> None:
    img = _I.new("RGB", (800, 600), (50, 100, 150))
    p = tmp_path / "test.jpg"
    img.save(p, "JPEG", quality=85)

    result = _downscale_frame(p)

    # numpy array is (H, W, 3); PIL thumb target 128×72 -> (72, 128, 3)
    assert result.shape == (72, 128, 3)
    assert result.dtype == np.uint8
    # Solid-color JPEG should still be near-solid after downscale
    assert abs(int(result[0, 0, 0]) - 50) < 5
    assert abs(int(result[0, 0, 1]) - 100) < 5
    assert abs(int(result[0, 0, 2]) - 150) < 5


def test_adaptive_threshold_static_scene_clamps_mad_floor() -> None:
    # All zeros: baseline=0, MAD=0 -> clamp MAD to 0.5 -> threshold = 1.5
    scores = [0.0, 0.0, 0.0, 0.0]
    t = _adaptive_threshold(scores)
    assert abs(t - 1.5) < 0.01


def test_adaptive_threshold_sits_between_baseline_and_spike() -> None:
    # Flat baseline at 1.0 with a single spike at 50.0; threshold should
    # separate the two.
    scores = [1.0] * 20 + [50.0] + [1.0] * 20
    t = _adaptive_threshold(scores)
    assert 1.0 < t < 50.0


def test_compute_scores_returns_n_minus_one(tmp_path: Path) -> None:
    sess = tmp_path / "scores"
    # 4 identical frames -> 3 scores, all zero
    for i in range(4):
        save_frame(sess, i, i * 100, _solid_img((100, 100, 100)))
    from claude_eyes.storage import list_frames

    frames = list_frames(sess)
    scores = _compute_scores(frames)

    assert len(scores) == 3
    assert all(s < 1.0 for s in scores)


def test_compute_scores_separates_motion_from_static(tmp_path: Path) -> None:
    sess = tmp_path / "mix"
    static_img = _solid_img((100, 100, 100))
    moving_img = _solid_img((200, 50, 50))
    # 3 static, then switch to moving for 1, then 3 static again
    save_frame(sess, 0, 0, static_img)
    save_frame(sess, 1, 100, static_img)
    save_frame(sess, 2, 200, static_img)
    save_frame(sess, 3, 300, moving_img)
    save_frame(sess, 4, 400, static_img)
    save_frame(sess, 5, 500, static_img)
    save_frame(sess, 6, 600, static_img)
    from claude_eyes.storage import list_frames

    frames = list_frames(sess)
    scores = _compute_scores(frames)

    assert len(scores) == 6
    # Scores at transitions (index 2 and 3) should be high; elsewhere near-zero
    assert scores[2] > 50   # static -> moving
    assert scores[3] > 50   # moving -> static
    assert scores[0] < 1.0
    assert scores[1] < 1.0
    assert scores[4] < 1.0
    assert scores[5] < 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_activity.py -v
```
Expected: `ImportError: cannot import name '_downscale_frame'` (and the other private helpers).

- [ ] **Step 3: Append implementation to `src/claude_eyes/activity.py`**

Add these imports to the existing import block (top of file, merge in):
```python
from pathlib import Path

from PIL import Image

from .storage import FrameInfo, list_frames
```

Then append the helpers at the bottom of the file:
```python
_THUMB_SIZE = (128, 72)            # (W, H) for PIL; 16:9; ~9216 pixels
_CHUNK_SIZE = 500                  # frames per batch (memory cap)


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
    """Threshold = ``percentile(scores, 25) + 3 × max(MAD, 0.5)``.

    The 0.5 floor on MAD prevents zero-threshold drift on scenes where
    every frame pair produces an identical score (threshold would otherwise
    be equal to the baseline, meaning every score would trigger "active").
    """
    arr = np.array(scores)
    baseline = float(np.percentile(arr, 25))
    mad = float(np.median(np.abs(arr - np.median(arr))))
    return baseline + 3 * max(mad, 0.5)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_activity.py -v
```
Expected: 13 passed (8 from Task 1 + 5 new).

- [ ] **Step 5: Commit**

```bash
git add src/claude_eyes/activity.py tests/test_activity.py
git commit -m "feat(activity): add downscale, compute_scores, adaptive threshold"
```

---

## Task 3: `detect_active_range` orchestrator

**Files:**
- Modify: `src/claude_eyes/activity.py` (append `detect_active_range`)
- Modify: `tests/test_activity.py` (append tests)

- [ ] **Step 1: Append failing tests**

```python
from claude_eyes.activity import detect_active_range


def test_detect_active_range_all_static_returns_none(tmp_path: Path) -> None:
    sess = tmp_path / "static"
    for i in range(5):
        save_frame(sess, i, i * 100, _solid_img((100, 100, 100)))
    active, score_mean = detect_active_range(sess)
    assert active is None
    assert score_mean == 0.0 or score_mean < 1.0


def test_detect_active_range_leading_trailing_idle_trimmed(tmp_path: Path) -> None:
    sess = tmp_path / "bracketed"
    static_img = _solid_img((100, 100, 100))
    moving_img = _solid_img((200, 50, 50))
    # 5 static, 3 moving, 5 static -> 13 frames, 12 scores
    for i in range(5):
        save_frame(sess, i, i * 100, static_img)
    for i in range(5, 8):
        save_frame(sess, i, i * 100, moving_img)
    for i in range(8, 13):
        save_frame(sess, i, i * 100, static_img)

    active, _ = detect_active_range(sess)

    assert active is not None
    first, last = active
    # Transitions are at scores[4] (5th score) and scores[7] (8th score).
    # first_score=4 -> first_frame=4; last_score=7 -> last_frame=8.
    assert first == 4
    assert last == 8


def test_detect_active_range_too_few_frames_returns_none(tmp_path: Path) -> None:
    sess = tmp_path / "single"
    save_frame(sess, 0, 0, _solid_img((100, 100, 100)))
    active, _ = detect_active_range(sess)
    assert active is None


def test_detect_active_range_missing_session_dir_returns_none(tmp_path: Path) -> None:
    active, score_mean = detect_active_range(tmp_path / "nope")
    assert active is None
    assert score_mean == 0.0


def test_detect_active_range_include_indices_filter(tmp_path: Path) -> None:
    """When given include_frame_indices, only those frames contribute."""
    sess = tmp_path / "filtered"
    static_img = _solid_img((100, 100, 100))
    moving_img = _solid_img((200, 50, 50))
    # Motion at indices 5-7; filter limits to indices 3-6.
    for i in range(5):
        save_frame(sess, i, i * 100, static_img)
    for i in range(5, 8):
        save_frame(sess, i, i * 100, moving_img)
    for i in range(8, 10):
        save_frame(sess, i, i * 100, static_img)

    active, _ = detect_active_range(sess, include_frame_indices={3, 4, 5, 6})

    assert active is not None
    first, last = active
    # Filtered frames are 3, 4, 5, 6 (4 frames, 3 scores).
    # Transitions: scores[0] (3-4) = static->static = 0
    #              scores[1] (4-5) = static->moving = HIGH
    #              scores[2] (5-6) = moving->moving = 0
    # Only scores[1] is above threshold -> first_score=1, last_score=1
    # first_frame=1 (index in filtered list), last_frame=2.
    # Returned indices are positions in the filtered list, not absolute.
    assert first == 1
    assert last == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_activity.py -v
```
Expected: `ImportError: cannot import name 'detect_active_range'`.

- [ ] **Step 3: Append `detect_active_range` to `src/claude_eyes/activity.py`**

```python
def detect_active_range(
    session_dir: Path,
    *,
    include_frame_indices: set[int] | None = None,
) -> tuple[tuple[int, int] | None, float]:
    """Identify the leading-and-trailing-trimmed index range of motion.

    Returns ``(range_or_None, score_mean)`` — the range is an inclusive
    ``(first_frame_idx, last_frame_idx)`` pair computed from the motion
    scores, widened by one on the right so both frames of the last active
    transition are included. ``score_mean`` is the mean of all scores,
    useful as a diagnostic field in the response even when no range was
    detected.

    If fewer than two frames are available (either because the session is
    empty, has a single frame, or the ``include_frame_indices`` filter is
    too restrictive), returns ``(None, 0.0)``.

    The returned indices are **positions within the filtered frame list**
    — when ``include_frame_indices`` is used, indices refer to the
    filtered subset in ascending order, not to the original frame indices
    on disk. Callers are expected to map back if needed.
    """
    frames = list_frames(session_dir)
    if include_frame_indices is not None:
        frames = [f for f in frames if f["index"] in include_frame_indices]
    if len(frames) < 2:
        return None, 0.0

    scores = _compute_scores(frames)
    if not scores:
        return None, 0.0

    score_mean = float(np.mean(scores))
    threshold = _adaptive_threshold(scores)
    arr = np.array(scores)
    active = arr > threshold
    if not active.any():
        return None, score_mean

    first = int(np.argmax(active))
    last = len(active) - 1 - int(np.argmax(active[::-1]))
    # scores[i] sits between frames[i] and frames[i+1]; widen by +1 on
    # the right so both endpoint frames are covered.
    return (first, min(last + 1, len(frames) - 1)), score_mean
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_activity.py -v
```
Expected: 18 passed (13 prior + 5 new).

- [ ] **Step 5: Run full suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```
Expected: 103 passed (85 prior + 18 new).

- [ ] **Step 6: Commit**

```bash
git add src/claude_eyes/activity.py tests/test_activity.py
git commit -m "feat(activity): add detect_active_range orchestrator"
```

---

## Task 4: `stop_recording` attaches new fields

**Files:**
- Modify: `src/claude_eyes/server.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Append failing test**

```python
def test_stop_recording_attaches_fps_effective_and_active_range(
    patched_server, tmp_path: Path
) -> None:
    start = patched_server.start_recording(fps=10, resolution_scale=1.0, region=None)
    sid = start["session_id"]
    time.sleep(1.2)
    result = patched_server.stop_recording(sid)

    assert "fps_effective" in result
    assert "active_range" in result
    assert "activity_score_mean" in result
    assert isinstance(result["fps_effective"], float)
    assert result["fps_effective"] > 0
    # active_range is either [int, int] or None
    assert result["active_range"] is None or (
        isinstance(result["active_range"], list)
        and len(result["active_range"]) == 2
    )
    assert isinstance(result["activity_score_mean"], float)

    patched_server.cleanup_session(sid)
```

- [ ] **Step 2: Run the test to confirm RED**

```bash
.venv/Scripts/python.exe -m pytest tests/test_server.py::test_stop_recording_attaches_fps_effective_and_active_range -v
```
Expected: `AssertionError: 'fps_effective' in {...}` (or similar — the field is missing).

- [ ] **Step 3: Modify `stop_recording` in `src/claude_eyes/server.py`**

Add this import alongside the existing `from .compose import compose_bucketed_preview` (merge in, respect ruff ordering):
```python
from .activity import compute_fps_effective, detect_active_range
```

Replace the return block of `stop_recording` with the version below. Everything up to the existing `frames = list_frames_on_disk(...)` line stays as-is.

```python
    frames = list_frames_on_disk(Path(session.frames_dir))

    try:
        bucket_items = compose_bucketed_preview(
            Path(session.frames_dir), bucket_s=1.0, mode="avg"
        )
    except Exception as exc:
        print(f"[claude-eyes] preview composition failed: {exc}", file=sys.stderr)
        bucket_items = []

    try:
        active_range, score_mean = detect_active_range(Path(session.frames_dir))
    except Exception as exc:
        print(f"[claude-eyes] activity detection failed: {exc}", file=sys.stderr)
        active_range, score_mean = None, 0.0

    fps_effective = compute_fps_effective(frames_count, duration_s)

    return {
        "session_id": session_id,
        "frames_count": frames_count,
        "duration_s": duration_s,
        "frames_dir": session.frames_dir,
        "frame_paths": [f["path"] for f in frames],
        "previews": {
            "mode": "avg",
            "bucket_s": 1.0,
            "items": [
                {
                    "bucket_index": b.bucket_index,
                    "preview_path": b.preview_path,
                    "frame_range": list(b.frame_range),
                    "ts_start_ms": b.ts_start_ms,
                    "ts_end_ms": b.ts_end_ms,
                }
                for b in bucket_items
            ],
        },
        "fps_effective": fps_effective,
        "active_range": list(active_range) if active_range is not None else None,
        "activity_score_mean": round(score_mean, 3),
    }
```

- [ ] **Step 4: Run the test to confirm GREEN**

```bash
.venv/Scripts/python.exe -m pytest tests/test_server.py -v
```
Expected: all server tests still pass + the new test.

- [ ] **Step 5: Run full suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```
Expected: 104 passed.

- [ ] **Step 6: Commit**

```bash
git add src/claude_eyes/server.py tests/test_server.py
git commit -m "feat(server): stop_recording reports fps_effective and active_range"
```

---

## Task 5: `trim_session` MCP tool

**Files:**
- Modify: `src/claude_eyes/server.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Append five failing tests**

```python
def test_trim_session_removes_dead_frames_and_regenerates_previews(
    patched_server, tmp_path: Path
) -> None:
    # Record at a moderate pace. The fake MSS produces identical frames,
    # so active_range will typically be None — to force a trim-able
    # scenario, we manually swap a couple of frames on disk after stop.
    start = patched_server.start_recording(fps=20, resolution_scale=1.0, region=None)
    sid = start["session_id"]
    time.sleep(0.6)  # ~12 frames
    patched_server.stop_recording(sid)

    # Inject "motion" by overwriting the 5th frame with a very different image
    from PIL import Image as _I

    sess_dir = Path(patched_server._registry.get(sid).frames_dir)
    frames_on_disk = sorted(sess_dir.glob("frame_*.jpg"))
    assert len(frames_on_disk) >= 6
    red = _I.new("RGB", (8, 8), (255, 0, 0))
    red.save(frames_on_disk[5], "JPEG", quality=85)
    red.save(frames_on_disk[6], "JPEG", quality=85)

    result = patched_server.trim_session(sid)

    assert "kept_frames" in result
    assert "deleted_frames" in result
    assert "freed_bytes" in result
    assert "previews" in result
    assert result["kept_frames"] >= 2
    # The mangled frames 5-6 should be kept (active), the extremes trimmed
    assert result["deleted_frames"] > 0
    # Previews directory should exist post-trim
    assert (sess_dir / "previews").is_dir()

    patched_server.cleanup_session(sid)


def test_trim_session_rejects_active_session(patched_server) -> None:
    start = patched_server.start_recording(fps=10, resolution_scale=1.0, region=None)
    sid = start["session_id"]
    # Do NOT stop; call trim on the still-active session.
    result = patched_server.trim_session(sid)
    assert "error" in result
    assert "still recording" in result["error"]

    # Clean up: stop and remove
    patched_server.stop_recording(sid)
    patched_server.cleanup_session(sid)


def test_trim_session_rejects_continuous_session_id(patched_server) -> None:
    result = patched_server.trim_session("_continuous")
    assert "error" in result
    assert "continuous buffer" in result["error"]


def test_trim_session_unknown_session_returns_error(patched_server) -> None:
    result = patched_server.trim_session("sess_ghost")
    assert "error" in result
    assert "unknown session" in result["error"]


def test_trim_session_all_static_returns_no_range_error(
    patched_server, tmp_path: Path
) -> None:
    # Fake MSS always returns the same image -> no motion detected.
    start = patched_server.start_recording(fps=10, resolution_scale=1.0, region=None)
    sid = start["session_id"]
    time.sleep(0.3)
    patched_server.stop_recording(sid)

    result = patched_server.trim_session(sid)
    assert "error" in result
    assert "no active range" in result["error"]

    patched_server.cleanup_session(sid)
```

- [ ] **Step 2: Run tests to confirm RED**

```bash
.venv/Scripts/python.exe -m pytest tests/test_server.py -v
```
Expected: `AttributeError: ... 'trim_session'`.

- [ ] **Step 3: Add `trim_session` to `src/claude_eyes/server.py`**

Add `import shutil` to the existing stdlib import block (merge in, respect ruff ordering).

Insert the new tool after the existing `compose_timeline_preview` tool and before `start_continuous_buffer`. Keep the decorator order.

```python
@mcp.tool()
def trim_session(session_id: str) -> dict[str, Any]:
    """Apply the active-range trim: delete frames outside the detected motion
    window and regenerate previews. Opt-in and destructive.

    Rejects the continuous-buffer directory name and any session still
    recording. Returns a structured error if no active range is detected
    (nothing to trim) or the session is unknown.
    """
    if session_id == CONTINUOUS_SESSION_DIR_NAME:
        return {"error": "trim not supported on continuous buffer"}
    if session_id in _active:
        return {"error": "session is still recording"}
    session = _registry.get(session_id)
    if session is None:
        return {"error": f"unknown session {session_id}"}

    session_dir = Path(session.frames_dir)
    active_range, _ = detect_active_range(session_dir)
    if active_range is None:
        return {"error": "no active range detected; nothing to trim"}

    first, last = active_range
    frames = list_frames_on_disk(session_dir)
    if not frames:
        return {"error": "session has no frames"}

    to_delete = [f for f in frames if not (first <= f["index"] <= last)]
    freed = 0
    for f in to_delete:
        p = Path(f["path"])
        try:
            freed += p.stat().st_size
            p.unlink()
        except OSError:
            continue

    previews_dir = session_dir / "previews"
    if previews_dir.is_dir():
        shutil.rmtree(previews_dir, ignore_errors=True)

    try:
        new_previews = compose_bucketed_preview(session_dir, bucket_s=1.0, mode="avg")
    except Exception as exc:
        print(f"[claude-eyes] preview re-composition failed: {exc}", file=sys.stderr)
        new_previews = []

    return {
        "session_id": session_id,
        "kept_frames": len(frames) - len(to_delete),
        "deleted_frames": len(to_delete),
        "freed_bytes": freed,
        "previews": {
            "mode": "avg",
            "bucket_s": 1.0,
            "items": [
                {
                    "bucket_index": b.bucket_index,
                    "preview_path": b.preview_path,
                    "frame_range": list(b.frame_range),
                    "ts_start_ms": b.ts_start_ms,
                    "ts_end_ms": b.ts_end_ms,
                }
                for b in new_previews
            ],
        },
    }
```

- [ ] **Step 4: Run tests to confirm GREEN**

```bash
.venv/Scripts/python.exe -m pytest tests/test_server.py -v
```
Expected: all server tests pass.

- [ ] **Step 5: Full suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```
Expected: 109 passed.

- [ ] **Step 6: Commit**

```bash
git add src/claude_eyes/server.py tests/test_server.py
git commit -m "feat(server): add trim_session MCP tool"
```

---

## Task 6: `query_buffer` attaches new fields

**Files:**
- Modify: `src/claude_eyes/server.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Append failing test**

```python
def test_query_buffer_includes_fps_effective_and_active_range(patched_server) -> None:
    patched_server.start_continuous_buffer(fps=10)
    time.sleep(1.2)
    result = patched_server.query_buffer(time_range_s=5, max_frames=5)

    assert "fps_effective" in result
    assert "active_range" in result
    assert "activity_score_mean" in result
    # fps_effective is > 0 once the buffer has at least 2 frames in range
    assert isinstance(result["fps_effective"], float)
    # active_range may be None (fake MSS produces identical frames) or [int, int]
    assert result["active_range"] is None or (
        isinstance(result["active_range"], list)
        and len(result["active_range"]) == 2
    )

    patched_server.stop_continuous_buffer()
```

- [ ] **Step 2: Run the test to confirm RED**

```bash
.venv/Scripts/python.exe -m pytest tests/test_server.py::test_query_buffer_includes_fps_effective_and_active_range -v
```
Expected: `AssertionError: 'fps_effective' in {...}`.

- [ ] **Step 3: Modify `query_buffer` in `src/claude_eyes/server.py`**

Locate the existing `query_buffer` function body. After the `bucket_items = compose_bucketed_preview(...)` / `filtered_items = [...]` block and BEFORE the `result: dict[str, Any] = { ... }` assignment, insert the activity computation. Then include the three new fields in the result dict.

Final form of the function body (replace the whole body, keep `@mcp.tool()` decorator and signature):
```python
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

        try:
            bucket_items = compose_bucketed_preview(
                handle.session_dir, bucket_s=1.0, mode="avg"
            )
        except Exception as exc:
            print(f"[claude-eyes] preview composition failed: {exc}", file=sys.stderr)
            bucket_items = []

        filtered_items = [
            b for b in bucket_items
            if b.ts_end_ms >= oldest and b.ts_start_ms <= now_ms
        ]

        try:
            indices = {f["index"] for f in all_frames}
            active_range, score_mean = detect_active_range(
                handle.session_dir, include_frame_indices=indices
            )
        except Exception as exc:
            print(f"[claude-eyes] activity detection failed: {exc}", file=sys.stderr)
            active_range, score_mean = None, 0.0

        # For query_buffer we report fps_effective of the sampled slice,
        # not of the full buffer: frames-in-range over the requested
        # time_range_s (post-clamp).
        effective_range_s = max(0.001, (now_ms - oldest) / 1000)
        fps_effective = compute_fps_effective(len(all_frames), effective_range_s)

        result: dict[str, Any] = {
            "frames": enriched,
            "total_in_range": len(all_frames),
            "oldest_frame_age_s": enriched[0]["age_s"] if enriched else 0.0,
            "newest_frame_age_s": enriched[-1]["age_s"] if enriched else 0.0,
            "previews": {
                "mode": "avg",
                "bucket_s": 1.0,
                "items": [
                    {
                        "bucket_index": b.bucket_index,
                        "preview_path": b.preview_path,
                        "frame_range": list(b.frame_range),
                        "ts_start_ms": b.ts_start_ms,
                        "ts_end_ms": b.ts_end_ms,
                    }
                    for b in filtered_items
                ],
            },
            "fps_effective": fps_effective,
            "active_range": list(active_range) if active_range is not None else None,
            "activity_score_mean": round(score_mean, 3),
        }
        if clamped:
            effective_s = max(0, (now_ms - buffer_oldest) // 1000)
            result["warning"] = (
                f"time_range_s exceeded buffer age; clamped to {effective_s}s"
            )
        return result
```

- [ ] **Step 4: Run the test to confirm GREEN**

```bash
.venv/Scripts/python.exe -m pytest tests/test_server.py -v
```
Expected: all server tests pass.

- [ ] **Step 5: Full suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```
Expected: 110 passed.

- [ ] **Step 6: Commit**

```bash
git add src/claude_eyes/server.py tests/test_server.py
git commit -m "feat(server): query_buffer reports fps_effective and active_range"
```

---

## Task 7: Skill updates (three files)

**Files:**
- Modify: `.claude/skills/analyze-screen/SKILL.md`
- Modify: `.claude/skills/analyze-page-animation/SKILL.md`
- Modify: `.claude/skills/review-recent-activity/SKILL.md`

- [ ] **Step 1: Update `analyze-screen/SKILL.md`**

Find the existing `## Scan-then-drill when frames exceed 30` section (from Spec 4). Immediately AFTER that section and BEFORE `## Example dispatch`, insert:

```markdown
## Active range (Spec 5)

`stop_recording` attaches `active_range: [first_idx, last_idx] | null`, `fps_effective: float`, and `activity_score_mean: float`. Use them to reduce token spend further and catch I/O bottlenecks.

**Before scan-then-drill:**

1. If `active_range` is not null, filter `frame_paths` to indices in `[first_idx, last_idx]` before scanning. A 400-frame recording with a 30-frame active range drops the scan input by ~90%.
2. If `active_range` is null, the algorithm found no activity above its adaptive threshold — fall back to the full `frame_paths` as before.

**Check `fps_effective`:**

- If `fps_effective < 0.8 × fps_nominal` (the value you passed to `start_recording`), warn the user: the capture is disk-I/O-bound. Suggest a lower `resolution_scale` or tighter `region` for the next recording.

**Optional: `trim_session`.**

After the analysis, if you want to free disk too (not just ignore dead frames in the subagent pass), call `mcp__claude_eyes__trim_session(session_id)`. This deletes everything outside `active_range` and regenerates previews. Never called automatically — ask yourself whether the dead frames might still be useful before trimming.
```

- [ ] **Step 2: Update `analyze-page-animation/SKILL.md`**

Find the existing `## Scan-then-drill when frames exceed 30` section. Immediately AFTER it and BEFORE `## Common mistakes to avoid`, insert the **same** Active range block. Slight variant for the Chrome context:

```markdown
## Active range (Spec 5)

`stop_recording` attaches `active_range: [first_idx, last_idx] | null`, `fps_effective: float`, and `activity_score_mean: float`.

**Usage in this skill:**

1. Chrome animations are often very tight (1-2 s) and bracketed by long idle padding (Claude-in-Chrome JS roundtrip + transitionend wait). `active_range` typically identifies the ~30 frames around the animation out of ~400. Filter `frame_paths` to that range before scanning.
2. If `active_range` is null, the animation didn't produce enough per-pixel delta to exceed the adaptive threshold (very subtle colour shifts on a light background, for example). Fall back to `frame_paths` and consider `compose_timeline_preview(session_id, mode="max")` to amplify trails.
3. `fps_effective < 0.8 × fps_nominal` in this skill almost always means the `region` was too wide (browser viewport instead of a tight element bbox). Recompute Step 0 with a tighter bbox and retry.

**Optional: `trim_session`.** Useful when running many animation captures in a row — frees disk without losing the analysis value.
```

- [ ] **Step 3: Update `review-recent-activity/SKILL.md`**

After the existing `4. **Scan then drill**` step and before step 5, insert a new sub-step `4.5`:

```markdown
4.5. **Respect `active_range`.** `query_buffer` attaches `active_range`, `fps_effective`, and `activity_score_mean` just like `stop_recording`.

   - If `active_range` is not null, only scan previews whose `frame_range` intersects `active_range`. For a "what did I do" question, this narrows the scan to the seconds when something actually changed on screen.
   - If `active_range` is null, the continuous buffer captured a static or near-static interval; tell the user "nothing notable happened in the last N seconds" rather than inventing activity.
   - `fps_effective < 0.8 × fps_nominal` is less critical here (continuous buffer runs at low fps by default) but still worth flagging to the user.
```

- [ ] **Step 4: Verify line counts**

```bash
wc -l .claude/skills/analyze-screen/SKILL.md .claude/skills/analyze-page-animation/SKILL.md .claude/skills/review-recent-activity/SKILL.md
```
Expected: all three files under 500 lines.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/
git commit -m "docs(skills): add Active range section using Spec 5 fields"
```

---

## Task 8: `CLAUDE.md` — active range + fps_effective in scan-then-drill

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Extend the existing Scan-then-drill section**

Find the existing `## Scan-then-drill workflow` section. Replace its bulleted list of steps with the version below (adds a new "step 0" at the start and keeps the existing two):

```markdown
## Scan-then-drill workflow

`stop_recording` and `query_buffer` auto-attach bucket previews to their responses (one composited image per `bucket_s=1.0` second of recording, `mode="avg"` by default) AND the active-range metadata from Spec 5. Use them to reduce token spend on the frame-analyzer subagent.

Rule of thumb: if a response has `frames_count < 30`, pass raw `frame_paths` directly (previews add no value). Otherwise:

0. **Respect `active_range`.** If the response contains `active_range: [first, last]`, filter `frame_paths` to indices in that range before anything else — dead frames outside the range shouldn't reach the subagent. If `fps_effective < 0.8 × fps_nominal`, warn the user: the capture is disk-I/O-bound.
1. **Scan.** Send only `previews.items[*].preview_path` (or the subset whose `frame_range` intersects `active_range`) to the subagent with the prompt "identify the bucket indices relevant to the question". Get back a short list.
2. **Drill.** Filter `frame_paths` to the chosen buckets' `frame_range` (further narrowed by `active_range` if present) and dispatch the subagent again with the raw frames and the original question.

If the default `avg` preview doesn't surface the behaviour, call `compose_timeline_preview(session_id, bucket_s=0.5, mode="max")` or `mode="motion"` and re-scan. Optional follow-up: call `trim_session(session_id)` to free disk after the analysis (deletes frames outside `active_range`). Skills (`analyze-screen`, `analyze-page-animation`, `review-recent-activity`) all follow this pattern — reach for them first, they encode the flow.
```

- [ ] **Step 2: Verify length**

```bash
wc -l CLAUDE.md
```
Expected: still under 200 lines.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): update scan-then-drill with active_range and trim_session"
```

---

## Task 9: Full suite + lint + type check + smoke

**Files:**
- Possibly modify: any file flagged by ruff / mypy.

- [ ] **Step 1: Full suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```
Expected: **110 passed** (85 prior + 25 new across Tasks 1-6). No failures.

- [ ] **Step 2: mypy**

```bash
.venv/Scripts/python.exe -m mypy src/claude_eyes
```
Expected: `Success: no issues found in 9 source files` (8 prior + `activity.py`).

Common candidates if issues appear: numpy strict-mode `no-any-return` on some helpers. Wrap with `cast(np.ndarray, ...)` as done in `compose.py`.

- [ ] **Step 3: ruff**

```bash
.venv/Scripts/python.exe -m ruff check src tests
```
Expected: `All checks passed!`.

Common candidates: long test lines around frame-path assertions. Wrap to ≤ 100 chars.

- [ ] **Step 4: Real-screen smoke — re-run the Start-menu scenario**

Manual step. Restart Claude Code so the updated server + skills load. Ask Claude to analyze the Windows Start-menu animation (fps=25, full-screen). Expect:

1. `stop_recording` response includes `fps_effective` (probably ~17-20 on this machine, flagged as I/O-bound).
2. `active_range` brackets the ~30 frames around the menu open+close (out of ~300+ total).
3. Scan+drill reads only frames in `active_range`, then narrows further to the scan-identified bucket. Token count to the subagent drops visibly.
4. Optionally, calling `trim_session(session_id)` after analysis frees ≥ 80% of the disk used by the session.

- [ ] **Step 5: Commit any lint/type fixes from Steps 2-3**

If Steps 2-3 required edits:

```bash
git add -u
git commit -m "chore: satisfy mypy/ruff after capture-intelligence changes"
```

If nothing was changed, this step is a no-op.

---

## Self-Review

**1. Spec coverage.**

| Spec requirement | Task(s) |
|---|---|
| `score_frame_motion` helper | 1 |
| `compute_fps_effective` helper | 1 |
| `_downscale_frame` helper (128×72, PIL bilinear) | 2 |
| `_compute_scores` chunked by 500 | 2 |
| `_adaptive_threshold` (percentile 25 + 3×MAD, floor 0.5) | 2 |
| `detect_active_range` with optional `include_frame_indices` | 3 |
| `stop_recording` new fields (`fps_effective`, `active_range`, `activity_score_mean`) | 4 |
| `query_buffer` same three new fields | 6 |
| `trim_session` MCP tool with all four error paths | 5 |
| Best-effort semantics: activity.py exception → fields still present | 4, 5, 6 (try/except) |
| Skill updates (3 files) | 7 |
| `CLAUDE.md` scan-then-drill update | 8 |
| Full suite + mypy + ruff + smoke | 9 |
| Default behaviour: never auto-trim | covered by design (only `trim_session` deletes) |
| Back-compat: callers ignoring new fields still work | covered by response being additive |

No gaps.

**2. Placeholder scan.** No "TBD", "TODO", "similar to…", or undefined symbols. Every code step shows complete code; every test step has exact assertions; every command shows expected output.

**3. Type consistency.**

- `detect_active_range(session_dir, *, include_frame_indices=None) -> tuple[tuple[int, int] | None, float]` — same signature used in Tasks 3, 4, 5, 6.
- `active_range` returned as `tuple[int, int]` from `activity.py` but serialised to `list[int]` of length 2 in tool responses (JSON-friendly). Consistent across Tasks 4, 5, 6.
- `compute_fps_effective(frames_count, duration_s) -> float` — same signature in Tasks 1, 4, 6.
- `score_frame_motion(prev, curr) -> float` — same in Tasks 1, 2, 3.
- Preview item dict shape (`bucket_index`, `preview_path`, `frame_range`, `ts_start_ms`, `ts_end_ms`) — identical across Tasks 4, 5, 6 (matches Spec 4).
- `trim_session` error strings — consistent with Task 5 tests: `"trim not supported on continuous buffer"`, `"session is still recording"`, `"unknown session <id>"`, `"no active range detected; nothing to trim"`, `"session has no frames"`.
- `_FakeMSS` instance tracking from Spec 3 reused unchanged — `trim_session` test doesn't need it but the recorder path still does.

No drift. Plan is ready to execute.

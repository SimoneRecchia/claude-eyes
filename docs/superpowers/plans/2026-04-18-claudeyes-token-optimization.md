# claudeEyes Token Optimization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Python-side bucket preview compositing (Spec 4a) and wire it into the three existing skills (Spec 4c), so the frame-analyzer subagent scans a coarse timeline before drilling into raw frames.

**Architecture:** A new `compose.py` module bundles frames into `bucket_s`-second windows and emits one composite JPEG per bucket in three modes (`avg`/`max`/`motion`) using `numpy`. `stop_recording` auto-composes `mode="avg", bucket_s=1.0` and attaches the metadata to its response. `query_buffer` does the same, filtered to the queried time range. A new `compose_timeline_preview` MCP tool recomposes on-demand with different parameters. The three skills (`analyze-screen`, `analyze-page-animation`, `review-recent-activity`) gain a "scan-then-drill" workflow. `CLAUDE.md` adds a hard `fps <= 60` rule and concrete fps-per-task examples.

**Tech Stack:** Python 3.13, `numpy>=1.26`, `Pillow>=10.0`, existing `mcp`, `mss`, `pytest`.

**Prerequisite:** Spec 1+2+3 shipped on `main` (PR #2). Spec 4 design at `docs/superpowers/specs/2026-04-18-claudeyes-token-optimization-design.md`. New branch `feat/token-optimization` already created with the spec commit.

---

## File structure

```
src/claude_eyes/
├── compose.py        # Task 2-3 — NEW: blend helpers + compose_bucketed_preview
└── server.py         # Task 4-6 — stop_recording/query_buffer/compose_timeline_preview

pyproject.toml         # Task 1 — declare numpy>=1.26 explicitly

tests/
├── test_compose.py   # Task 2-3 — NEW: blend math + compose orchestration
├── test_storage.py   # Task 7 — extend: cleanup removes previews
└── test_server.py    # Task 4, 5, 6 — extend: stop_recording/query_buffer/compose tool

.claude/skills/
├── analyze-screen/SKILL.md             # Task 8 — scan-then-drill section
├── analyze-page-animation/SKILL.md     # Task 8 — scan-then-drill section
└── review-recent-activity/SKILL.md     # Task 8 — scan-then-drill section

CLAUDE.md              # Task 9 — fps<=60 hard rule + fps table + scan-then-drill
```

---

## Task 1: Declare `numpy` as an explicit dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add `numpy>=1.26` to `[project].dependencies`**

Open `pyproject.toml`. The current `dependencies` array is:
```toml
dependencies = [
  "mcp>=1.0",
  "mss>=9.0",
  "Pillow>=10.0",
]
```

Replace it with:
```toml
dependencies = [
  "mcp>=1.0",
  "mss>=9.0",
  "Pillow>=10.0",
  "numpy>=1.26",
]
```

- [ ] **Step 2: Reinstall the project so the new dep is pulled in**

```bash
.venv/Scripts/python.exe -m pip install -e ".[dev]"
```
Expected: installation succeeds. `numpy` should already be present via Pillow; pip prints it as already satisfied or upgrades to >=1.26.

- [ ] **Step 3: Verify the import works**

```bash
.venv/Scripts/python.exe -c "import numpy; print(numpy.__version__)"
```
Expected: prints a version string `>= 1.26`.

- [ ] **Step 4: Run the full suite to confirm no regression**

```bash
.venv/Scripts/python.exe -m pytest -q
```
Expected: 68 passed.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "build(deps): declare numpy>=1.26 as direct dependency"
```

---

## Task 2: Blend helper functions in `compose.py`

**Files:**
- Create: `src/claude_eyes/compose.py` (skeleton + three helpers only)
- Create: `tests/test_compose.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_compose.py`:
```python
"""Tests for claude_eyes.compose — blend helpers and orchestrator."""
from __future__ import annotations

import numpy as np

from claude_eyes.compose import _blend_avg, _blend_max, _blend_motion


def test_blend_avg_two_solid_colors() -> None:
    arr = np.array(
        [
            [[[255, 0, 0]]],   # red
            [[[0, 0, 255]]],   # blue
        ],
        dtype=np.uint8,
    )
    result = _blend_avg(arr)
    # Average of red (255,0,0) and blue (0,0,255) -> ~(127,0,127)
    assert result.shape == (1, 1, 3)
    assert result[0, 0, 0] == 127
    assert result[0, 0, 1] == 0
    assert result[0, 0, 2] == 127


def test_blend_max_lighten() -> None:
    arr = np.array(
        [
            [[[255, 0, 0]]],   # red
            [[[0, 255, 0]]],   # green
        ],
        dtype=np.uint8,
    )
    result = _blend_max(arr)
    # Max per-channel -> yellow (255,255,0)
    assert list(result[0, 0]) == [255, 255, 0]


def test_blend_motion_static_is_zero() -> None:
    arr = np.array(
        [
            [[[100, 100, 100]]],
            [[[100, 100, 100]]],
        ],
        dtype=np.uint8,
    )
    result = _blend_motion(arr)
    assert (result == 0).all()


def test_blend_motion_highlights_change() -> None:
    # Frame 0 black, frame 1 has a diff of (100, 50, 25) -> max=100 normalised to 255
    arr = np.array(
        [
            [[[0, 0, 0]]],
            [[[100, 50, 25]]],
        ],
        dtype=np.uint8,
    )
    result = _blend_motion(arr)
    # Max diff = 100, normalised to 255.
    assert result[0, 0, 0] == 255
    # 50 scaled by 255/100 = 127.5 -> 127 or 128 (rounding)
    assert abs(int(result[0, 0, 1]) - 127) <= 1
    # 25 scaled by 255/100 = 63.75 -> 63 or 64
    assert abs(int(result[0, 0, 2]) - 63) <= 1


def test_blend_motion_single_frame_falls_back_to_avg() -> None:
    arr = np.array([[[[50, 60, 70]]]], dtype=np.uint8)
    result = _blend_motion(arr)
    assert list(result[0, 0]) == [50, 60, 70]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_compose.py -v
```
Expected: `ModuleNotFoundError: No module named 'claude_eyes.compose'`.

- [ ] **Step 3: Create `src/claude_eyes/compose.py` with only the three helpers**

```python
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

from typing import Literal

import numpy as np

BlendMode = Literal["avg", "max", "motion"]


def _blend_avg(arr: np.ndarray) -> np.ndarray:
    """Pixel-wise mean across frames.

    arr shape: (N, H, W, 3) uint8. Returns (H, W, 3) uint8.
    """
    return arr.mean(axis=0).astype(np.uint8)


def _blend_max(arr: np.ndarray) -> np.ndarray:
    """Pixel-wise max across frames (lighten blend).

    arr shape: (N, H, W, 3) uint8. Returns (H, W, 3) uint8.
    """
    return arr.max(axis=0)


def _blend_motion(arr: np.ndarray) -> np.ndarray:
    """Sum of absolute diffs between consecutive frames, normalised to 0-255.

    If fewer than 2 frames are present, falls back to :func:`_blend_avg`
    (motion is undefined on a single frame).
    """
    if arr.shape[0] < 2:
        return _blend_avg(arr)
    diffs = np.abs(np.diff(arr.astype(np.int16), axis=0))   # (N-1, H, W, 3)
    summed = diffs.sum(axis=0)                              # (H, W, 3)
    max_val = int(summed.max())
    if max_val == 0:
        return np.zeros_like(summed, dtype=np.uint8)
    normalised = summed.astype(np.float32) * (255.0 / max_val)
    return normalised.astype(np.uint8)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_compose.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/claude_eyes/compose.py tests/test_compose.py
git commit -m "feat(compose): add avg/max/motion blend helpers with numpy"
```

---

## Task 3: `compose_bucketed_preview` orchestrator

**Files:**
- Modify: `src/claude_eyes/compose.py`
- Modify: `tests/test_compose.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_compose.py`:
```python
from pathlib import Path

from PIL import Image as _I

from claude_eyes.compose import BucketInfo, compose_bucketed_preview
from claude_eyes.storage import save_frame


def _img(color: tuple[int, int, int] = (100, 100, 100)) -> _I.Image:
    return _I.new("RGB", (8, 8), color)


def test_compose_empty_session_returns_empty_list(tmp_path: Path) -> None:
    sess = tmp_path / "empty"
    sess.mkdir()
    assert compose_bucketed_preview(sess, bucket_s=1.0, mode="avg") == []


def test_compose_bucket_boundaries_respect_timestamps(tmp_path: Path) -> None:
    sess = tmp_path / "buckets"
    # 3 frames in bucket 0 (ts 0-999ms), 2 in bucket 1 (ts 1000-1999ms)
    save_frame(sess, 0, 100, _img((255, 0, 0)))
    save_frame(sess, 1, 500, _img((255, 0, 0)))
    save_frame(sess, 2, 900, _img((255, 0, 0)))
    save_frame(sess, 3, 1200, _img((0, 0, 255)))
    save_frame(sess, 4, 1800, _img((0, 0, 255)))

    items = compose_bucketed_preview(sess, bucket_s=1.0, mode="avg")

    assert len(items) == 2
    assert items[0].bucket_index == 0
    assert items[0].frame_range == (0, 2)
    assert items[0].ts_start_ms == 0
    assert items[0].ts_end_ms == 999
    assert items[1].bucket_index == 1
    assert items[1].frame_range == (3, 4)
    assert items[1].ts_start_ms == 1000
    assert items[1].ts_end_ms == 1999
    # Files exist on disk
    for it in items:
        assert Path(it.preview_path).exists()


def test_compose_writes_files_under_previews_dir(tmp_path: Path) -> None:
    sess = tmp_path / "dir_check"
    save_frame(sess, 0, 100, _img())
    items = compose_bucketed_preview(sess, bucket_s=1.0, mode="avg")
    assert len(items) == 1
    assert (sess / "previews").is_dir()
    assert Path(items[0].preview_path).parent == sess / "previews"
    assert Path(items[0].preview_path).name.startswith("preview_avg_000_")


def test_compose_bucket_s_clamped_to_minimum(tmp_path: Path) -> None:
    sess = tmp_path / "clamp"
    save_frame(sess, 0, 0, _img())
    save_frame(sess, 1, 50, _img())
    items = compose_bucketed_preview(sess, bucket_s=0.05, mode="avg")
    # bucket_s clamped to 0.1 (100 ms); ts 0 -> bucket 0, ts 50 -> bucket 0
    assert len(items) == 1
    assert items[0].frame_range == (0, 1)


def test_compose_unknown_mode_defaults_to_avg(tmp_path: Path) -> None:
    sess = tmp_path / "bad_mode"
    save_frame(sess, 0, 100, _img())
    items = compose_bucketed_preview(sess, bucket_s=1.0, mode="unknown")  # type: ignore[arg-type]
    assert len(items) == 1
    assert "preview_avg_" in items[0].preview_path


def test_compose_returns_bucket_info_dataclass(tmp_path: Path) -> None:
    sess = tmp_path / "dataclass_check"
    save_frame(sess, 0, 100, _img())
    items = compose_bucketed_preview(sess, bucket_s=1.0, mode="avg")
    assert all(isinstance(it, BucketInfo) for it in items)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_compose.py -v
```
Expected: `ImportError: cannot import name 'BucketInfo'` (or `compose_bucketed_preview`).

- [ ] **Step 3: Append `BucketInfo` + `compose_bucketed_preview` to `src/claude_eyes/compose.py`**

Add these imports at the top (merge with the existing `import` block, preserve ruff ordering):
```python
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .config import JPEG_QUALITY
from .storage import list_frames
```

Add the dataclass and the orchestrator at the end of the file:
```python
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

    # Group frames by bucket index (ts // bucket_ms).
    buckets: dict[int, list[dict]] = {}
    for f in frames:
        bidx = f["timestamp_ms"] // bucket_ms
        buckets.setdefault(bidx, []).append(f)

    result: list[BucketInfo] = []
    for bidx in sorted(buckets):
        bucket_frames = buckets[bidx]
        if not bucket_frames:
            continue

        # Load and stack into (N, H, W, 3). Resize mismatched frames to
        # the first frame's size (currently impossible but future-proof).
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_compose.py -v
```
Expected: all compose tests green (5 blend + 6 orchestrator = 11).

- [ ] **Step 5: Run full suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```
Expected: 79 passed (68 + 11).

- [ ] **Step 6: Commit**

```bash
git add src/claude_eyes/compose.py tests/test_compose.py
git commit -m "feat(compose): add compose_bucketed_preview orchestrator"
```

---

## Task 4: `stop_recording` auto-attaches previews

**Files:**
- Modify: `src/claude_eyes/server.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Append failing test to `tests/test_server.py`**

```python
def test_stop_recording_attaches_previews(patched_server, tmp_path: Path) -> None:
    start = patched_server.start_recording(fps=10, resolution_scale=1.0, region=None)
    sid = start["session_id"]
    time.sleep(1.2)                    # ~12 frames at 10 fps across 2 buckets
    result = patched_server.stop_recording(sid)

    assert "previews" in result
    assert result["previews"]["mode"] == "avg"
    assert result["previews"]["bucket_s"] == 1.0
    items = result["previews"]["items"]
    assert len(items) >= 1
    first = items[0]
    assert set(first.keys()) >= {
        "bucket_index",
        "preview_path",
        "frame_range",
        "ts_start_ms",
        "ts_end_ms",
    }
    assert Path(first["preview_path"]).exists()

    patched_server.cleanup_session(sid)
```

- [ ] **Step 2: Run the test to confirm RED**

```bash
.venv/Scripts/python.exe -m pytest tests/test_server.py::test_stop_recording_attaches_previews -v
```
Expected: fail with `KeyError: 'previews'`.

- [ ] **Step 3: Modify `stop_recording` in `src/claude_eyes/server.py`**

Add this import alongside the existing imports (merge with the existing group, preserve ruff ordering):
```python
from .compose import compose_bucketed_preview
```

Replace the final `return { ... }` block of `stop_recording` with the version below. Everything before the return stays exactly as it is.

```python
    frames = list_frames_on_disk(Path(session.frames_dir))

    try:
        bucket_items = compose_bucketed_preview(
            Path(session.frames_dir), bucket_s=1.0, mode="avg"
        )
    except Exception as exc:                                             # noqa: BLE001
        print(f"[claude-eyes] preview composition failed: {exc}", file=sys.stderr)
        bucket_items = []

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
    }
```

(If ruff rejects the `noqa: BLE001` because the rule isn't selected, drop the comment — `except Exception` is already used in `continuous._capture_loop` after Spec 3's final fixes and ruff didn't complain there.)

- [ ] **Step 4: Run the test to confirm GREEN**

```bash
.venv/Scripts/python.exe -m pytest tests/test_server.py -v
```
Expected: new test passes; existing tests still pass.

- [ ] **Step 5: Run full suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```
Expected: 80 passed.

- [ ] **Step 6: Commit**

```bash
git add src/claude_eyes/server.py tests/test_server.py
git commit -m "feat(server): stop_recording auto-attaches bucket previews"
```

---

## Task 5: `compose_timeline_preview` MCP tool

**Files:**
- Modify: `src/claude_eyes/server.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Append failing tests**

```python
def test_compose_timeline_preview_tool_works(patched_server) -> None:
    start = patched_server.start_recording(fps=10, resolution_scale=1.0, region=None)
    sid = start["session_id"]
    time.sleep(1.2)
    patched_server.stop_recording(sid)

    result = patched_server.compose_timeline_preview(
        session_id=sid, bucket_s=0.5, mode="max"
    )

    assert result["session_id"] == sid
    assert result["mode"] == "max"
    assert result["bucket_s"] == 0.5
    assert len(result["items"]) >= 1
    first = result["items"][0]
    assert "preview_max_" in first["preview_path"]
    assert Path(first["preview_path"]).exists()

    patched_server.cleanup_session(sid)


def test_compose_timeline_preview_unknown_session_returns_error(patched_server) -> None:
    result = patched_server.compose_timeline_preview(session_id="sess_ghost")
    assert "error" in result
    assert "unknown session" in result["error"]


def test_compose_timeline_preview_empty_session_returns_error(patched_server) -> None:
    start = patched_server.start_recording(fps=10, resolution_scale=1.0, region=None)
    sid = start["session_id"]
    # Stop immediately (likely 0-1 frames depending on timing); then also delete
    # the session directory to simulate "no frames".
    patched_server.stop_recording(sid)
    import shutil
    from pathlib import Path as _P
    sess_dir = _P(patched_server._registry.get(sid).frames_dir)
    for p in sess_dir.glob("frame_*.jpg"):
        p.unlink()

    result = patched_server.compose_timeline_preview(session_id=sid)
    assert "error" in result
    assert "no frames" in result["error"]

    patched_server.cleanup_session(sid)
```

- [ ] **Step 2: Run the tests to confirm RED**

```bash
.venv/Scripts/python.exe -m pytest tests/test_server.py -v
```
Expected: fail with `AttributeError: ... 'compose_timeline_preview'`.

- [ ] **Step 3: Add the tool to `src/claude_eyes/server.py`**

Insert immediately after `cleanup_session` and before the three continuous-buffer tools (order: on-demand tools → continuous-buffer tools → composition tool → `main`). Use `typing.Literal` — add to existing `typing` import.

Modify the existing `from typing import Any` line to:
```python
from typing import Any, Literal
```

Add the tool:
```python
@mcp.tool()
def compose_timeline_preview(
    session_id: str,
    bucket_s: float = 1.0,
    mode: Literal["avg", "max", "motion"] = "avg",
) -> dict[str, Any]:
    """Recompose the bucket previews of an existing on-demand session with
    different parameters. Writes preview files under
    ``sessions/<session_id>/previews/`` and returns their metadata.

    Continuous buffer sessions are not addressable by this tool; use
    ``query_buffer`` instead to get preview metadata for the rolling buffer.
    """
    session = _registry.get(session_id)
    if session is None:
        return {"error": f"unknown session {session_id}"}

    try:
        items = compose_bucketed_preview(
            Path(session.frames_dir), bucket_s=bucket_s, mode=mode
        )
    except Exception as exc:                                             # noqa: BLE001
        return {"error": f"compose failed: {exc}"}

    if not items:
        return {"error": "session has no frames"}

    effective_bucket_s = max(0.1, bucket_s)
    effective_mode = mode if mode in ("avg", "max", "motion") else "avg"

    return {
        "session_id": session_id,
        "mode": effective_mode,
        "bucket_s": effective_bucket_s,
        "items": [
            {
                "bucket_index": b.bucket_index,
                "preview_path": b.preview_path,
                "frame_range": list(b.frame_range),
                "ts_start_ms": b.ts_start_ms,
                "ts_end_ms": b.ts_end_ms,
            }
            for b in items
        ],
    }
```

- [ ] **Step 4: Run tests to confirm GREEN**

```bash
.venv/Scripts/python.exe -m pytest tests/test_server.py -v
```
Expected: all server tests pass.

- [ ] **Step 5: Run full suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```
Expected: 83 passed.

- [ ] **Step 6: Commit**

```bash
git add src/claude_eyes/server.py tests/test_server.py
git commit -m "feat(server): add compose_timeline_preview MCP tool"
```

---

## Task 6: `query_buffer` attaches previews for the queried range

**Files:**
- Modify: `src/claude_eyes/server.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Append failing test**

```python
def test_query_buffer_includes_previews_in_range(patched_server) -> None:
    patched_server.start_continuous_buffer(fps=10)
    time.sleep(1.3)
    result = patched_server.query_buffer(time_range_s=5, max_frames=5)

    assert "previews" in result
    assert result["previews"]["mode"] == "avg"
    assert result["previews"]["bucket_s"] == 1.0
    items = result["previews"]["items"]
    assert len(items) >= 1
    for it in items:
        assert Path(it["preview_path"]).exists()
        # Previews must intersect the queried range [oldest, now_ms].
        # At fps=10 with 1.3s elapsed, oldest≈0 ms, now≈1300 ms — buckets 0 and 1.
        assert it["ts_start_ms"] <= 5000           # within time_range_s=5
        assert it["ts_end_ms"] >= 0

    patched_server.stop_continuous_buffer()
```

- [ ] **Step 2: Run the test to confirm RED**

```bash
.venv/Scripts/python.exe -m pytest tests/test_server.py::test_query_buffer_includes_previews_in_range -v
```
Expected: fail with `KeyError: 'previews'` in the assertion.

- [ ] **Step 3: Modify `query_buffer` in `src/claude_eyes/server.py`**

Locate the existing `query_buffer` function. After the line `result: dict[str, Any] = { ... }` and BEFORE `if clamped:`, insert the preview composition block. Then include the `previews` field in the result dict.

The final function body (starting from just after the `handle = _continuous_handle` line):
```python
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
        except Exception as exc:                                         # noqa: BLE001
            print(f"[claude-eyes] preview composition failed: {exc}", file=sys.stderr)
            bucket_items = []

        filtered_items = [
            b for b in bucket_items
            if b.ts_end_ms >= oldest and b.ts_start_ms <= now_ms
        ]

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
        }
        if clamped:
            effective_s = max(0, (now_ms - buffer_oldest) // 1000)
            result["warning"] = (
                f"time_range_s exceeded buffer age; clamped to {effective_s}s"
            )
        return result
```

- [ ] **Step 4: Run tests to confirm GREEN**

```bash
.venv/Scripts/python.exe -m pytest tests/test_server.py -v
```
Expected: all server tests pass.

- [ ] **Step 5: Run full suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```
Expected: 84 passed.

- [ ] **Step 6: Commit**

```bash
git add src/claude_eyes/server.py tests/test_server.py
git commit -m "feat(server): query_buffer attaches previews for the queried range"
```

---

## Task 7: `cleanup_session` removes previews (lock-down test)

**Files:**
- Modify: `tests/test_storage.py`

No code change — `cleanup_session_dir` already uses `shutil.rmtree` on the session folder, which removes the `previews/` subdir. This task locks that behaviour down with a test so it can't regress.

- [ ] **Step 1: Append the test**

```python
def test_cleanup_session_dir_also_removes_previews(tmp_path: Path) -> None:
    sess = tmp_path / "with_previews"
    # Frame layout
    _touch_frame(sess, 0, 100)
    _touch_frame(sess, 1, 500)
    # Fake a previews dir as compose would do
    preview_dir = sess / "previews"
    preview_dir.mkdir()
    (preview_dir / "preview_avg_000_0000000000.jpg").write_bytes(b"not really a jpeg")
    (preview_dir / "preview_avg_001_0000001000.jpg").write_bytes(b"not really a jpeg")

    freed = cleanup_session_dir(sess)

    assert freed > 0
    assert not sess.exists()
    assert not preview_dir.exists()
```

- [ ] **Step 2: Run the test — it should pass immediately**

```bash
.venv/Scripts/python.exe -m pytest tests/test_storage.py::test_cleanup_session_dir_also_removes_previews -v
```
Expected: PASS. (This locks existing behaviour in.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_storage.py
git commit -m "test(storage): lock down cleanup removes previews subdir"
```

---

## Task 8: Scan-then-drill pattern in the three skills

**Files:**
- Modify: `.claude/skills/analyze-screen/SKILL.md`
- Modify: `.claude/skills/analyze-page-animation/SKILL.md`
- Modify: `.claude/skills/review-recent-activity/SKILL.md`

- [ ] **Step 1: Update `analyze-screen/SKILL.md`**

In the file, find the existing workflow section ("## The workflow"). Replace step 5 and the common-mistakes section as follows.

The existing step 5 says "Dispatch the `frame-analyzer` subagent via the `Task` tool". Replace with:

```markdown
5. **Scan then drill** — optimise token spend on the subagent:

   **If `frames_count < 30`**: pass `frame_paths` directly to the subagent, as before.

   **Otherwise** (frames_count ≥ 30, previews are attached to the `stop_recording` response):

   a. **Scan pass.** Dispatch `frame-analyzer` with ONLY `previews.items[*].preview_path`. Prompt it to identify which bucket indices contain the behaviour the user asked about, and to return a list of `bucket_index` values.

   b. **Drill pass.** Using the bucket indices the subagent returned, compute the subset of `frame_paths` whose indices fall inside any chosen bucket's `frame_range`. Dispatch `frame-analyzer` again with that filtered list and the original user question. Answer from the second report.

   If the first dispatch returns no interesting buckets, tell the user nothing notable happened in the recording. Do not dispatch a drill pass on an empty result.
```

In the "## Common mistakes to avoid" section, add:

```markdown
- **Skipping the scan pass when `frames_count >= 30`.** Sending hundreds of raw frames to the subagent burns tokens for no reason. The scan pass is your coarse map.
- **Asking the scan subagent for a final answer.** Its job is only to identify interesting bucket indices — the drill pass answers the question.
```

Also add a one-line mention to the "## Parameter selection quick reference" table under an additional "Preview modes" mini-section (append after the existing table):

```markdown
### Preview modes (passed via `compose_timeline_preview` if the default doesn't help)

| Mode | Use when |
|---|---|
| `avg` (default) | General "state of the bucket" — static content stays readable, motion shows as soft trail. |
| `max` | Cursor trails, animation smoothness checks, UI with bright elements on dark background. |
| `motion` | Long recordings where the question is "when did something happen" — heatmap of change. |
```

- [ ] **Step 2: Update `analyze-page-animation/SKILL.md`**

Insert a new section titled "## Scan-then-drill when frames exceed 30" immediately before the existing "## Common mistakes to avoid" section:

```markdown
## Scan-then-drill when frames exceed 30

`stop_recording` auto-attaches `previews` to its response. Reach for scan-then-drill when `frames_count >= 30`; otherwise pass raw frames directly as before.

1. **Scan pass.** Dispatch `frame-analyzer` with only the `previews.items[*].preview_path`. Prompt: "identify the bucket index containing the animation described". Return a `bucket_index`.
2. **Drill pass.** Build the raw `frame_paths` subset whose indices fall inside the chosen bucket's `frame_range`. Dispatch `frame-analyzer` again with that subset and the user's original question.

For a tight Chrome animation the recording is often shorter than a bucket (≤ 1 s) and may land in `frames_count < 30` — in that case skip the scan pass entirely, it adds nothing.

If the default `avg` preview doesn't surface the animation clearly (common for subtle colour transitions on a light background), call `compose_timeline_preview(session_id, mode="max")` and re-scan with the new previews.
```

- [ ] **Step 3: Update `review-recent-activity/SKILL.md`**

Find the existing workflow step 4 ("**Dispatch `frame-analyzer`**..."). Replace it with:

```markdown
4. **Scan then drill** — the `query_buffer` response already contains `previews` for the queried range.

   a. **Scan pass.** Dispatch `frame-analyzer` with `previews.items[*].preview_path` only. Prompt it to identify which bucket(s) contain activity relevant to the user's question. Return the bucket indices.

   b. **Drill pass.** For each chosen bucket, include only the raw frames from `frames` whose `timestamp_ms` falls inside that bucket's `[ts_start_ms, ts_end_ms]`. Dispatch `frame-analyzer` with that narrower list and the original question. Answer from the second report.

   For "when did I do X" questions, consider calling `compose_timeline_preview(session_id="<continuous session id you know>", mode="motion")` first — the motion heatmap makes active buckets obvious. (Note: `compose_timeline_preview` currently does not address the continuous buffer directly; if you need this, rerun `query_buffer` which already uses `avg`/`bucket_s=1.0`.)
```

- [ ] **Step 4: Verify the three files parse as Markdown**

```bash
wc -l .claude/skills/analyze-screen/SKILL.md .claude/skills/analyze-page-animation/SKILL.md .claude/skills/review-recent-activity/SKILL.md
```
Expected: all under 500 lines.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/analyze-screen/SKILL.md .claude/skills/analyze-page-animation/SKILL.md .claude/skills/review-recent-activity/SKILL.md
git commit -m "docs(skills): add scan-then-drill workflow using bucket previews"
```

---

## Task 9: `CLAUDE.md` — hard rule, fps table, scan-then-drill workflow

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add the `fps <= 60` hard rule**

Find the existing `## Hard rules` section. Append this bullet at the end:

```markdown
- **Never set `fps > 60`.** Monitor refresh is 60 Hz; higher values double disk and add zero visual information.
```

- [ ] **Step 2: Replace the abstract fps heuristic with a concrete table**

Find the existing `### `fps` (frames per second, default 3)` subsection under "Parameter heuristics (for `start_recording`)". Replace it (and the existing table) with:

```markdown
### `fps` (frames per second, default 3)

Claude picks fps per task. Concrete guidance:

| Task | Rec. fps |
|---|---|
| OS window / menu animation (~200 ms) | 25–30 |
| Web CSS transition (~300 ms) | 20–25 |
| Fluid 1–2 s animation | 15–20 |
| UI walkthrough, no smoothness judgement | 5–8 |
| Long-range "what did I do" recall | 2–3 |
| Micro-stutter / frame-drop debug | 30 (max) |

Hard ceiling: **60**. Above that, see the hard rule above.
```

- [ ] **Step 3: Add the scan-then-drill workflow section**

Insert a new section immediately before the existing `## Related files` section:

```markdown
## Scan-then-drill workflow

`stop_recording` and `query_buffer` auto-attach bucket previews to their responses (one composited image per `bucket_s=1.0` second of recording, `mode="avg"` by default). Use them to reduce token spend on the frame-analyzer subagent.

Rule of thumb: if a response has `frames_count < 30`, pass raw `frame_paths` directly (previews add no value). Otherwise use two dispatches:

1. **Scan.** Send only `previews.items[*].preview_path` to the subagent with the prompt "identify the bucket indices relevant to the question". Get back a short list.
2. **Drill.** Filter `frame_paths` to the chosen buckets' `frame_range` and dispatch the subagent again with the raw frames and the original question.

If the default `avg` preview doesn't surface the behaviour, call `compose_timeline_preview(session_id, bucket_s=0.5, mode="max")` or `mode="motion"` and re-scan. Skills (`analyze-screen`, `analyze-page-animation`, `review-recent-activity`) all follow this pattern — reach for them first, they encode the flow.
```

- [ ] **Step 4: Verify length**

```bash
wc -l CLAUDE.md
```
Expected: under 200 lines. (It was 134 before; the additions should bring it to ~165-175.)

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): add fps<=60 rule, fps table, scan-then-drill section"
```

---

## Task 10: Full suite + lint + type check + smoke

**Files:**
- Possibly modify: any file flagged by ruff / mypy.

- [ ] **Step 1: Full suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```
Expected: **85 passed** (68 prior + 17 new across Tasks 2-7). No failures.

- [ ] **Step 2: mypy**

```bash
.venv/Scripts/python.exe -m mypy src/claude_eyes
```
Expected: `Success: no issues found in 8 source files`.

Common candidates for fixes: missing annotation on a numpy return, missing `Literal` on `mode`. Fix minimally and re-run.

- [ ] **Step 3: ruff**

```bash
.venv/Scripts/python.exe -m ruff check src tests
```
Expected: `All checks passed!`.

Common candidates: long lines in the new test bodies, unused `np` import if a test file imports but doesn't reach the assertions. Wrap or remove.

- [ ] **Step 4: Smoke — re-run the Start-menu scenario with correct parameters**

Manual step, user-driven. Restart Claude Code so the updated skills + CLAUDE.md are loaded. Ask Claude (via the `analyze-screen` skill) to analyse the Windows Start-menu animation. Expect Claude to:

1. Choose `fps=25-30` per the new CLAUDE.md table (not 15).
2. Receive `previews` in the `stop_recording` response.
3. If `frames_count >= 30`: dispatch a scan pass with preview paths, then a drill pass with the filtered raw frames.
4. Answer about the animation's smoothness using specific frame references.

No commit in this step unless the test reveals a real bug.

- [ ] **Step 5: If Steps 2 or 3 required code fixes, commit them**

```bash
git add -u
git commit -m "chore: satisfy mypy/ruff after token-optimisation changes"
```

If nothing was changed, this step is a no-op.

---

## Self-Review

**1. Spec coverage.**

| Spec requirement | Task(s) |
|---|---|
| `numpy>=1.26` declared | 1 |
| `_blend_avg`, `_blend_max`, `_blend_motion` helpers | 2 |
| `compose_bucketed_preview` orchestrator | 3 |
| `stop_recording` auto-attaches `previews` | 4 |
| `compose_timeline_preview` MCP tool | 5 |
| `query_buffer` attaches `previews` filtered to range | 6 |
| `cleanup_session` wipes `previews/` (test lock-in) | 7 |
| Skill updates: scan-then-drill in all three | 8 |
| `CLAUDE.md`: fps≤60 hard rule, fps table, scan-then-drill section | 9 |
| Full suite green + mypy + ruff clean | 10 |
| Manual smoke: Start-menu with correct fps and scan-then-drill | 10 step 4 |
| Default `mode="avg"`, `bucket_s=1.0` | 3, 4, 6 |
| `bucket_s` clamped to ≥ 0.1 | 3 (orchestrator + test) |
| Unknown `mode` falls back to `avg` | 3 (test + impl) |
| Motion single-frame fallback to avg | 2 (test + impl) |
| Preview filename `preview_<mode>_<idx:03d>_<ts_ms:010d>.jpg` | 3 |
| Preview dir `sessions/<id>/previews/` | 3, 7 |
| `stop_continuous_buffer` unchanged | covered by omission |

No spec requirement left without a task.

**2. Placeholder scan.** No "TBD", "TODO", "similar to…", or undefined symbols. Every test step shows the exact code; every impl step shows the exact final function shape. Expected command outputs are concrete (pass count per step).

**3. Type consistency.**

- `BlendMode = Literal["avg", "max", "motion"]` defined in Task 2, reused in Task 3, referenced by the `mode` param in Task 5 via `typing.Literal` (same values).
- `BucketInfo` introduced in Task 3 with exactly five fields; consumed in Tasks 4, 5, 6 with the same field names.
- `compose_bucketed_preview(session_dir, bucket_s, mode)` signature stable across Tasks 3, 4, 5, 6.
- Preview items dict shape (`bucket_index`, `preview_path`, `frame_range`, `ts_start_ms`, `ts_end_ms`) identical in Tasks 4, 5, 6.
- Test `_touch_frame` helper already exists in `tests/test_storage.py` (added in Spec 2) — Task 7 reuses it without redefining.
- `_FakeMSS` — not re-extended; existing `.instances`/`.grabbed` additions from Spec 3 remain untouched.

No drift. Plan ready.

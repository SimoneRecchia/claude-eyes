# claudeEyes — Capture-time Intelligence (Spec 5) Design

**Status:** approved for implementation on 2026-04-18.
**Branch:** `feat/capture-intelligence` (new branch off `main` which already contains Spec 1+2+3+4).
**Precedent:** builds on Spec 4 (bucket preview compositing). All prior specs shipped on main via PRs #1, #2, #3.

---

## Goal

Stop wasting tokens on "dead frames" — the idle seconds at the start and end of every recording while the user thinks, cues Claude, or the stop lags. A post-capture Python pass identifies the **active range** (first and last frame with meaningful motion) and reports it alongside the existing response fields. Also report the **effective fps** achieved (distinct from nominal) so Claude can detect I/O bottlenecks early and adapt future recordings.

## Scope

**In scope (Spec 5):**

- Compute `fps_effective` (real fps from frame timestamps) and attach to `stop_recording` and `query_buffer` responses.
- Compute `active_range: [first_idx, last_idx] | null` via an adaptive motion-detection pass on downscaled frames; attach to the same responses.
- Attach `activity_score_mean` (diagnostic) to the responses.
- Add a new MCP tool `trim_session(session_id)` that opt-in **applies** the trim: deletes frames outside the active range and regenerates preview images. Distruction is never automatic.
- Add a new module `src/claude_eyes/activity.py` with three public functions: `score_frame_motion`, `detect_active_range`, `compute_fps_effective`.
- Update the three skills (`analyze-screen`, `analyze-page-animation`, `review-recent-activity`) with an "Active range" section explaining how to use the new fields.
- Update `CLAUDE.md` scan-then-drill section to reference `active_range` + `fps_effective`.

**Out of scope:**

- Middle-gap detection (finding pauses inside the recording). Leading + trailing idle only; middle activity is preserved even if it contains static sub-sequences.
- Motion-triggered capture (skip saving frames at capture time). Deferred to a future spec (equivalent to the previously-deferred Spec 4b pHash dedup).
- Automatic application of trim inside `stop_recording`. Always opt-in via the new tool.
- Changes to `start_recording`, `start_continuous_buffer`, `stop_continuous_buffer`, `list_frames`, `cleanup_session`, `compose_timeline_preview`. Those tools keep their existing signatures and behaviour.

## Design decisions (recap)

1. **Soft + opt-in hard trim.** `stop_recording` reports `active_range` as metadata but touches no files; `trim_session` is the only destructive tool, called explicitly by Claude or the user.
2. **Motion scoring = MSE on downscaled frames.** Mean-absolute-diff between consecutive frames, computed on 128×72 thumbnails. Fast, deterministic, numpy-native (reuses Spec 4 dependency).
3. **Adaptive threshold.** Threshold is derived per-session from the score distribution: `baseline = percentile(scores, 25); threshold = baseline + 3 * MAD`. No magic numbers. Adapts to scenes with video playing in background vs static desktops.
4. **Leading + trailing only.** Active range is `[first i where score > threshold, last i where score > threshold]`. Static frames inside that range are kept — preserves context and is simple to represent.
5. **Best-effort semantics.** If activity detection crashes or the session is too short to compute, response contains `active_range: null` and `fps_effective` still populated. Never breaks the recording.
6. **`trim_session` is destructive and sequential.** Deletes files outside `active_range` and recomposes the preview. Rejects active sessions (still recording) and the continuous buffer (different lifecycle).

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│ stop_recording (modified)                                                │
│  ─ stop recorder, enumerate frames on disk (as today)                    │
│  ─ compute_fps_effective(frames, duration_s) -> float                    │
│  ─ detect_active_range(session_dir) -> tuple[int,int] | None             │
│  ─ compose_bucketed_preview (Spec 4, unchanged)                          │
│  ─ response now includes:                                                │
│       fps_effective: float                                               │
│       active_range: [int, int] | null                                    │
│       activity_score_mean: float                                         │
│       previews: {...}         (Spec 4)                                   │
│       frame_paths: [...]      (unchanged)                                │
└──────────────┬───────────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ trim_session (new MCP tool, opt-in, destructive)                         │
│  ─ Reject if session is in _active (still recording)                     │
│  ─ Reject if session_id == "_continuous"                                 │
│  ─ Recompute active_range (idempotent if already trimmed)                │
│  ─ Delete frame files outside [first_idx, last_idx]                      │
│  ─ Delete old previews/ subdir                                           │
│  ─ Re-run compose_bucketed_preview on surviving frames                   │
│  ─ Response: { kept_frames, deleted_frames, freed_bytes, previews }      │
└──────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────┐
│ query_buffer (modified)                                                  │
│  ─ Same detection, scoped to [oldest, now_ms] slice of continuous dir    │
│  ─ Response adds fps_effective (of the slice), active_range, score_mean  │
└──────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────┐
│ NEW src/claude_eyes/activity.py                                          │
│                                                                          │
│   def score_frame_motion(prev, curr) -> float                            │
│   def compute_fps_effective(frames, duration_s) -> float                 │
│   def detect_active_range(session_dir, *, include_frames=None)           │
│       -> tuple[int, int] | None                                          │
│                                                                          │
│   Internal helpers:                                                      │
│   _downscale_frame(path, size=(128,72)) -> np.ndarray                    │
│   _compute_scores(frames) -> list[float]                                 │
│   _adaptive_threshold(scores) -> float                                   │
└──────────────────────────────────────────────────────────────────────────┘
```

## Tool signature changes and additions

### Modified: `stop_recording`

Keeps its existing fields, adds three new ones.

```python
stop_recording(session_id: str) -> {
    "session_id": str,
    "frames_count": int,
    "duration_s": float,
    "frames_dir": str,
    "frame_paths": list[str],
    "previews": {...},                                  # Spec 4 — unchanged
    "fps_effective": float,                             # NEW
    "active_range": tuple[int, int] | None,             # NEW
    "activity_score_mean": float,                       # NEW (diagnostic)
}
```

### Modified: `query_buffer`

Same three new fields, scoped to the queried slice.

```python
query_buffer(time_range_s: int, max_frames: int = 30) -> {
    "frames": [...],                                    # existing
    "total_in_range": int,                              # existing
    "oldest_frame_age_s": float,                        # existing
    "newest_frame_age_s": float,                        # existing
    "previews": {...},                                  # Spec 4
    "fps_effective": float,                             # NEW
    "active_range": tuple[int, int] | None,             # NEW
    "activity_score_mean": float,                       # NEW
    "warning"?: str,                                    # existing optional
}
```

### New: `trim_session`

```python
trim_session(session_id: str) -> {
    "session_id": str,
    "kept_frames": int,
    "deleted_frames": int,
    "freed_bytes": int,
    "previews": {...},                                  # regenerated
} | { "error": str }
```

Error paths:
- `session_id == "_continuous"` → `{"error": "trim not supported on continuous buffer"}`
- `session_id in _active` → `{"error": "session is still recording"}`
- `session_id` unknown → `{"error": "unknown session <id>"}`
- Session has 0 frames → `{"error": "session has no frames"}`
- `detect_active_range` returns None (all frames idle or too few) → `{"error": "no active range detected; nothing to trim"}`

## Component changes

### New module `src/claude_eyes/activity.py`

```python
"""Post-capture activity detection and fps-effective reporting."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from .storage import FrameInfo, list_frames


_THUMB_SIZE = (128, 72)            # 16:9, ~9216 pixels per frame
_CHUNK_SIZE = 500                  # cap memory during long recordings


def score_frame_motion(prev: np.ndarray, curr: np.ndarray) -> float:
    """Mean per-pixel absolute difference. Both inputs same shape, uint8."""
    return float(np.abs(curr.astype(np.int16) - prev.astype(np.int16)).mean())


def compute_fps_effective(frames_count: int, duration_s: float) -> float:
    """Real fps achieved, rounded to 2 decimals. 0.0 if duration invalid."""
    if duration_s <= 0 or frames_count < 2:
        return 0.0
    return round(frames_count / duration_s, 2)


def detect_active_range(
    session_dir: Path,
    *,
    include_frame_indices: set[int] | None = None,
) -> tuple[tuple[int, int] | None, float]:
    """Identify the leading+trailing-trimmed range of motion activity.

    Returns ``(range_or_None, score_mean)`` so callers can surface
    ``activity_score_mean`` for diagnostics regardless of whether the
    range was detected.

    If ``include_frame_indices`` is provided, only those frames are
    scored (used by ``query_buffer`` to scope to the queried slice).
    """
    frames = list_frames(session_dir)
    if include_frame_indices is not None:
        frames = [f for f in frames if f["index"] in include_frame_indices]
    if len(frames) < 2:
        return None, 0.0

    scores = _compute_scores(frames)
    score_mean = float(np.mean(scores)) if scores else 0.0

    if not scores:
        return None, score_mean

    threshold = _adaptive_threshold(scores)
    arr = np.array(scores)
    active = arr > threshold
    if not active.any():
        return None, score_mean

    first = int(np.argmax(active))
    last = len(active) - 1 - int(np.argmax(active[::-1]))
    # scores[i] is the motion between frames[i] and frames[i+1].
    # Active at scores[i] means both frames[i] and frames[i+1] are
    # relevant; widen the range by one on the right.
    return (first, min(last + 1, len(frames) - 1)), score_mean


def _compute_scores(frames: list[FrameInfo]) -> list[float]:
    """Return the N-1 motion scores between consecutive frames."""
    scores: list[float] = []
    prev_thumb: np.ndarray | None = None
    # Process in chunks to cap peak memory for huge recordings.
    for chunk_start in range(0, len(frames), _CHUNK_SIZE):
        chunk = frames[chunk_start : chunk_start + _CHUNK_SIZE]
        for f in chunk:
            curr_thumb = _downscale_frame(Path(f["path"]))
            if prev_thumb is not None:
                scores.append(score_frame_motion(prev_thumb, curr_thumb))
            prev_thumb = curr_thumb
    return scores


def _downscale_frame(path: Path) -> np.ndarray:
    """Load a JPEG, resize to _THUMB_SIZE, return (H, W, 3) uint8."""
    with Image.open(path) as img:
        rgb = img.convert("RGB").resize(_THUMB_SIZE, Image.Resampling.BILINEAR)
        return np.asarray(rgb, dtype=np.uint8)


def _adaptive_threshold(scores: list[float]) -> float:
    """baseline + 3 * MAD, with a floor to avoid zero-threshold drift."""
    arr = np.array(scores)
    baseline = float(np.percentile(arr, 25))
    mad = float(np.median(np.abs(arr - np.median(arr))))
    return baseline + 3 * max(mad, 0.5)
```

### Modified `src/claude_eyes/server.py`

**`stop_recording` additions** — after the existing `compose_bucketed_preview` call, compute activity:

```python
# after frames = list_frames_on_disk(...)
try:
    active_range, score_mean = detect_active_range(Path(session.frames_dir))
except Exception as exc:  # noqa: BLE001
    print(f"[claude-eyes] activity detection failed: {exc}", file=sys.stderr)
    active_range, score_mean = None, 0.0

fps_effective = compute_fps_effective(frames_count, duration_s)

return {
    ...existing fields...,
    "previews": {...},
    "fps_effective": fps_effective,
    "active_range": list(active_range) if active_range else None,
    "activity_score_mean": round(score_mean, 3),
}
```

**`query_buffer` additions** — similar, scoped to the frames in range:

```python
# after sampled = sample_frames(all_frames, max_frames)
try:
    indices = {f["index"] for f in all_frames}
    active_range, score_mean = detect_active_range(
        handle.session_dir, include_frame_indices=indices
    )
except Exception as exc:  # noqa: BLE001
    active_range, score_mean = None, 0.0

fps_effective = compute_fps_effective(len(all_frames), time_range_s)
# ... include fps_effective / active_range / activity_score_mean in result
```

**`trim_session` new tool** — inserted after `compose_timeline_preview`:

```python
@mcp.tool()
def trim_session(session_id: str) -> dict[str, Any]:
    """Apply the active-range trim: delete frames outside the detected
    motion window and regenerate previews. Opt-in and destructive.
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

    # Delete files outside [first, last] (inclusive indices).
    to_delete = [f for f in frames if not (first <= f["index"] <= last)]
    freed = 0
    for f in to_delete:
        p = Path(f["path"])
        try:
            freed += p.stat().st_size
            p.unlink()
        except OSError:
            continue

    # Remove old previews/ subdir and recompose.
    import shutil
    previews_dir = session_dir / "previews"
    if previews_dir.is_dir():
        shutil.rmtree(previews_dir, ignore_errors=True)

    try:
        new_previews = compose_bucketed_preview(session_dir, bucket_s=1.0, mode="avg")
    except Exception as exc:  # noqa: BLE001
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

### Skill updates (three files)

Each skill gets a new "## Active range" section after the existing "Scan-then-drill" block:

```markdown
## Active range

`stop_recording` and `query_buffer` attach `active_range: [first_idx, last_idx] | null`,
`fps_effective: float`, and `activity_score_mean: float`. Use them to further reduce
token spend and catch I/O bottlenecks.

**Before scan-then-drill:**

1. If `active_range` is not null, filter `frame_paths` to indices in `[first_idx, last_idx]`
   before scanning. A 400-frame recording with a 30-frame active range drops the scan
   input by 90%.
2. If `active_range` is null, the algorithm found no activity above its adaptive threshold
   — fall back to the full `frame_paths` as before.

**Check `fps_effective`:**

- If `fps_effective < 0.8 × fps_nominal` (the value you passed to `start_recording`), warn
  the user: capture is disk-I/O-bound. Suggest `resolution_scale` lower or `region` tighter
  for the next recording.

**Optional: free disk via `trim_session`.**

- After the analysis, if you want to drop the dead frames from disk too (not just ignore
  them in the subagent pass), call `mcp__claude_eyes__trim_session(session_id)`. This
  deletes everything outside `active_range` and regenerates previews.
- `trim_session` is never called automatically. Ask yourself: will I or the user need the
  dead frames later? If not, trim.
```

### CLAUDE.md update

In the existing `## Scan-then-drill workflow` section, add a new bullet at the top of the numbered list:

```markdown
0. **Respect `active_range`.** `stop_recording` and `query_buffer` now report the frame
   range with actual motion. If it's present, filter `frame_paths` to that range before
   scan-then-drill. If `fps_effective < 0.8 × fps_nominal`, warn the user about I/O
   saturation.
```

## Edge cases

| Case | Behaviour |
|---|---|
| Session with 0 frames | `fps_effective=0.0`, `active_range=null`, `activity_score_mean=0.0`. No error. |
| All frames below threshold (static desktop) | `active_range=null`. Skills fall back to `frame_paths`. |
| All frames active (turbulent scene) | `active_range=[0, n-1]`. Effectively a no-op for trim. |
| Single-frame burst | `active_range=[i, i+1]`. Burst preserved. |
| Frames with different sizes (future-proof, impossible today) | Resize to first frame's dims before scoring (same logic as compose). |
| `trim_session` on active session | Structured error, no action. |
| `trim_session` called twice | Practically idempotent: the already-trimmed session has uniformly-active frames, so the adaptive threshold typically finds no range above it and `trim_session` returns `{"error": "no active range detected; nothing to trim"}`. Nothing is destroyed; calling twice is safe. |
| `trim_session` on unknown session | Structured error. |
| `trim_session` on `_continuous` | Rejected — buffer lifecycle is different. |
| `query_buffer` on slice with <2 frames | `active_range=null`, `fps_effective=0.0`. No error. |
| Huge session (>2000 frames) | Scoring runs in 500-frame chunks; peak memory stays under ~50 MB. |
| `activity.py` raises (bug or OOM) | `stop_recording` swallows the exception, logs to stderr, returns `active_range=null` and `fps_effective` best-effort. Never breaks the recording. |
| Scoring on corrupted frame file | That pair's score is skipped; adjacent pairs still computed. |

## Concurrency and safety

- `detect_active_range` is pure IO + CPU on frame files. No shared mutable state.
- `trim_session` takes `_continuous_lock` is **not** required — it only touches on-demand sessions, which are identified via the `_registry` (guarded elsewhere). However, it rejects sessions in `_active` (still recording), removing the only conflict window.
- `query_buffer` already holds `_continuous_lock`; activity detection runs inside that lock. The continuous capture thread writes new frames while we read — same concurrency contract as Spec 4's compose, and equally safe (file read is a consistent snapshot of what's on disk).
- No new locks needed.

## Testing strategy

New tests (suite 85 → ~95):

```
tests/test_activity.py (NEW)
  + test_score_frame_motion_identical_frames_returns_zero
  + test_score_frame_motion_fully_changed_returns_high
  + test_compute_fps_effective_from_frame_list
  + test_compute_fps_effective_zero_duration
  + test_detect_active_range_all_static_returns_none
  + test_detect_active_range_leading_trailing_idle_trimmed
  + test_detect_active_range_adaptive_threshold_ignores_noisy_baseline
  + test_detect_active_range_too_few_frames_returns_none

tests/test_server.py (extend)
  + test_stop_recording_attaches_fps_effective_and_active_range
  + test_trim_session_removes_dead_frames_and_regenerates_previews
  + test_trim_session_rejects_active_session
  + test_trim_session_rejects_continuous_session_id
  + test_trim_session_unknown_session_returns_error
  + test_query_buffer_includes_fps_effective_and_active_range
```

Synthetic fixtures: tests create 8×8 JPEG frames on tmp disk with hand-crafted motion profiles (e.g., [static × 5, moving × 3, static × 5]) and assert the detected range matches. No real screen capture needed.

## Disk and performance

- Scoring cost: ~400 ms for a 500-frame session (PIL thumbnail + numpy diff at 128×72). Chunked at 500 to cap memory at ~13 MB peak.
- `stop_recording` total latency: Spec 4 added +100-200 ms (compose), Spec 5 adds +300-500 ms (activity) → **+400-700 ms over pre-Spec-4 baseline**. Still under 1 s for the on-demand case.
- `query_buffer` latency: proportional to slice size. 60 frames = ~50 ms.
- `trim_session` latency: proportional to deleted frames. 400 deletes + recompose ≈ 500-800 ms.

## Success criteria

1. Suite 95+ tests green, mypy + ruff clean.
2. Re-run of the Start-menu smoke test with Spec 5 active: `active_range` correctly brackets the ~30 frames around the menu open/close (from ~384 total). Subagent reads ~30 frames instead of ~64 sampled (first attempt) or ~49 via scan-then-drill (second). 50-80% token reduction vs Spec 4 alone.
3. `stop_recording` latency under 1 s for recordings < 600 frames.
4. Manual test with `trim_session`: disk usage drops by ≥ 80% on the same Start-menu smoke.
5. **Back-compat:** callers that ignore the new fields see identical behaviour to Spec 4.

## What this spec does NOT change

- `start_recording`, `start_continuous_buffer`, `stop_continuous_buffer`, `list_frames`, `cleanup_session`, `compose_timeline_preview` — signatures and behaviour unchanged.
- Preview composition logic in `compose.py` — untouched. `trim_session` just calls it again after deleting frames.
- `frame-analyzer` subagent — unchanged.
- Hooks, `.mcp.json`, session registry structure — unchanged.

## Open questions for the implementation plan

None. All interfaces are locked. Remaining detail (exact test assertions, precise error strings, numpy array shapes) is implementation work.

# claudeEyes — Token Optimization via Preview Compositing (Spec 4a+4c) Design

**Status:** approved for implementation on 2026-04-18.
**Branch:** new `feat/token-optimization` (kept separate from the now-merged `main`).
**Precedent:** builds on Spec 1+2+3 (all shipped to `main` via PR #2). 68 tests currently green.

---

## Goal

Reduce the vision-token cost of analysing a screen recording by one order of magnitude, without losing analysis quality. The key insight: the subagent does not need to read every captured frame. A Python-side compositing step bundles each `bucket_s` window of frames into a single "preview" image; the subagent scans the preview timeline first, then drills into the raw frames of only the buckets that matter. Python does the deterministic heavy lifting; the AI budget is spent only where judgement is needed.

## Scope

**In scope (Spec 4a + 4c):**

- A new Python module `compose.py` that groups frames into time buckets and produces one composite per bucket in three modes (`avg`, `max`, `motion`).
- `stop_recording` auto-attaches preview metadata to its response (default `mode="avg"`, `bucket_s=1.0`).
- `query_buffer` attaches preview metadata for the queried time range.
- A new MCP tool `compose_timeline_preview` for on-demand recompositing with a different `mode` or `bucket_s`.
- Skill updates (`analyze-screen`, `analyze-page-animation`, `review-recent-activity`) with a "scan-then-drill" workflow.
- `CLAUDE.md` updated with: hard rule `fps <= 60`, scan-then-drill guidance, concrete fps-per-task examples.

**Out of scope (deferred to Spec 4b):**

- Perceptual-hash dedup of near-identical frames. Useful after 4a lands if disk becomes a problem; the YAGNI-compliant choice for now.

**Explicitly rejected:**

- Any attempt to auto-adapt `bucket_s` inside the Python code. The skill suggests appropriate values; the code uses whatever it is given.
- Motion overlay with per-pixel compositing on a representative frame. `mode="motion"` is a pure summed-diff image for 4a; advanced overlays can land later if needed.

## Design decisions (recap)

1. **Claude picks fps per task** (already the design since Spec 1). The problem in the manual smoke was Claude choosing 15 fps for a ~200 ms animation — a heuristic-application failure, not a design failure. Fix: better concrete examples in `CLAUDE.md`.
2. **Hard `fps <= 60` ceiling.** Above 60 Hz there is no usable visual information on a standard monitor. Document as a hard rule.
3. **Always compose previews.** The user explicitly asked for this: "un frame al secondo inizialmente". Cost is microseconds of numpy — no reason to gate it. Skills decide whether to USE the preview (they can skip if `frames_count` is small).
4. **Three modes, Claude picks.** `avg` (default, general "state of the bucket"), `max` (trails / animation traces), `motion` (heatmap of where change happened).
5. **`bucket_s = 1.0` default.** Matches "1 frame per second" mental model; produces a tractable number of previews for the subagent (25 for a 25-second recording).
6. **Hybrid tool surface.** `stop_recording` auto-composes with defaults; `compose_timeline_preview` lets Claude recompose with different parameters.

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  Claude Code                                                           │
│  Skills (analyze-screen, analyze-page-animation,                       │
│  review-recent-activity) — updated with scan-then-drill pattern       │
└──────────┬───────────────────────────────────────────────────────────┘
           │ MCP stdio
           ▼
┌──────────────────────────────────────────────────────────────────────┐
│  claude_eyes MCP server (Spec 1+2+3 tools + 1 new)                   │
│                                                                        │
│  Modified:                                                             │
│  - stop_recording       now returns `previews: {...}` block           │
│  - query_buffer         now returns `previews: {...}` for the range   │
│                                                                        │
│  NEW:                                                                  │
│  - compose_timeline_preview(session_id, bucket_s, mode)               │
│                                                                        │
│  Unchanged:                                                            │
│  - start_recording, list_frames, cleanup_session,                     │
│    start_continuous_buffer, stop_continuous_buffer                    │
└──────────┬───────────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────────┐
│  NEW src/claude_eyes/compose.py                                        │
│  - compose_bucketed_preview(session_dir, bucket_s, mode) -> list[...] │
│  - _blend_avg / _blend_max / _blend_motion  (numpy)                   │
│                                                                        │
│  Preview output: sessions/<id>/previews/                               │
│                  preview_<mode>_<idx:03d>_<ts_start_ms:010d>.jpg      │
└──────────────────────────────────────────────────────────────────────┘
```

## Tool signature changes and additions

### Modified: `stop_recording`

New `previews` field in the response; all existing fields unchanged.

```python
stop_recording(session_id: str) -> {
    "session_id": str,
    "frames_count": int,
    "duration_s": float,
    "frames_dir": str,
    "frame_paths": list[str],
    "previews": {
        "mode": "avg",
        "bucket_s": 1.0,
        "items": [
            {
                "bucket_index": int,
                "preview_path": str,
                "frame_range": tuple[int, int],   # inclusive
                "ts_start_ms": int,
                "ts_end_ms": int,
            },
            ...
        ],
    },
}
```

If `frames_count == 0`, `previews.items` is an empty list and no preview files are written.

### Modified: `query_buffer`

New `previews` field covering the queried time range; all other fields (`frames`, `total_in_range`, `warning`) unchanged.

```python
query_buffer(time_range_s: int, max_frames: int = 30) -> {
    ...existing fields...
    "previews": {
        "mode": "avg",
        "bucket_s": 1.0,
        "items": [... same shape as above ...],
    },
}
```

Preview items only cover buckets whose `[ts_start_ms, ts_end_ms]` range intersects the queried `[oldest, now_ms]`.

### New: `compose_timeline_preview`

```python
compose_timeline_preview(
    session_id: str,
    bucket_s: float = 1.0,
    mode: Literal["avg", "max", "motion"] = "avg",
) -> {
    "session_id": str,
    "mode": "avg" | "max" | "motion",
    "bucket_s": float,
    "items": [... same shape ...],
}

# error path:
# { "error": "unknown session <id>" }
# { "error": "session has no frames" }  (if session_dir exists but is empty)
```

Always overwrites existing preview files with the same `(mode, bucket_index, ts_start_ms)` filename; idempotent for a given input.

## Component changes

### New module `src/claude_eyes/compose.py`

```python
@dataclass
class BucketInfo:
    bucket_index: int
    preview_path: str
    frame_range: tuple[int, int]
    ts_start_ms: int
    ts_end_ms: int


BlendMode = Literal["avg", "max", "motion"]


def compose_bucketed_preview(
    session_dir: Path,
    bucket_s: float = 1.0,
    mode: BlendMode = "avg",
) -> list[BucketInfo]:
    """Group frames into buckets of bucket_s seconds, blend each into one
    preview image written to session_dir/previews/, return metadata list.

    Clamps bucket_s to >= 0.1. Skips empty buckets (no frames in interval).
    Creates session_dir/previews/ if missing. Overwrites existing previews
    with the same (mode, bucket_index, ts_start_ms) filename.
    """
```

Internal helpers:

```python
def _blend_avg(arr: np.ndarray) -> np.ndarray:
    """Mean across frames. arr shape: (N, H, W, 3), dtype uint8 -> float32."""

def _blend_max(arr: np.ndarray) -> np.ndarray:
    """Max across frames (lighten)."""

def _blend_motion(arr: np.ndarray) -> np.ndarray:
    """Sum of absolute differences between consecutive frames, normalised to
    0-255 range, single-channel expanded to RGB (pure magnitude, no overlay
    in this spec)."""
```

Preview filename: `preview_{mode}_{bucket_index:03d}_{ts_start_ms:010d}.jpg`, JPEG quality = `JPEG_QUALITY` (85, reused from `config.py`).

### Modified `src/claude_eyes/server.py`

1. `stop_recording`: after computing `frames` and before returning, call `compose_bucketed_preview(session_dir, bucket_s=1.0, mode="avg")` and attach the items. If composing raises (e.g., disk full for preview write), log to stderr and return the response with `previews.items = []`. Never propagate exceptions — the recording is valid even if composition fails.

2. `query_buffer`: after `sample_frames`, compute `previews = compose_bucketed_preview(...)` then filter to the bucket indices whose `[ts_start_ms, ts_end_ms]` intersects the queried range. Same error handling.

3. New `@mcp.tool() compose_timeline_preview(session_id, bucket_s, mode)`: looks up `session.frames_dir` via `_registry.get(session_id)` (or via `_continuous_handle.session_dir` if the id matches the continuous one — see edge cases); returns structured error if session missing. Clamps `bucket_s >= 0.1`. Clamps `mode` to the three allowed values (default to `"avg"` on unknown).

### Modified `pyproject.toml`

Add `numpy>=1.26` to `dependencies`. Already transitive via Pillow but declare it explicitly since we import it directly.

### Skill updates (scan-then-drill pattern)

Each of the three skills gets a new section that replaces the current "dispatch frame-analyzer with all frame paths" step:

```
When stop_recording returns:

1. Inspect `previews.items`. If empty (very short recording or compose
   failed), fall back to dispatching the subagent directly with
   `frame_paths` as today.

2. If `frames_count < 30`, skip previews entirely and dispatch with
   `frame_paths` directly — previews add no value at low frame counts.

3. Otherwise, FIRST DISPATCH: send the preview paths to frame-analyzer
   with the prompt "These are `bucket_s`-second composites of a
   `frames_count`-frame recording at `fps` fps, mode=`mode`. Identify
   which bucket(s) contain the behaviour described in the question.
   Return a list of bucket_index values."

4. If the subagent returns N bucket indices, build `frame_paths` filtered
   by `frame_range` of each chosen bucket.

5. SECOND DISPATCH: send the filtered raw frames with the original user
   question. Synthesize and answer.

6. `cleanup_session` removes frames + previews together (previews live
   inside session_dir).
```

Each skill's prose is adapted to its trigger: `analyze-screen` says "desktop animation", `analyze-page-animation` says "Chrome-triggered animation", `review-recent-activity` says "rolling buffer query".

Mode-selection guidance per skill:
- `analyze-screen`, `analyze-page-animation`: default `mode="avg"`; use `mode="max"` when the user asks about smoothness / cursor trails / animation stutter (trails dominate the composite).
- `review-recent-activity`: default `mode="avg"` for "state-of-screen" queries; consider `mode="motion"` when the user asks "when did I do something" (heatmap highlights active buckets).

### `CLAUDE.md` updates

Three additions, all before `## Related files`:

1. New hard rule in the existing `## Hard rules` section: `- **Never set fps > 60.** Monitor refresh is 60 Hz; higher values double disk and add zero visual information.`

2. Concrete fps-per-task examples replacing the existing abstract heuristics:

| Task | Rec. fps |
|---|---|
| OS window / menu animation (~200 ms) | 25–30 |
| Web CSS transition (~300 ms) | 20–25 |
| Fluid 1-2 s animation | 15–20 |
| UI walkthrough, no smoothness judgement | 5–8 |
| Long-range "what did I do" recall | 2–3 |
| Micro-stutter / frame-drop debug | 30 (max) |

3. New section `## Scan-then-drill workflow` with the high-level flow outlined above, cross-linking to the three skills.

## Edge cases

| Case | Handling |
|---|---|
| `bucket_s > session_duration` | One bucket containing every frame; `items[0]` covers the whole session; no error. |
| `frames_count == 0` | `items = []`, no preview files written, no error. |
| `mode="motion"` on a 1-frame bucket | Motion needs ≥ 2 frames; fallback to `avg` for that bucket and include `"fallback_mode": "avg"` in its metadata. |
| Bucket interval with no frames | Skip — no `BucketInfo` for it. Bucket indices stay monotonically increasing for written buckets only. |
| `compose_timeline_preview` with unknown session | `{"error": "unknown session <id>"}`. |
| `compose_timeline_preview` with session that has no frames yet | `{"error": "session has no frames"}`. |
| Disk full while writing preview | Log to stderr; skip that bucket; include remaining buckets in return. |
| Frame size drift inside a bucket (currently impossible but future-proof) | Resize all frames to first frame's dimensions before blending. |
| `bucket_s <= 0` | Clamp to `0.1`; include `"warning": "bucket_s clamped to 0.1"` in response. |
| `mode` not in `{avg, max, motion}` | Default to `"avg"`; include warning. |
| `cleanup_session` on session with previews | Already works: `cleanup_session_dir(session_dir)` is `shutil.rmtree` on the parent, removing `previews/` too. |
| `compose_timeline_preview` called twice with same params | Idempotent — overwrites. Callers can recompose safely. |
| `compose_timeline_preview` called with different params after auto-compose | Writes new files under different filename (mode is in the name); both sets live in `previews/` until cleanup. |

## Concurrency and safety

- Compositing is synchronous inside `stop_recording`; the recorder thread has already stopped, no contention.
- `query_buffer` composes while the continuous capture thread is still running. The capture thread writes new frames; compose reads an on-disk snapshot of what exists at call time. Frames added mid-compose appear in the next bucket (or the current one if timing lines up); old pruned frames may cause one bucket to be sparse. Acceptable — the buffer is inherently approximate.
- No new locks needed. `compose_bucketed_preview` is pure IO + CPU.

## Testing strategy

New tests (suite 68 → ~80):

```
tests/test_compose.py (new file)
  + test_compose_avg_static_scene_returns_clean_image
  + test_compose_max_shows_brightest_trail
  + test_compose_motion_highlights_changed_regions
  + test_compose_bucket_boundaries_respect_timestamps
  + test_compose_empty_session_returns_empty_list
  + test_compose_single_frame_bucket_falls_back_to_avg_for_motion
  + test_compose_bucket_s_clamped_to_minimum

tests/test_storage.py (extend)
  + test_cleanup_session_dir_also_removes_previews

tests/test_server.py (extend)
  + test_stop_recording_attaches_previews
  + test_compose_timeline_preview_tool_works
  + test_compose_timeline_preview_unknown_session_error
  + test_query_buffer_includes_previews_in_range
```

All new tests use `_FakeMSS` for capture (where needed) and small synthetic numpy arrays for compositing assertions — they verify blend math (e.g., "two frames of solid red + solid blue blended with `avg` produce purple") without depending on real recorded frames.

## Disk and performance

- Compositing 60 frames of 1920×1080×3 uint8: numpy mean/max/diff in ~50–80 ms, ~370 MB transient memory (released immediately). Stays well below typical system memory.
- JPEG preview size at q=85: ~200–400 KB per 1080p preview. 25 previews for a 25-second recording = 5–10 MB additional disk per session.
- Continuous buffer at 2 fps × 300 s = 600 frames → 300 bucket previews (bucket_s=1.0) = ~100 MB extra. Well under the 1 GB default cap.
- `stop_recording` now runs +100–200 ms on a typical 10-second recording. Acceptable given the token savings downstream.

## Success criteria

1. Suite 80+ tests green; mypy + ruff clean.
2. Manual smoke test: re-run the Windows Start menu test with Claude choosing fps=30, bucket_s=1.0, auto-composed previews. Claude reads ~5 preview images in the first dispatch, identifies the bucket containing the animation, reads ~30 raw frames from that bucket in the second dispatch. Total images passed to frame-analyzer ≤ 40. Visible animation-smoothness judgement recovered.
3. `stop_recording` latency on a 10-second recording increases by less than 200 ms.
4. Back-compat: skills that ignore `previews` (or encounter `items = []`) fall back to direct `frame_paths` dispatch and behave exactly as in Spec 1+2+3.
5. `query_buffer` response stays under 50 ms excluding compositing; compositing adds proportional to `(time_range_s / bucket_s)` buckets.

## What this spec does NOT change

- Spec 1 capture tools (`start_recording`, `stop_recording` signature, `list_frames`, `cleanup_session`) apart from the new `previews` field in the `stop_recording` return.
- Spec 2 continuous-mode tools (`start_continuous_buffer`, `stop_continuous_buffer`) — unchanged. `query_buffer` only grows a `previews` field.
- Spec 3 `region_dpr` — unchanged.
- `frame-analyzer` subagent — unchanged. It receives preview paths or raw frame paths; it reads them with `Read` as always.
- Hooks and `.mcp.json` — unchanged.

## Open questions for the implementation plan

None. All interface choices are locked. Remaining detail (exact numpy calls, exact preview filename padding, pytest fixtures for synthetic frames) is implementation-phase work.

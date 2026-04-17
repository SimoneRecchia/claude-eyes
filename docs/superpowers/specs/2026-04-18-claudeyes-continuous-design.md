# claudeEyes — Continuous Mode (Spec 2) Design

**Status:** approved for implementation on 2026-04-18.
**Branch:** `feat/foundation` (same branch as Spec 1 per user request).
**Precedent:** builds on Spec 1 / Foundation (on-demand recording + MCP server + `frame-analyzer` subagent + `analyze-screen` skill + hooks).

---

## Goal

Give Claude access to a **rolling screen buffer** that the user explicitly activates. When the user asks "what did I just do?", Claude queries the buffer for the relevant time window, dispatches the existing `frame-analyzer` subagent against a token-efficient sample of frames, and answers. The goal is near-realtime recall of recent screen activity at a fraction of the cost of true realtime analysis.

## Scope

- Record the screen continuously at low fps into a single rolling buffer.
- Keep frames for a bounded time window (retention) with a disk cap as safety net.
- Expose a query tool that returns an evenly-sampled subset of frames in a requested time range.
- Coexist with the existing on-demand recording mode without interference.

**Out of scope:**

- Chrome extension / DOM selector → bbox translation (Spec 3).
- Capture-time perceptual-hash dedupe (postponed; can be layered on later without interface changes).
- Any form of auto-start. The buffer starts only when the user asks for it.

## Design decisions (recap)

1. **Start/stop trigger:** explicit MCP tools `start_continuous_buffer(...)` / `stop_continuous_buffer()`. Claude calls them on explicit user request. The `SessionEnd` hook already wipes `sessions/`; the daemon thread dies with the MCP process on stdio close.
2. **Retention:** default `300 s` (5 min). Default disk cap `1024 MB`. Both overridable via env vars and tool params.
3. **Optimization:** server-side uniform-in-time sampling at query time via `max_frames` (default 30). No capture-time dedupe. Capture is "dumb".
4. **Coexistence with on-demand mode:** both run independently on separate session directories. A second `start_continuous_buffer` while one is active returns a structured error, never raises.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Claude Code                                                     │
│  - start_continuous_buffer (only on explicit user request)      │
│  - query_buffer → Task(frame-analyzer, sampled frames)          │
│  - stop_continuous_buffer                                        │
└──────────┬──────────────────────────────────┬──────────────────┘
           │ MCP stdio                        │ Task tool
           ▼                                  ▼
┌──────────────────────────────────────┐   ┌──────────────────────┐
│  claude_eyes MCP server               │   │  frame-analyzer      │
│  (Spec 1 tools + 3 new ones)         │   │  (unchanged)         │
│                                      │   └──────────────────────┘
│  NEW @mcp.tool:                      │
│  - start_continuous_buffer(          │
│      fps=2, retention_s=300,         │
│      resolution_scale=0.75)          │
│  - stop_continuous_buffer()          │
│  - query_buffer(                     │
│      time_range_s,                   │
│      max_frames=30)                  │
└──────────┬───────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────┐
│  NEW claude_eyes.continuous                                       │
│  - ContinuousHandle  (capture thread + cleanup thread + lock)    │
│  - start_continuous / stop_continuous                             │
│  - sample_frames(frames, max_frames)                              │
│                                                                  │
│  Frames → sessions/_continuous/ (reserved directory)             │
│  Rolling cleanup → prune by age (retention_s) + by disk cap      │
└──────────────────────────────────────────────────────────────────┘
```

## New MCP tools

```python
start_continuous_buffer(
    fps: int = 2,
    retention_s: int = 300,
    resolution_scale: float = 0.75,
) -> dict
#  success → { "active": True, "started_at": str, "config": { fps, retention_s,
#              resolution_scale, disk_cap_mb, monitor } }
#  already active → { "error": "continuous buffer already active",
#                     "started_at": str }

stop_continuous_buffer() -> dict
#  success → { "stopped": True, "frames_kept": int, "bytes_kept": int }
#  idle    → { "error": "no active continuous buffer" }

query_buffer(
    time_range_s: int,
    max_frames: int = 30,
) -> dict
#  success → { "frames": [{ path, index, timestamp_ms, age_s }, ...],
#              "total_in_range": int,          # before sampling
#              "oldest_frame_age_s": float,
#              "newest_frame_age_s": float,
#              "warning"?: "time_range_s exceeds buffer age; clamped to X s" }
#  idle    → { "error": "no active continuous buffer" }
#  empty   → { "frames": [], "total_in_range": 0 }
```

## Component changes

### New module `src/claude_eyes/continuous.py`

```
@dataclass
class ContinuousConfig:
    fps: int
    retention_s: int
    resolution_scale: float
    disk_cap_bytes: int
    monitor: int

@dataclass
class ContinuousHandle:
    capture_thread: Thread
    cleanup_thread: Thread
    stop_event: Event
    session_dir: Path
    started_monotonic: float
    started_at_iso: str
    config: ContinuousConfig

def start_continuous(...) -> ContinuousHandle
def stop_continuous(handle: ContinuousHandle) -> tuple[int, int]  # (frames_kept, bytes_kept)
def sample_frames(
    frames: list[FrameInfo],
    max_frames: int,
) -> list[FrameInfo]
# If len(frames) <= max_frames: returns the input unchanged.
# Otherwise: returns max_frames frames evenly spaced by index, always
# including frames[0] and frames[-1] (the oldest and newest in the
# requested range) when max_frames >= 2.
```

The capture thread reuses the pattern from `recorder._capture_loop`: monotonic clock, `stop_event.wait()` for throttling, fixed-step `next_tick += interval`, save via `storage.save_frame`.

The cleanup thread wakes every `CLEANUP_TICK_SECONDS` (= 5 s) via `stop_event.wait(CLEANUP_TICK_SECONDS)` and calls `storage.prune_by_age` then `storage.prune_by_size`. Both threads share the same `stop_event`, so `stop_continuous` brings them down together.

### Extensions to `src/claude_eyes/storage.py` (additive, non-breaking)

```python
def prune_by_age(session_dir: Path, max_age_ms: int, now_ms: int) -> int:
    """Remove frames whose timestamp_ms < now_ms - max_age_ms. Returns count removed."""

def prune_by_size(session_dir: Path, max_bytes: int) -> int:
    """If total size > max_bytes, remove oldest frames until under cap. Returns count removed."""

def frames_in_time_range(
    session_dir: Path,
    oldest_ts_ms: int,
    newest_ts_ms: int,
) -> list[FrameInfo]:
    """Return frames with timestamp_ms in [oldest, newest], sorted by timestamp."""
```

`prune_by_size` parses the index from the filename to walk oldest-first without full `stat()` per file beyond what's needed.

`save_frame`, `list_frames`, `cleanup_session_dir`, and `frame_filename` are **unchanged** — Spec 1 consumers are not touched.

### Changes to `src/claude_eyes/config.py`

New module-level constants:

```python
DEFAULT_CONTINUOUS_FPS = 2
DEFAULT_CONTINUOUS_RETENTION_S = 300
DEFAULT_CONTINUOUS_RESOLUTION_SCALE = 0.75
DEFAULT_CONTINUOUS_DISK_CAP_MB = 1024
DEFAULT_QUERY_MAX_FRAMES = 30
CONTINUOUS_SESSION_DIR_NAME = "_continuous"
CLEANUP_TICK_SECONDS = 5
```

`ServerConfig` grows four optional fields (all with defaults so no existing consumer breaks):

```python
continuous_fps: int = DEFAULT_CONTINUOUS_FPS
continuous_retention_s: int = DEFAULT_CONTINUOUS_RETENTION_S
continuous_resolution_scale: float = DEFAULT_CONTINUOUS_RESOLUTION_SCALE
continuous_disk_cap_mb: int = DEFAULT_CONTINUOUS_DISK_CAP_MB
```

`ServerConfig.from_env()` reads the corresponding env vars:
`CLAUDE_EYES_CONTINUOUS_FPS`, `CLAUDE_EYES_RETENTION_S`, `CLAUDE_EYES_CONTINUOUS_RESOLUTION_SCALE`, `CLAUDE_EYES_DISK_CAP_MB`.

### Changes to `src/claude_eyes/server.py`

Module-level state adds:

```python
_continuous_handle: ContinuousHandle | None = None
_continuous_lock: threading.Lock = threading.Lock()
```

Three new `@mcp.tool()` functions that operate on this state under `_continuous_lock`. The existing four tools (`start_recording`, `stop_recording`, `list_frames`, `cleanup_session`) are **not modified** in signature or behaviour — they continue to work on `sessions/sess_xxx/` dirs.

### New skill `.claude/skills/review-recent-activity/SKILL.md`

Trigger conditions only — no workflow summary in description:

```yaml
---
name: review-recent-activity
description: Use when the user asks about something they recently did on screen — "what did I just do", "cosa ho fatto", "riassumi gli ultimi N minuti", "cosa è successo nel buffer". Requires the continuous buffer to be active (user starts it explicitly).
---
```

Workflow (inside the skill body):
1. Check the buffer is active; if not, tell the user how to start it and stop.
2. Pick `time_range_s` from the user's phrasing ("just" → 60 s, "last minute" → 60, "last few minutes" → 180, etc.).
3. Call `mcp__claude_eyes__query_buffer(time_range_s, max_frames=30)`.
4. Dispatch `frame-analyzer` via `Task` with the returned frame paths + user's question.
5. Synthesize a direct answer. Do **not** call `cleanup_session` — the continuous buffer is not a regular session.

The existing `analyze-screen` skill is **unchanged**; it continues to be the right tool for on-demand animation / UI-transition analysis. Descriptions are intentionally non-overlapping.

### Hooks

Add one `PostToolUse` matcher on `mcp__claude_eyes__start_continuous_buffer`:

```json
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
```

The new hook logs the event and injects an `additionalContext` reminder to Claude that **the user's screen is now being recorded continuously** and Claude must inform the user clearly in its next response. This is the privacy guardrail.

The existing `SessionEnd` cleanup hook already handles `sessions/_continuous/` — no change.

### `CLAUDE.md` updates

Add a "Continuous mode" section at the end with two hard rules:
1. **Never start the buffer on your own.** It begins only when the user explicitly asks ("parti col buffer", "attiva la registrazione continua", "record in background").
2. **Always tell the user when the buffer starts and stops.** They must know their screen is being captured.

Plus: brief guidance that `review-recent-activity` skill is the entry point for "what did I do" questions, while `analyze-screen` stays for on-demand animation analysis.

## Edge cases

| Case | Behaviour |
|---|---|
| `start_continuous_buffer` when already active | Structured error with the existing `started_at`. No double-start. |
| `stop_continuous_buffer` when idle | Structured error; no raise. |
| `query_buffer` when idle | Structured error; no raise. |
| `query_buffer` with `time_range_s > retention` | Return what exists + `warning` field describing the clamp. |
| `query_buffer` with `max_frames >= total_in_range` | Return all frames, no sampling. |
| `query_buffer` on empty buffer (just started) | Return `{ "frames": [], "total_in_range": 0 }` without error. |
| Write failure (disk full, permission) during capture | Log to stderr, skip the frame, loop continues. Don't crash the thread. |
| Race: cleanup vs capture | Cleanup derives its reference time from the newest frame's `timestamp_ms` (parsed from the filename) and keeps a 1-second grace window, never deleting frames whose `timestamp_ms` is within the last 1000 ms. Filenames are unique by `(index, timestamp_ms)`, so no collision even if the two threads race. |
| MCP server restart | Buffer is volatile. `_continuous/` is wiped on SessionEnd or on the next `start_continuous_buffer` call. No reattach. |
| Thread deadlock on stop | `stop_event.set()` + `thread.join(timeout=5)` on each thread; after timeout, log a warning and return. Daemon threads die with the process anyway. |

## Concurrency control

- A single `_continuous_handle` at module scope, guarded by `_continuous_lock`. Start/stop are atomic with respect to each other.
- The capture and cleanup threads share one `stop_event`, so stopping is atomic across both.
- File-system operations require no lock: the cleanup grace window (`now - 1 s`) plus unique filenames means the two threads never touch the same file.

## Safety

- **Daemon threads:** both threads are `daemon=True` so an MCP process crash or Claude Code exit cleanly terminates them.
- **Hook privacy guardrail:** `log_continuous_start.py` injects a reminder into Claude's context the moment the buffer starts.
- **Hard cap on runtime:** no explicit timeout — the buffer is user-controlled. The disk cap is the only self-limiting behaviour.
- **`CLAUDE.md` rule:** Claude must never start the buffer on its own. This is enforced by skill description and CLAUDE.md guidance, not by code (code-level enforcement is impossible in an MCP tool model).

## Testing strategy

New tests (targeting ~10 additions, suite goes from 35 → ~45):

```
tests/test_storage.py (extend)
  + test_prune_by_age_removes_only_old_frames
  + test_prune_by_size_removes_oldest_first
  + test_frames_in_time_range_filters_correctly

tests/test_continuous.py (new)
  + test_continuous_captures_and_cleanup_works  (fake mss, short run)
  + test_continuous_stops_cleanly
  + test_continuous_prunes_by_age
  + test_sample_frames_uniform_distribution
  + test_sample_frames_returns_all_when_under_max

tests/test_server.py (extend)
  + test_start_continuous_rejects_double_start
  + test_stop_continuous_rejects_when_idle
  + test_query_buffer_returns_sampled_frames
  + test_query_buffer_time_range_cap
  + test_continuous_and_on_demand_coexist
```

All tests reuse `_FakeMSS` from `tests/test_recorder.py`. Timing-sensitive tests use short sleeps (< 1 s) and tolerant bounds to avoid flakiness.

## Success criteria

1. 5-minute real capture at 2 fps + default scale stays under 200 MB on disk (well under the 1 GB cap).
2. `query_buffer(300, 30)` returns within ~50 ms (I/O only, no analysis).
3. `frame-analyzer` subagent processes 30 frames in a single turn (validated in Spec 1).
4. Starting on-demand `start_recording(fps=10)` while the buffer is active completes without errors; frames never mix between `sessions/_continuous/` and `sessions/sess_xxx/`.
5. Hook reminder fires on `start_continuous_buffer` and Claude informs the user in the next response.

## What this spec does NOT change

- Spec 1 four MCP tools (`start_recording`, `stop_recording`, `list_frames`, `cleanup_session`) — signatures and behaviour untouched.
- `frame-analyzer` subagent — no changes.
- `analyze-screen` skill — no changes.
- `recorder.py` — no changes (continuous capture reuses the pattern but lives in `continuous.py`).
- Session registry (`SessionRegistry`) — not used by the continuous buffer; the buffer's `_continuous/` directory is a singleton, not a registry entry.

## Open questions for the implementation plan

None. All interface decisions are locked. Remaining choices (concrete test assertions, exact sleep durations, specific mypy annotations) are implementation detail for the planning phase.

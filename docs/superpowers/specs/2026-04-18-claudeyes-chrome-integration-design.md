# claudeEyes × Claude-in-Chrome Integration (Spec 3) Design

**Status:** approved for implementation on 2026-04-18.
**Branch:** `feat/foundation` (same branch as Spec 1 + Spec 2, continuous).
**Precedent:** builds on Spec 1 (on-demand recording + 4 MCP tools + `frame-analyzer` subagent + `analyze-screen` skill) and Spec 2 (continuous rolling buffer + `review-recent-activity` skill).

---

## Goal

Let Claude capture **timing-perfect video** (not a single screenshot) of a visual behaviour happening inside a Chrome page, by orchestrating the existing `Claude-in-Chrome` MCP server with the existing `claude_eyes` MCP server through a dedicated Claude skill. No new Chrome extension, no fork of Anthropic's extension. Thin Python patch for DPR, one new skill, one documentation update.

## Scope

- Add a `region_dpr: float = 1.0` parameter to `start_recording` and `start_continuous_buffer` so browser-reported CSS-pixel bboxes convert cleanly to physical-pixel capture regions.
- Write a new skill `analyze-page-animation` that orchestrates Claude-in-Chrome + claudeEyes with six ready-to-use patterns for common scenarios, plus a fallback decision tree for exotic cases.
- Update `CLAUDE.md` with a "Using claudeEyes with Claude-in-Chrome" section to disambiguate when to use which skill.
- Cross-link the three skills (`analyze-screen`, `review-recent-activity`, `analyze-page-animation`) in each other's descriptions.

**Out of scope:**

- A new Chrome extension or any modification to Anthropic's `Claude-in-Chrome` extension.
- Capture-time dedupe / perceptual hashing (still postponed from Spec 2).
- Frame-diff artefact for the subagent (rejected earlier: marginal gain, real complexity).
- Drag-and-drop and complex gestural interactions (handled by the skill's fallback, not promoted to a pattern).

## Design decisions (recap)

1. **Orchestration-only integration.** Claude drives both MCP servers from a single skill. Neither server imports the other. Claude-in-Chrome handles DOM / navigation / input; claudeEyes handles capture.
2. **DPR handled server-side.** The browser reports CSS pixels; `mss` captures physical pixels. Claude queries `window.devicePixelRatio` once, passes it as `region_dpr`, the recorder scales internally. Consumers not using Chrome don't need to know about it.
3. **Skill teaches timing-perfect capture.** The skill provides a library of six patterns (click + CSS, scroll reveal, hover, form submit, page-load, media playback) with verbatim JS snippets. Each snippet ends with an `await` on a precise completion signal so `stop_recording` fires at the exact right moment — no wasted frames before or after.
4. **Fallback decision tree** when no pattern matches (canvas, requestAnimationFrame loops, custom JS). Inspect → classify → pick timing strategy (event, polling, ask user).
5. **Safety cap everywhere.** Every JS snippet includes a 15-second `setTimeout` safety resolve, and the skill instructs Claude to also cap the recording via its own logic.
6. **Pre-roll 200–300 ms** between `start_recording` and the trigger JS, so the captured video includes the pre-animation state.

## Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│  Claude Code                                                             │
│  Skill: analyze-page-animation                                           │
│    - classifies target, picks pattern                                    │
│    - fetches bbox + DPR + window offsets via Claude-in-Chrome JS         │
│    - orchestrates start_recording → trigger → await → stop               │
│    - dispatches frame-analyzer subagent, synthesizes answer              │
└───────────────┬────────────────────────────────────────┬────────────────┘
                │ MCP stdio                              │ MCP stdio
                ▼                                        ▼
┌──────────────────────────────────┐        ┌────────────────────────────┐
│  Claude-in-Chrome MCP server     │        │  claude_eyes MCP server    │
│  (unchanged — Anthropic official)│        │  (Spec 1+2 tools + region_ │
│  - javascript_tool               │        │   dpr param on two tools)  │
│  - computer / find               │        │                            │
│  - navigate / tabs / read_page   │        │                            │
└──────────────────────────────────┘        └────────────────────────────┘
```

## Tool signature changes

```python
# src/claude_eyes/server.py — start_recording gets one new param
start_recording(
    fps: int = 3,
    resolution_scale: float = 1.0,
    region: tuple[int, int, int, int] | None = None,
    region_dpr: float = 1.0,                        # NEW
    session_name: str | None = None,
) -> dict
```

`start_continuous_buffer` does **not** gain `region_dpr` in this spec — the continuous buffer has no `region` param today (it always captures the full virtual screen), so scaling would have nothing to operate on. When a future spec introduces `region` on the continuous buffer, `region_dpr` follows the same shape as on `start_recording`.

Behaviour:

- `region_dpr = 1.0` (default) → no scaling, back-compat.
- `region_dpr > 1.0` → each of `(x, y, w, h)` in `region` is multiplied by `region_dpr` before being passed to `mss` / the capture loop.
- Applied inside the capture loop (`recorder._capture_loop`, `continuous._capture_loop`) once, before the target dict is built.
- Ignored when `region is None` (no-op).
- Clamped to `[0.1, 4.0]` defensively to avoid absurd values.

## Component changes

### `src/claude_eyes/recorder.py`

`start_recorder(..., region_dpr: float = 1.0)` — new keyword-only param. Inside `_capture_loop`, when `region is not None`, scale each coordinate by `region_dpr` (rounded to int, min 1) before building `{"left", "top", "width", "height"}`.

### `src/claude_eyes/continuous.py`

Unchanged in this spec. The continuous buffer's capture loop doesn't accept a `region`, so `region_dpr` has no effect there. The day a future spec introduces `region` on the continuous buffer, the same `region_dpr` param lands alongside it.

### `src/claude_eyes/server.py`

Only `start_recording` gains the new parameter. It forwards `region_dpr` to `start_recorder`. `start_continuous_buffer` is untouched.

### Tests

`tests/test_recorder.py` adds one test:

```python
def test_recorder_applies_region_dpr(tmp_path: Path, fake_mss: None) -> None:
    """region (100, 50, 200, 80) at DPR 1.5 must grab (150, 75, 300, 120)."""
```

The test uses a `_FakeMSS` that records the `monitor` arg to `.grab()` and asserts the scaled values.

### New skill `.claude/skills/analyze-page-animation/SKILL.md`

Trigger-only description, no workflow summary (writing-skills rule):

```yaml
---
name: analyze-page-animation
description: Use when the user is on a Chrome page (via Claude-in-Chrome) and asks to analyze a time-based visual behaviour — "cosa succede quando clicco", "l'animazione è fluida", "c'è un glitch nella transizione", "mostrami il reveal on scroll", "la modal appare male". Captures a timing-perfect video (not a single screenshot) around the triggering action.
---
```

The body covers:

1. **When to use / when NOT to use** (disambiguation with `analyze-screen` and `review-recent-activity`).
2. **Step 0 — inspect target** (fetch bbox, DPR, window offsets, scroll-into-view if needed). JS snippet provided verbatim.
3. **Pattern library** (six patterns). For each: trigger shape, JS snippet, FPS recommendation.
4. **Fallback decision tree** when no pattern matches.
5. **Orchestration recipe** (`start_recording` → `sleep(pre_roll)` → trigger JS → `stop_recording` → `Task(frame-analyzer)` → `cleanup_session`).
6. **FPS heuristics** (short/medium/long tables).
7. **Error handling** (selector missing, event never fires, DPR weird, window off-screen).
8. **Common mistakes** block.

#### Pattern library

Each pattern has three pieces: name, JS snippet, FPS default.

- **Pattern 1 — Click + CSS transition/animation.** `transitionend` / `animationend` listener, safety timeout, `click()`.
- **Pattern 2 — Scroll-triggered reveal.** `IntersectionObserver` + `scrollIntoView({ behavior: 'smooth', block: 'center' })`, then `transitionend` if any.
- **Pattern 3 — Hover.** Instructs Claude to dispatch a **real** mouse move via `mcp__Claude_in_Chrome__computer` (synthetic `mouseenter` does not trigger CSS `:hover`). The JS awaits `transitionend`.
- **Pattern 4 — Form submit feedback (AJAX forms only).** `form.requestSubmit()` + `animationend` / `transitionend` on the feedback target. Explicit note: for navigating forms, use Pattern 5 on the landing page.
- **Pattern 5 — Page-load / initial render.** After `mcp__Claude_in_Chrome__navigate`, wait for `load` + 500 ms buffer. Suitable for hero animations, route transitions.
- **Pattern 6 — Media playback.** `<video>` / `<audio>`: set `currentTime = 0`, `play()`, await `ended`.

#### Fallback decision tree

When none match, the skill instructs Claude to:

1. Call `mcp__Claude_in_Chrome__javascript_tool` with inspection JS — read `getComputedStyle().transitionDuration`, `.animationName`, tag name.
2. If tag is `<canvas>` or `<video>`: time-based cap; ask the user for expected duration if longer than 5 s.
3. If no CSS signal: poll `getBoundingClientRect()` every 50 ms; stop when the six values (x, y, w, h, and computed opacity/background-color hash) are identical for three consecutive ticks (≥ 150 ms stable).
4. If the user's description is too vague: ask for expected duration + a characterising frame ("un click", "lo scroll", "la modal che appare") and re-classify.
5. Always keep a 20-second absolute safety cap on the recording.

#### Orchestration recipe

```
# Pseudocode the skill recipe writes out
region_info = javascript_tool(<STEP 0 snippet>)
if region_info.bbox offscreen after scroll:
    fallback to region=None (full screen)
physical_bbox = compute_screen_bbox(region_info)
session = start_recording(region=physical_bbox, region_dpr=region_info.dpr, fps=chosen_fps)
sleep(200ms)
result = javascript_tool(<PATTERN N trigger snippet>)  # blocks until await resolves
frames = stop_recording(session.id)
report = Task(frame-analyzer, prompt=<user question + frame paths>)
cleanup_session(session.id)
return synthesize(report)
```

#### JS helper for Step 0

```js
const el = document.querySelector('<TARGET>');
if (!el) throw new Error('target selector not found');
const r = el.getBoundingClientRect();
if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) {
  el.scrollIntoView({ block: 'center', inline: 'center' });
  // ~300ms settle
  await new Promise(res => setTimeout(res, 300));
}
const r2 = el.getBoundingClientRect();
return {
  bbox_css: [Math.round(r2.left), Math.round(r2.top), Math.round(r2.width), Math.round(r2.height)],
  dpr: window.devicePixelRatio,
  window_screen_xy: [window.screenX, window.screenY],
  chrome_ui_top: window.outerHeight - window.innerHeight,
  chrome_side_border: Math.max(0, (window.outerWidth - window.innerWidth) / 2),
};
```

Claude converts to physical pixels:

```
screen_x_css = window_screen_xy[0] + chrome_side_border + bbox_css[0]
screen_y_css = window_screen_xy[1] + chrome_ui_top      + bbox_css[1]
physical_bbox = (
    round(screen_x_css * dpr),
    round(screen_y_css * dpr),
    round(bbox_css[2] * dpr),
    round(bbox_css[3] * dpr),
)
```

**Simplification opt-out:** if this math looks brittle (multi-monitor, odd window placement), the skill tells Claude to fall back to `region=None` and accept full-screen capture.

### CLAUDE.md update

New section **`## Using claudeEyes with Claude-in-Chrome`** inserted immediately before `## Related files`. Content:

- When on a Chrome page, prefer `analyze-page-animation` over `analyze-screen` for time-based visual questions.
- Never use Claude-in-Chrome's `computer`/screenshot tool for time-based analysis — it's a single frame. Use claudeEyes.
- The continuous buffer is still the right tool for "what did I just do" on any app (Chrome or not) — route through `review-recent-activity`.

### Skill cross-links

- `analyze-screen` description gains a one-liner: "For Chrome pages, prefer `analyze-page-animation` which handles DOM selectors and timing-perfect triggering."
- `review-recent-activity` description gains a one-liner: "For a targeted, on-demand capture of a single Chrome animation (not the whole buffer), prefer `analyze-page-animation`."

## Edge cases

| Case | Handling |
|---|---|
| Selector missing | JS throws; Claude surfaces the error, asks user for the correct selector. |
| Animation event never fires | 15 s safety timeout + 20 s recording cap; Claude reports the cap hit. |
| Target off-screen | `scrollIntoView` + 300 ms settle before re-reading bbox. |
| Multi-monitor Chrome window | `window.screenX`/`Y` are monitor-absolute in Chrome 111+; fallback full-screen if the math looks wrong. |
| Extremely high DPR (>3) | `region_dpr` is clamped to `[0.1, 4.0]`; Claude warned via docstring. |
| User asks about a whole flow (multiple animations) | Skill suggests either running on-demand multiple times OR starting the continuous buffer and using `review-recent-activity`. |
| Synthetic hover does not trigger `:hover` | Pattern 3 explicitly routes through `mcp__Claude_in_Chrome__computer` for a real pointer move. |
| Navigating form | Pattern 4 is marked AJAX-only; for navigating forms the skill points to Pattern 5 on the destination page. |

## Testing strategy

Additions only:

```
tests/test_recorder.py (extend)
  + test_recorder_applies_region_dpr          (scales bbox via fake mss)
  + test_recorder_region_dpr_default_is_noop  (dpr=1.0 passes bbox unchanged)
  + test_recorder_region_dpr_clamped          (dpr=5.0 clamped to 4.0)

tests/test_server.py (extend)
  + test_start_recording_forwards_region_dpr  (end-to-end via patched server)
```

Total new tests: ~4. Suite goes from 64 → ~68.

No tests for the skill itself (it's a markdown document — would need live browser + real animations to test; out of scope). Manual verification in real Chrome page is Task 7 of the plan.

## Success criteria

1. Full suite green (~68 tests, mypy clean, ruff clean).
2. Manual smoke on a real Chrome page with a CSS animation: Claude classifies correctly, picks fps, records timing-perfect, report arrives.
3. Manual smoke on a Retina / 150%-scaled display: `region_dpr` handles DPR correctly — frame contents show the intended element, not an offset region.
4. Regression: running `analyze-screen` (desktop, non-Chrome) still works without any Chrome tools present.

## What this spec does NOT change

- Spec 1 four MCP tools — signatures unchanged except the new optional `region_dpr` on `start_recording`.
- Spec 2 three continuous-mode tools — unchanged (`region_dpr` deferred until continuous gets a `region` param).
- `frame-analyzer` subagent — unchanged.
- `analyze-screen` and `review-recent-activity` skills — only a description tweak each for cross-linking.
- Hooks and `.mcp.json` — unchanged.

## Open questions for the implementation plan

None. All interface decisions are locked. Details for the plan: exact code for `region_dpr` in both loops, exact skill markdown including the six JS snippets, exact CLAUDE.md insertion text, exact test assertions.

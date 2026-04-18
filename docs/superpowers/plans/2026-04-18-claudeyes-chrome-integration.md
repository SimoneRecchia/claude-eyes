# claudeEyes × Claude-in-Chrome Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the thin orchestration layer between `claude_eyes` and `Claude-in-Chrome` — one Python parameter (`region_dpr` on `start_recording`), one new skill (`analyze-page-animation`), CLAUDE.md and two existing skill descriptions updated to cross-link.

**Architecture:** No new MCP server, no new Chrome extension. Claude drives both existing MCP servers via a dedicated skill that provides six ready-to-use patterns plus a fallback decision tree for Chrome-page animation analysis. A `region_dpr` parameter lets browser-reported CSS-pixel bboxes convert to physical-pixel capture regions via a single scalar multiplier inside `mss.grab`.

**Tech Stack:** Python 3.13, `mcp>=1.0`, `mss>=9.0`, `Pillow>=10.0`, `pytest`. No new dependencies. Skill is Markdown + inline JavaScript snippets.

**Prerequisite:** Spec 1 + Spec 2 are landed on `feat/foundation` (64 tests green, mypy clean, ruff clean). Spec 3 design is at `docs/superpowers/specs/2026-04-18-claudeyes-chrome-integration-design.md`.

---

## File structure

```
src/claude_eyes/
├── recorder.py       # Task 1 — region_dpr in _capture_loop + start_recorder
└── server.py         # Task 2 — region_dpr on start_recording MCP tool

tests/
├── test_recorder.py  # Task 1 — extend _FakeMSS to record grabbed monitors + dpr tests
└── test_server.py    # Task 2 — test dpr forwards through MCP tool

.claude/
├── skills/
│   ├── analyze-page-animation/SKILL.md   # Task 3 — NEW
│   ├── analyze-screen/SKILL.md           # Task 5 — description cross-link
│   └── review-recent-activity/SKILL.md   # Task 5 — description cross-link

CLAUDE.md            # Task 4 — new section "Using claudeEyes with Claude-in-Chrome"
```

---

## Task 1: `region_dpr` on the recorder

**Files:**
- Modify: `src/claude_eyes/recorder.py`
- Modify: `tests/test_recorder.py`

- [ ] **Step 1: Extend `_FakeMSS` in `tests/test_recorder.py` to record grabbed monitors**

Modify the existing `_FakeMSS` class so it tracks each instance and every `grab` call. Existing tests continue to pass because they don't touch the new attributes.

Replace the current `_FakeMSS` class (keep `_FakeScreenshot` unchanged) with:

```python
class _FakeMSS:
    """Context-manager replacement for `mss.mss()` that records grab calls."""

    instances: list["_FakeMSS"] = []

    def __init__(self) -> None:
        self.monitors = [
            {"left": 0, "top": 0, "width": 8, "height": 8},
            {"left": 0, "top": 0, "width": 8, "height": 8},
        ]
        self.grabbed: list[dict] = []
        _FakeMSS.instances.append(self)

    def __enter__(self) -> "_FakeMSS":
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def grab(self, monitor: dict) -> _FakeScreenshot:
        self.grabbed.append(dict(monitor))
        return _FakeScreenshot()
```

- [ ] **Step 2: Append three failing tests to `tests/test_recorder.py`**

```python
def test_recorder_region_dpr_default_is_noop(tmp_path: Path, fake_mss: None) -> None:
    """Without region_dpr (default 1.0), region is passed through unchanged."""
    from claude_eyes.recorder import start_recorder, stop_recorder

    _FakeMSS.instances.clear()
    handle = start_recorder(
        session_dir=tmp_path / "rec_dpr_1",
        fps=10,
        resolution_scale=1.0,
        region=(10, 20, 30, 40),
        monitor_index=0,
    )
    time.sleep(0.3)
    stop_recorder(handle)

    grabbed = _FakeMSS.instances[-1].grabbed
    assert grabbed, "expected at least one grab"
    assert grabbed[0] == {"left": 10, "top": 20, "width": 30, "height": 40}


def test_recorder_applies_region_dpr(tmp_path: Path, fake_mss: None) -> None:
    """region (100, 50, 200, 80) at DPR 1.5 must grab (150, 75, 300, 120)."""
    from claude_eyes.recorder import start_recorder, stop_recorder

    _FakeMSS.instances.clear()
    handle = start_recorder(
        session_dir=tmp_path / "rec_dpr_15",
        fps=10,
        resolution_scale=1.0,
        region=(100, 50, 200, 80),
        monitor_index=0,
        region_dpr=1.5,
    )
    time.sleep(0.3)
    stop_recorder(handle)

    grabbed = _FakeMSS.instances[-1].grabbed
    assert grabbed, "expected at least one grab"
    assert grabbed[0] == {"left": 150, "top": 75, "width": 300, "height": 120}


def test_recorder_region_dpr_clamped_high(tmp_path: Path, fake_mss: None) -> None:
    """DPR > 4.0 is clamped to 4.0."""
    from claude_eyes.recorder import start_recorder, stop_recorder

    _FakeMSS.instances.clear()
    handle = start_recorder(
        session_dir=tmp_path / "rec_dpr_5",
        fps=10,
        resolution_scale=1.0,
        region=(100, 100, 100, 100),
        monitor_index=0,
        region_dpr=5.0,
    )
    time.sleep(0.3)
    stop_recorder(handle)

    grabbed = _FakeMSS.instances[-1].grabbed
    assert grabbed, "expected at least one grab"
    assert grabbed[0] == {"left": 400, "top": 400, "width": 400, "height": 400}
```

- [ ] **Step 3: Run the tests to confirm RED**

```bash
.venv/Scripts/python.exe -m pytest tests/test_recorder.py -v
```
Expected: three new tests fail with `TypeError: start_recorder() got an unexpected keyword argument 'region_dpr'` (default-is-noop test currently passes because default dpr doesn't exist yet — it will still be green post-change, leaving two failing).

Interpret carefully: if `test_recorder_region_dpr_default_is_noop` already passes (because `start_recorder` currently ignores a keyword arg — it won't, it'll raise), that's fine. The two `region_dpr`-using tests must fail to confirm true RED.

- [ ] **Step 4: Implement `region_dpr` in `src/claude_eyes/recorder.py`**

Replace the `_capture_loop` signature + region-handling block and the `start_recorder` signature + thread kwargs. Exact change:

In `_capture_loop`, add `region_dpr` to the keyword-only params and apply the scale before building `target`:

```python
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
    region_dpr: float = 1.0,
) -> None:
    interval = 1.0 / fps
    next_tick = started_monotonic
    dpr = max(0.1, min(4.0, region_dpr))  # defensive clamp

    with mss.mss() as sct:
        if region is not None:
            x, y, w, h = region
            if dpr != 1.0:
                x = int(round(x * dpr))
                y = int(round(y * dpr))
                w = max(1, int(round(w * dpr)))
                h = max(1, int(round(h * dpr)))
            target = {"left": x, "top": y, "width": w, "height": h}
        else:
            target = sct.monitors[monitor_index]

        while not stop_event.is_set():
            # ... (rest of the existing loop body — unchanged)
```

(Keep the entire body of the while-loop exactly as it was.)

In `start_recorder`, add `region_dpr` to the keyword-only args and forward it:

```python
def start_recorder(
    *,
    session_dir: Path,
    fps: int,
    resolution_scale: float,
    region: tuple[int, int, int, int] | None,
    monitor_index: int,
    region_dpr: float = 1.0,
) -> RecorderHandle:
    session_dir.mkdir(parents=True, exist_ok=True)
    stop_event = threading.Event()
    counter: list[int] = [0]
    started = time.monotonic()
    thread = threading.Thread(
        target=_capture_loop,
        kwargs={
            "stop_event": stop_event,
            "session_dir": session_dir,
            "fps": fps,
            "resolution_scale": resolution_scale,
            "region": region,
            "monitor_index": monitor_index,
            "frames_counter": counter,
            "started_monotonic": started,
            "region_dpr": region_dpr,
        },
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
```

- [ ] **Step 5: Run tests to confirm GREEN**

```bash
.venv/Scripts/python.exe -m pytest tests/test_recorder.py -v
```
Expected: all prior recorder tests + 3 new DPR tests pass. Full suite:

```bash
.venv/Scripts/python.exe -m pytest -q
```
Expected: 67 passed (64 prior + 3 new).

- [ ] **Step 6: Commit**

```bash
git add src/claude_eyes/recorder.py tests/test_recorder.py
git commit -m "feat(recorder): add region_dpr param to scale CSS-pixel bboxes"
```

---

## Task 2: `region_dpr` on the `start_recording` MCP tool

**Files:**
- Modify: `src/claude_eyes/server.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Append failing test to `tests/test_server.py`**

```python
def test_start_recording_forwards_region_dpr(patched_server, tmp_path: Path) -> None:
    """Region passed to the tool is scaled by region_dpr before hitting mss."""
    from tests.test_recorder import _FakeMSS

    _FakeMSS.instances.clear()
    result = patched_server.start_recording(
        fps=10,
        resolution_scale=1.0,
        region=(10, 20, 30, 40),
        region_dpr=2.0,
        session_name="dpr_smoke",
    )
    sid = result["session_id"]
    time.sleep(0.3)
    patched_server.stop_recording(sid)

    grabbed = _FakeMSS.instances[-1].grabbed
    assert grabbed, "expected at least one grab"
    assert grabbed[0] == {"left": 20, "top": 40, "width": 60, "height": 80}

    patched_server.cleanup_session(sid)
```

- [ ] **Step 2: Run the test to confirm RED**

```bash
.venv/Scripts/python.exe -m pytest tests/test_server.py::test_start_recording_forwards_region_dpr -v
```
Expected: fail with `TypeError: start_recording() got an unexpected keyword argument 'region_dpr'`.

- [ ] **Step 3: Add `region_dpr` to `start_recording` in `src/claude_eyes/server.py`**

Find the existing `start_recording` tool function and:

- Add `region_dpr: float = 1.0` to its signature (between `region` and `session_name`, to keep chronological parameter order matching the design doc).
- Pass it to `start_recorder` as a keyword arg.
- Surface it in the returned `config` dict so Claude sees the exact value that was applied.

Exact final function:

```python
@mcp.tool()
def start_recording(
    fps: int = DEFAULT_FPS,
    resolution_scale: float = DEFAULT_RESOLUTION_SCALE,
    region: tuple[int, int, int, int] | None = None,
    region_dpr: float = 1.0,
    session_name: str | None = None,
) -> dict[str, Any]:
    """Begin a new screen recording session.

    Returns a ``session_id`` used for every subsequent call. The session
    folder is created under the configured ``sessions_dir``. If ``region`` is
    given, ``region_dpr`` multiplies its coordinates before capture — use it
    when the region was computed in CSS pixels (e.g., from a browser) but the
    screen is captured in physical pixels (high-DPI / OS scaling).
    """
    session = RecordingSession.create(
        name=session_name or "",
        fps=fps,
        resolution_scale=resolution_scale,
        region=region,
        monitor=_config.monitor,
        include_cursor=_config.include_cursor,
        sessions_dir=_config.sessions_dir,
    )
    handle = start_recorder(
        session_dir=Path(session.frames_dir),
        fps=fps,
        resolution_scale=resolution_scale,
        region=session.region,
        monitor_index=_config.monitor,
        region_dpr=region_dpr,
    )
    _active[session.session_id] = handle
    _registry.add(session)
    return {
        "session_id": session.session_id,
        "started_at": session.started_at,
        "config": {
            "fps": fps,
            "resolution_scale": resolution_scale,
            "region": list(session.region) if session.region else None,
            "region_dpr": region_dpr,
            "monitor": _config.monitor,
            "include_cursor": _config.include_cursor,
        },
    }
```

- [ ] **Step 4: Run the test to confirm GREEN**

```bash
.venv/Scripts/python.exe -m pytest tests/test_server.py -v
```
Expected: all prior server tests + 1 new test pass. Full suite:

```bash
.venv/Scripts/python.exe -m pytest -q
```
Expected: 68 passed.

- [ ] **Step 5: Commit**

```bash
git add src/claude_eyes/server.py tests/test_server.py
git commit -m "feat(server): expose region_dpr on start_recording MCP tool"
```

---

## Task 3: `analyze-page-animation` skill

**Files:**
- Create: `.claude/skills/analyze-page-animation/SKILL.md`

- [ ] **Step 1: Create the directory and the SKILL file**

Create the parent directory first (Windows bash):

```bash
mkdir -p .claude/skills/analyze-page-animation
```

- [ ] **Step 2: Write `.claude/skills/analyze-page-animation/SKILL.md` with the full content below**

```markdown
---
name: analyze-page-animation
description: Use when the user is on a Chrome page (via Claude-in-Chrome) and asks to analyze a time-based visual behaviour — "cosa succede quando clicco", "l'animazione è fluida", "c'è un glitch nella transizione", "mostrami il reveal on scroll", "la modal appare male". Captures a timing-perfect video (not a single screenshot) around the triggering action.
---

# analyze-page-animation

Coordinates Claude-in-Chrome (DOM, navigation, input) with claudeEyes (video capture) so a time-based visual behaviour on a Chrome page is recorded exactly around the action that produces it — no wasted frames before the trigger, no frames after the animation ends.

## When to use

**Use when** the user is on a Chrome page and the question requires seeing a behaviour that unfolds over time: animations, transitions, reveal-on-scroll, hover effects, form-submit feedback, media playback, page-entry renders.

**Do NOT use when:**

- A single screenshot answers the question → use Claude-in-Chrome's native screenshot.
- The user is NOT in a Chrome page (desktop app, OS UI) → use `analyze-screen`.
- The user is asking about recent past activity recorded by the rolling buffer → use `review-recent-activity`.

## Step 0 — Inspect the target element

Before choosing a pattern, run a short inspection JS via `mcp__Claude_in_Chrome__javascript_tool` to fetch the bounding box, DPR, and Chrome window offsets. The snippet also scrolls the element into view if needed.

```js
const el = document.querySelector('<TARGET_SELECTOR>');
if (!el) throw new Error('target selector not found');
let r = el.getBoundingClientRect();
if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) {
  el.scrollIntoView({ block: 'center', inline: 'center' });
  await new Promise(res => setTimeout(res, 300));
  r = el.getBoundingClientRect();
}
return {
  bbox_css: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)],
  dpr: window.devicePixelRatio,
  window_screen_xy: [window.screenX, window.screenY],
  chrome_ui_top: window.outerHeight - window.innerHeight,
  chrome_side_border: Math.max(0, (window.outerWidth - window.innerWidth) / 2),
};
```

Convert the result to screen-absolute, physical-pixel coordinates:

```
screen_x_css = window_screen_xy[0] + chrome_side_border + bbox_css[0]
screen_y_css = window_screen_xy[1] + chrome_ui_top      + bbox_css[1]
physical_x   = round(screen_x_css * dpr)
physical_y   = round(screen_y_css * dpr)
physical_w   = round(bbox_css[2]  * dpr)
physical_h   = round(bbox_css[3]  * dpr)
```

Pass `region=(physical_x, physical_y, physical_w, physical_h)` and `region_dpr=1.0` to `start_recording`. (The math is already in physical pixels, so no further scaling.)

**Opt-out:** if the window position looks off (multi-monitor edge, odd DPI), pass `region=None` and accept full-screen capture.

## Pattern library

Pick the pattern whose trigger shape matches the user's description. If none matches, go to the fallback section.

### Pattern 1 — Click + CSS transition/animation

Use when a click starts a CSS `transition` or `animation` on a target element.

```js
const trigger = document.querySelector('<TRIGGER_SELECTOR>');
const target  = document.querySelector('<TARGET_SELECTOR>');
if (!trigger || !target) throw new Error('selector not found');
await new Promise((resolve) => {
  const done = () => resolve();
  target.addEventListener('transitionend', done, { once: true });
  target.addEventListener('animationend',  done, { once: true });
  setTimeout(done, 15000);
  trigger.click();
});
return { ok: true };
```

Default FPS: 20 (see heuristics below).

### Pattern 2 — Scroll-triggered reveal

Use when scrolling an element into view causes an animation (fade-in, slide-in, AOS-style).

```js
const target = document.querySelector('<TARGET_SELECTOR>');
if (!target) throw new Error('target selector not found');
await new Promise((resolve) => {
  let settled = false;
  const io = new IntersectionObserver((entries) => {
    if (entries[0].isIntersecting && !settled) {
      settled = true;
      target.addEventListener('transitionend', resolve, { once: true });
      setTimeout(resolve, 3000);
    }
  });
  io.observe(target);
  setTimeout(resolve, 15000);
  target.scrollIntoView({ behavior: 'smooth', block: 'center' });
});
return { ok: true };
```

Default FPS: 15.

### Pattern 3 — Hover animation (needs real pointer)

Synthetic `mouseenter` / `mouseover` events do **not** trigger CSS `:hover` styles. You must move a real pointer. Use `mcp__Claude_in_Chrome__computer` with a `move` action pointing to the element's bbox center, then await via JS:

1. Read `bbox_css` from Step 0.
2. Compute the center: `(bbox_css[0] + bbox_css[2] / 2, bbox_css[1] + bbox_css[3] / 2)` (CSS pixels, viewport-relative).
3. Call `mcp__Claude_in_Chrome__computer` with the move action to that center (check the tool's exact action schema at call time).
4. Immediately inject this JS to wait for the transition:

```js
const target = document.querySelector('<TARGET_SELECTOR>');
await new Promise((resolve) => {
  target.addEventListener('transitionend', resolve, { once: true });
  setTimeout(resolve, 10000);
});
return { ok: true };
```

Default FPS: 20. Pre-roll stays at 200 ms (captures the pre-hover baseline).

### Pattern 4 — Form submit feedback (AJAX forms only)

Use for forms that do `event.preventDefault()` and show an in-page animation (success toast, loading spinner, validation flash). If the form actually navigates, use Pattern 5 on the destination page.

```js
const form   = document.querySelector('<FORM_SELECTOR>');
const target = document.querySelector('<FEEDBACK_TARGET_SELECTOR>');
if (!form || !target) throw new Error('selector not found');
await new Promise((resolve) => {
  target.addEventListener('animationend',  resolve, { once: true });
  target.addEventListener('transitionend', resolve, { once: true });
  setTimeout(resolve, 10000);
  form.requestSubmit ? form.requestSubmit() : form.submit();
});
return { ok: true };
```

Default FPS: 15.

### Pattern 5 — Page-load / initial render / route transition

Use for hero animations, SPA route changes, first-paint transitions. Run AFTER `mcp__Claude_in_Chrome__navigate` to the target URL.

```js
await new Promise((resolve) => {
  const onReady = () => setTimeout(resolve, 500);
  if (document.readyState === 'complete') onReady();
  else window.addEventListener('load', onReady, { once: true });
  setTimeout(resolve, 15000);
});
return { ok: true };
```

Default FPS: 12. The 500 ms trailing buffer captures entry animations that start on `load`.

### Pattern 6 — Media playback

Use for `<video>` / `<audio>` elements.

```js
const media = document.querySelector('<MEDIA_SELECTOR>');
if (!media) throw new Error('media selector not found');
await new Promise((resolve) => {
  media.addEventListener('ended', resolve, { once: true });
  setTimeout(resolve, 15000);
  media.currentTime = 0;
  media.play();
});
return { ok: true };
```

Default FPS: 15. If the media is longer than 10 s, ask the user first whether they really want a full capture.

## Fallback decision tree

When no pattern matches (canvas, custom `requestAnimationFrame`, unknown JS framework):

1. **Inspect** with `mcp__Claude_in_Chrome__javascript_tool`:

   ```js
   const el = document.querySelector('<TARGET_SELECTOR>');
   const cs = getComputedStyle(el);
   return {
     tag: el.tagName,
     transition_duration: cs.transitionDuration,
     animation_name: cs.animationName,
     has_video: !!el.querySelector && !!el.querySelector('video'),
   };
   ```

2. **Classify:**
   - `tag === 'CANVAS'` or `tag === 'VIDEO'` → time-based cap. Ask the user for expected duration if longer than 5 s.
   - `animation_name !== 'none'` or `transition_duration !== '0s'` → Pattern 1 after all, try it.
   - Otherwise → polling.

3. **Polling snippet (used only by the fallback):**

   ```js
   const target = document.querySelector('<TARGET_SELECTOR>');
   let last = null, stable = 0;
   const deadline = Date.now() + 15000;
   while (Date.now() < deadline) {
     const r = target.getBoundingClientRect();
     const cs = getComputedStyle(target);
     const sig = `${r.left}|${r.top}|${r.width}|${r.height}|${cs.opacity}|${cs.backgroundColor}`;
     if (sig === last) { if (++stable >= 3) break; } else { stable = 0; last = sig; }
     await new Promise(res => setTimeout(res, 50));
   }
   return { ok: true };
   ```

   Resolves when the element's geometry + opacity + background stay identical for 3 consecutive 50-ms ticks (150 ms stable).

4. **If still ambiguous**: ask the user for the expected duration and characterising frame ("click", "scroll", "drag"), then pick the closest pattern.

## Orchestration recipe

```
1. Step 0 — inspect target; compute physical bbox.
2. Pick fps from the heuristic below based on expected duration.
3. start_recording(region=physical_bbox, region_dpr=1.0, fps=fps, session_name="chrome_<pattern>")
4. sleep(200 ms)                       # pre-roll
5. trigger JS via javascript_tool      # blocks until await resolves
   (Pattern 3 additionally calls mcp__Claude_in_Chrome__computer before the JS)
6. stop_recording(session_id)          # frames already complete
7. Task(subagent_type="frame-analyzer", prompt="<user question + frame paths + pattern context>")
8. cleanup_session(session_id)
9. Synthesize the subagent's report into a concise answer.
```

## FPS heuristics

Choose based on **expected animation duration**, not overall recording length:

| Expected duration | FPS |
|---|---|
| < 1 s  | 25–30 |
| 1–3 s  | 15–20 |
| 3–8 s  | 8–12  |
| > 8 s  | 5–8   |

Never exceed 30 fps (mss I/O gets lossy) and never go below 3 fps for animation analysis.

## Error handling

| Error | What to do |
|---|---|
| `javascript_tool` throws "selector not found" | Stop. Tell the user the selector didn't match and ask for the correct one. |
| Pattern 1 completes immediately (no animation ran) | The element had no CSS transition; switch to fallback polling or ask the user. |
| Safety timeout (15 s) fires | Stop. Warn the user that the animation exceeded 15 s — suggest Pattern 5 or on-demand mode with a longer cap. |
| bbox math looks wrong (negative or > monitor size) | Pass `region=None` to `start_recording` (full-screen capture); the subagent will focus based on the question. |
| `start_recording` returns `{"error": ...}` | Surface it to the user, do not attempt the trigger. |

## Common mistakes to avoid

- **Using this skill for a single-state screenshot.** Use Claude-in-Chrome's screenshot tool for that.
- **Forgetting `cleanup_session` after the subagent returns.** Leaks disk.
- **Passing a CSS-pixel bbox to `region` without converting.** On high-DPI displays the capture is off-center. Either compute the physical bbox (Step 0) or use `region_dpr`.
- **Setting `fps > 30`.** I/O becomes the bottleneck, frame drops rise, no quality gain.
- **Using Pattern 4 for navigating forms.** The navigation destroys the feedback animation. Use Pattern 5 on the landing page instead.
- **Starting a continuous buffer to answer an on-demand question.** Continuous is user-activated long-running; this skill is sharp, short, triggered.

## Related

- Subagent: `.claude/agents/frame-analyzer.md` (reused unchanged)
- Sibling skill: `.claude/skills/analyze-screen/SKILL.md` (desktop / non-Chrome)
- Sibling skill: `.claude/skills/review-recent-activity/SKILL.md` (rolling buffer queries)
- Project guidance: `CLAUDE.md`
```

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/analyze-page-animation/SKILL.md
git commit -m "feat(skill): add analyze-page-animation for Chrome-scoped video capture"
```

---

## Task 4: CLAUDE.md — "Using claudeEyes with Claude-in-Chrome" section

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Insert the new section immediately before `## Related files`**

Open `CLAUDE.md`. Find the line `## Related files`. Insert the block below ABOVE it (leave `## Related files` and everything after it untouched).

```markdown
## Using claudeEyes with Claude-in-Chrome

When you are working on a Chrome page via the `mcp__Claude_in_Chrome__*` tools and the user asks about visual behaviour that unfolds over time (animations, transitions, reveal-on-scroll, hover effects, media playback), use the **`analyze-page-animation` skill**. It coordinates Claude-in-Chrome (DOM, input, navigation) with claudeEyes (video capture) and guarantees timing-perfect start/stop around the triggering action.

### Hard rules

- **Never use Claude-in-Chrome's `computer` screenshot tool for time-based behaviour.** It captures a single frame. claudeEyes captures a real video.
- **Convert CSS pixels to physical pixels** before calling `start_recording`. Chrome's `getBoundingClientRect()` returns CSS pixels; on a 150% / Retina display the physical region is different. Either do the math in JS (recommended, see the skill's Step 0) or pass `region_dpr=window.devicePixelRatio` to `start_recording`.
- **Scroll the target into view before starting the recorder.** Off-screen regions grab empty/irrelevant pixels.
- **Keep using `review-recent-activity` for rolling-buffer queries**, even on Chrome pages — the continuous buffer is not tab-scoped.

### Which skill does what

| Skill | Context | Trigger |
|---|---|---|
| `analyze-screen` | Desktop / OS UI / any app | User asks to see a time-based behaviour outside a browser. |
| `analyze-page-animation` | Chrome page via Claude-in-Chrome | User asks about a specific animation/interaction on a page. |
| `review-recent-activity` | Anywhere, user started the rolling buffer | "Cosa ho fatto", "cosa è successo negli ultimi minuti". |

```

- [ ] **Step 2: Verify CLAUDE.md is still well-formed and not too long**

```bash
wc -l CLAUDE.md
```
Expected: between 140 and 180 lines. Still under the 200-line guidance.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): add Using claudeEyes with Claude-in-Chrome section"
```

---

## Task 5: Cross-link `analyze-screen` and `review-recent-activity` descriptions

**Files:**
- Modify: `.claude/skills/analyze-screen/SKILL.md`
- Modify: `.claude/skills/review-recent-activity/SKILL.md`

- [ ] **Step 1: Update `analyze-screen`'s frontmatter description**

Find the `description:` line in `.claude/skills/analyze-screen/SKILL.md`. Replace it with:

```
description: Use when the user asks to understand visual behavior that unfolds over time — animations, UI transitions, loading states, interactions, or any screen activity that a single screenshot cannot capture. Triggers include phrases like "analyze what happens when…", "is the animation smooth", "cosa succede quando clicco", "analizza l'animazione". For Chrome pages accessed via Claude-in-Chrome, prefer `analyze-page-animation` which handles DOM selectors and timing-perfect triggering.
```

- [ ] **Step 2: Update `review-recent-activity`'s frontmatter description**

Find the `description:` line in `.claude/skills/review-recent-activity/SKILL.md`. Replace it with:

```
description: Use when the user asks about something they recently did on screen — "what did I just do", "cosa ho fatto", "riassumi gli ultimi N minuti", "cosa è successo nel buffer", "ricordami cosa stavo facendo". Requires the continuous buffer to already be active (the user must have started it explicitly). For a targeted on-demand capture of a specific Chrome animation, prefer `analyze-page-animation` instead.
```

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/analyze-screen/SKILL.md .claude/skills/review-recent-activity/SKILL.md
git commit -m "docs(skills): cross-link analyze-page-animation from sibling skills"
```

---

## Task 6: Full suite + lint + type check + commit lint fixes

**Files:**
- Possibly modify: any file flagged by ruff / mypy.

- [ ] **Step 1: Run the full suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```
Expected: **68 passed**. No failures.

- [ ] **Step 2: Run mypy**

```bash
.venv/Scripts/python.exe -m mypy src/claude_eyes
```
Expected: `Success: no issues found in 7 source files`.

If mypy flags anything, fix it minimally — most likely candidates: missing default on `region_dpr` in one of the two signatures, or a missing type annotation on the clamped value. Re-run until clean.

- [ ] **Step 3: Run ruff**

```bash
.venv/Scripts/python.exe -m ruff check src tests
```
Expected: `All checks passed!`.

If ruff flags long lines in the new test additions (likely the DPR test docstrings), wrap them to ≤100 chars.

- [ ] **Step 4: Commit any lint/type fixes**

If Steps 2 or 3 required edits:

```bash
git add -u
git commit -m "chore: satisfy mypy/ruff after Chrome integration changes"
```

If nothing changed, this step is a no-op.

---

## Task 7: Manual smoke on a real Chrome page

Not a code task — verifies the skill wording guides real execution. Requires the user to drive Claude in a Claude-Code session with Claude-in-Chrome enabled.

- [ ] **Step 1: Restart Claude Code** so `.mcp.json` and the new skill load.

- [ ] **Step 2: Navigate a test page with a simple CSS animation**

   Any page with a button that plays a CSS transition works. A minimal test page (save as `smoke.html`, open in Chrome):

   ```html
   <!doctype html>
   <style>
     #box { width: 120px; height: 120px; background: #3366ff; transition: transform 1.2s ease; }
     #box.on { transform: rotate(360deg) scale(1.3); background: #ff3366; }
   </style>
   <button id="go">Play</button>
   <div id="box"></div>
   <script>
     document.getElementById('go').onclick = () => document.getElementById('box').classList.toggle('on');
   </script>
   ```

- [ ] **Step 3: Ask Claude**: "Guarda questa pagina — l'animazione del box quando clicco Play è fluida?"

   Expected sequence observed in Claude's response/tool calls:
   1. Inspects the target via `mcp__Claude_in_Chrome__javascript_tool` (Step 0 snippet).
   2. Computes physical bbox.
   3. Calls `start_recording` with the bbox and chosen fps (should land in 15–25 range for a ~1.2 s animation).
   4. Sleeps ~200 ms.
   5. Calls `javascript_tool` with the Pattern 1 snippet (`transitionend` await + click).
   6. Calls `stop_recording` immediately after.
   7. Dispatches `frame-analyzer` subagent.
   8. Calls `cleanup_session`.
   9. Answers the user in one or two sentences referencing specific frames.

- [ ] **Step 4: Smoke on a scaled display**

   If the display is at 100% scaling, change it to 150% (Windows: `Win+I → System → Display → Scale`) or use a 4K laptop. Re-run Step 3. The captured frames must show the `#box`, not an offset region.

No code commit in this task.

---

## Self-Review

**1. Spec coverage.**

| Spec requirement | Task |
|---|---|
| `region_dpr` param on `start_recording` | 2 |
| `region_dpr` applied inside `_capture_loop` with clamp | 1 |
| `start_continuous_buffer` NOT receiving `region_dpr` in this spec | covered by omission (only Task 2 modifies server) |
| New skill `analyze-page-animation` with 6 patterns + fallback | 3 |
| CLAUDE.md "Using claudeEyes with Claude-in-Chrome" section | 4 |
| Cross-links on `analyze-screen` + `review-recent-activity` | 5 |
| Hover pattern uses real pointer via `mcp__Claude_in_Chrome__computer` | 3 (Pattern 3 body) |
| AJAX-only note on Pattern 4 | 3 (Pattern 4 body) |
| Target off-screen → scrollIntoView + settle | 3 (Step 0) |
| DPR clamp `[0.1, 4.0]` | 1 (`_capture_loop`) |
| Tests: dpr noop, dpr scale, dpr clamp, server forwards | 1, 2 |
| mypy + ruff clean | 6 |
| Manual smoke on real Chrome + scaled display | 7 |

No gaps.

**2. Placeholder scan.** No "TBD", "TODO", "add error handling", or "similar to above" anywhere. Every code step shows the exact code to write. Every command step shows expected output.

**3. Type consistency.**

- `region_dpr: float = 1.0` — same default, same type, same position in both `_capture_loop` and `start_recorder` (Task 1) and `start_recording` (Task 2).
- Clamp logic `max(0.1, min(4.0, region_dpr))` lives only in `_capture_loop` — `start_recorder` forwards the raw value, the clamp is the last line of defence. Consistent.
- Test class `_FakeMSS` is extended once (Task 1 Step 1) and reused by Task 2 Step 1 via import. No shadow definitions.
- Skill file path `.claude/skills/analyze-page-animation/SKILL.md` — same across Tasks 3, 4, 5.
- Tool names in examples (`mcp__Claude_in_Chrome__javascript_tool`, `mcp__Claude_in_Chrome__computer`, `mcp__Claude_in_Chrome__navigate`) — consistent.

No drift. Plan ready.

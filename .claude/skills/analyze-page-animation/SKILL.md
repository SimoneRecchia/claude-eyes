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

## Scan-then-drill when frames exceed 30

`stop_recording` auto-attaches `previews` to its response. Reach for scan-then-drill when `frames_count >= 30`; otherwise pass raw frames directly as before.

1. **Scan pass.** Dispatch `frame-analyzer` with only the `previews.items[*].preview_path`. Prompt: "identify the bucket index containing the animation described". Return a `bucket_index`.
2. **Drill pass.** Build the raw `frame_paths` subset whose indices fall inside the chosen bucket's `frame_range`. Dispatch `frame-analyzer` again with that subset and the user's original question.

For a tight Chrome animation the recording is often shorter than a bucket (≤ 1 s) and may land in `frames_count < 30` — in that case skip the scan pass entirely, it adds nothing.

If the default `avg` preview doesn't surface the animation clearly (common for subtle colour transitions on a light background), call `compose_timeline_preview(session_id, mode="max")` and re-scan with the new previews.

## Active range (Spec 5)

`stop_recording` attaches `active_range: [first_idx, last_idx] | null`, `fps_effective: float`, and `activity_score_mean: float`.

**Usage in this skill:**

1. Chrome animations are often very tight (1-2 s) and bracketed by long idle padding (Claude-in-Chrome JS roundtrip + transitionend wait). `active_range` typically identifies the ~30 frames around the animation out of ~400. Filter `frame_paths` to that range before scanning.
2. If `active_range` is null, the animation didn't produce enough per-pixel delta to exceed the adaptive threshold (very subtle colour shifts on a light background, for example). Fall back to `frame_paths` and consider `compose_timeline_preview(session_id, mode="max")` to amplify trails.
3. `fps_effective < 0.8 × fps_nominal` in this skill almost always means the `region` was too wide (browser viewport instead of a tight element bbox). Recompute Step 0 with a tighter bbox and retry.

**Optional: `trim_session`.** Useful when running many animation captures in a row — frees disk without losing the analysis value.

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

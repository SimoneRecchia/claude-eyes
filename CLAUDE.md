# claude-eyes — project guidance

claude-eyes is an MCP server that gives you **visual awareness of what happens on screen over time**. You can record the screen at a chosen frame rate, then dispatch the `frame-analyzer` subagent to analyze the captured sequence.

Use this capability when a single screenshot is not enough — when the information you need unfolds across time.

## When to use it

Invoke screen recording when the user asks you to understand something that **changes over time**:

- Animations (smoothness, glitches, stuttering, easing)
- UI transitions, loading states, progressive rendering
- User interactions (drag, hover, multi-step flows)
- Behavior during events (click, scroll, keypress)
- Anything where "show me what happens when…" is the right framing

**Do NOT use it when:**
- A single screenshot answers the question → use the native screenshot tool.
- You can answer from code or documentation without seeing anything.
- The user has not asked for a visual analysis (don't record pre-emptively).

## The MCP tools (all deterministic, no AI)

| Tool | Purpose |
|---|---|
| `start_recording` | Begin capture. Returns `session_id`. |
| `stop_recording` | End capture. Returns frame paths + metadata. |
| `list_frames` | List frames of an existing session without stopping. |
| `cleanup_session` | **MANDATORY after every analysis.** Frees disk. |

AI analysis is **not** in the MCP — it happens by dispatching the `frame-analyzer` subagent via the `Task` tool.

## Decision tree: how to pick the right approach

Claude makes three decisions in sequence before starting any recording:

### 1. Categorize the question

| Category | Examples | Drill mandatory? | fps target |
|---|---|---|---|
| **Motion / gesture / trail** | "che forma sto facendo", "traccia il percorso", "cursor path" | **yes** | 25–30 |
| **Timing / transition** | "is it smooth", "when does X appear", "flicker" | **yes** | 20–25 |
| **Existence / layout** | "cosa c'era sul menu", "which buttons are visible" | no | 10–15 |
| **Long recall** | "cosa ho fatto negli ultimi 5 minuti" | no | 2–3 (buffer OK) |

The category drives the next two decisions. Motion and timing questions require the drill pass — the preview is never a valid final answer for them.

### 2. Pick `fps` and `resolution_scale`

| Situation | `fps` | `resolution_scale` |
|---|---|---|
| Mouse gesture / drag / cursor path | 25–30 | 0.75 |
| OS animation / Chrome transition | 20–25 | 1.0 |
| Normal UI animation | 15–20 | 1.0 |
| UI walkthrough / multi-step | 10 | 0.75 |
| **Default (no clear hint)** | **10** | **0.75** |
| Layout-only check | 5 | 0.5 |
| Long recall / "what did I do" | 2–3 | 0.75 |

Hard ceiling: **60 fps** (monitor refresh rate; above that is wasted disk).

### 3. Pick `region`

- For localized UI (a button, a widget, a menu): tight bounding box. Saves disk and focuses the subagent.
- For multi-monitor setups (`CLAUDE_EYES_MONITOR=0`, i.e. virtual screen): if the action is on one monitor, narrow `region` to that monitor's bounds. Full virtual-screen captures on multi-monitor hit I/O ceilings fast.
- If unsure, ask the user "which monitor is the action on?" once before starting the recording.

### Session name

`session_name` is an optional human-readable label for your own tracking. Defaults to auto-generated.

## Standard workflow

The `analyze-screen` skill orchestrates this end-to-end. Follow it:

1. **Pick parameters** using the heuristics above.
2. **`start_recording(...)`** — save the `session_id`.
3. **Tell the user** what to do (if the recording captures their action).
4. **`stop_recording(session_id)`** — receive frame paths.
5. **Dispatch the subagent** via the `Task` tool:
   - `subagent_type: "frame-analyzer"`
   - Pass the frame paths and the analysis question.
6. **`cleanup_session(session_id)`** — **always, no exceptions.**
7. **Synthesize** the subagent's report into a concise answer for the user.

## Hard rules

- **Always call `cleanup_session` after analysis.** Leaked sessions fill disk. A `SessionEnd` hook wipes orphans as a safety net, but that's a last resort — not an excuse.
- **Never record without a user-visible reason.** If the user didn't ask to understand something visual, don't start a recording.
- **Never raise `fps` or `resolution_scale` "just in case."** Higher values = more tokens for the subagent and more disk. Match the task.
- **Never dispatch analysis directly from the main agent.** Always go through the `frame-analyzer` subagent. Main agent = orchestration, subagent = vision.
- **Never set `fps > 60`.** Monitor refresh is 60 Hz; higher values double disk and add zero visual information.
- **Preview images are a SCAN tool, never an ANSWER.** After the scan pass identifies relevant buckets, the drill pass is MANDATORY for motion-, timing-, or trail-category questions. Answering from a composited preview is a bug.
- **For motion- or timing-category questions, never rely on the 2 fps continuous buffer.** Start an on-demand recording at `fps >= 20` — the buffer coexists with on-demand recordings, no need to stop it.
- **Under I/O bottleneck (`fps_effective < 50% × fps_nominal`), the retry MUST lower `resolution_scale` or narrow `region` before raising `fps`.** Raising fps when I/O is the bottleneck is wasted compute.

## Continuous mode (rolling buffer)

claude-eyes also supports a **continuous rolling buffer**: a low-fps background capture that keeps the last N minutes of screen activity on disk, for "what did I just do" style questions. It is separate from on-demand recording and coexists with it.

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

## Using claude-eyes with Claude-in-Chrome

When you are working on a Chrome page via the `mcp__Claude_in_Chrome__*` tools and the user asks about visual behaviour that unfolds over time (animations, transitions, reveal-on-scroll, hover effects, media playback), use the **`analyze-page-animation` skill**. It coordinates Claude-in-Chrome (DOM, input, navigation) with claude-eyes (video capture) and guarantees timing-perfect start/stop around the triggering action.

### Hard rules

- **Never use Claude-in-Chrome's `computer` screenshot tool for time-based behaviour.** It captures a single frame. claude-eyes captures a real video.
- **Convert CSS pixels to physical pixels** before calling `start_recording`. Chrome's `getBoundingClientRect()` returns CSS pixels; on a 150% / Retina display the physical region is different. Either do the math in JS (recommended, see the skill's Step 0) or pass `region_dpr=window.devicePixelRatio` to `start_recording`.
- **Scroll the target into view before starting the recorder.** Off-screen regions grab empty/irrelevant pixels.
- **Keep using `review-recent-activity` for rolling-buffer queries**, even on Chrome pages — the continuous buffer is not tab-scoped.

### Which skill does what

| Skill | Context | Trigger |
|---|---|---|
| `analyze-screen` | Desktop / OS UI / any app | User asks to see a time-based behaviour outside a browser. |
| `analyze-page-animation` | Chrome page via Claude-in-Chrome | User asks about a specific animation/interaction on a page. |
| `review-recent-activity` | Anywhere, user started the rolling buffer | "Cosa ho fatto", "cosa è successo negli ultimi minuti". |

## Scan-then-drill workflow

`stop_recording` and `query_buffer` auto-attach bucket previews to their responses (one composited image per `bucket_s=1.0` second of recording, `mode="avg"` by default) AND the active-range metadata from Spec 5. Use them to reduce token spend on the frame-analyzer subagent.

Rule of thumb: if a response has `frames_count < 30`, pass raw `frame_paths` directly (previews add no value). Otherwise:

0. **Respect `active_range`.** If the response contains `active_range: [first, last]`, filter `frame_paths` to indices in that range before anything else — dead frames outside the range shouldn't reach the subagent. If `fps_effective < 0.8 × fps_nominal`, warn the user: the capture is disk-I/O-bound.
1. **Scan.** Send only `previews.items[*].preview_path` (or the subset whose `frame_range` intersects `active_range`) to the subagent with the prompt "identify the bucket indices relevant to the question". Get back a short list.
2. **Drill.** Filter `frame_paths` to the chosen buckets' `frame_range` (further narrowed by `active_range` if present) and dispatch the subagent again with the raw frames and the original question.

If the default `avg` preview doesn't surface the behaviour, call `compose_timeline_preview(session_id, bucket_s=0.5, mode="max")` or `mode="motion"` and re-scan. Optional follow-up: call `trim_session(session_id)` to free disk after the analysis (deletes frames outside `active_range`). Skills (`analyze-screen`, `analyze-page-animation`, `review-recent-activity`) all follow this pattern — reach for them first, they encode the flow.

## Retry protocol

If the first analysis attempt fails or hedges, retry ONCE with different parameters. Do not re-run the same capture with the same settings.

**Retry triggers** (retry if any apply):

- Subagent response contains hedge words: "I think", "probably", "could be", "hard to tell", "perhaps".
- Response is shorter than ~20 words for a qualitative question.
- Response contradicts a specific hint the user provided.
- User explicitly says "wrong" / "riprova" / "no, try again".

**Retry tactics** (apply in this priority order, pick the first that fits):

1. **I/O-first.** If `fps_effective < 50% × fps_nominal`, lower `resolution_scale` to 0.5 OR narrow `region` to a single monitor before touching fps. Raising fps under I/O bottleneck is wasted.
2. **Preview mode.** For motion/trail with a vague answer, switch `compose_timeline_preview(mode="max")` and re-run the drill. For timing, switch to `mode="motion"`.
3. **Drill scope.** If the first drill used the whole `active_range`, narrow to a single bucket and drill that alone (higher frame density on the moment that matters).
4. **fps bump.** Only after 1–3 have been applied, bump `fps` by +5 (cap at 30).

Always call `cleanup_session` on the first recording before starting the second. If the second attempt also fails, tell the user what you tried and ask for a specific hint — do not loop.

## Related files

- Subagent: `.claude/agents/frame-analyzer.md` — vision analysis instructions.
- Skill: `.claude/skills/analyze-screen/SKILL.md` — the orchestration workflow.
- Hooks: `.claude/settings.json` + `.claude/hooks/*.py` — cleanup & logging.
- MCP config: `.mcp.json` — registers the `claude_eyes` stdio server.

See @README.md for repository overview.

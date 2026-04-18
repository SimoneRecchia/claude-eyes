# claude-eyes — Agent Autonomous Decisions (Spec 6) Design

**Date:** 2026-04-18
**Status:** Draft for review
**Scope:** Prompt engineering (CLAUDE.md, 3 skills, 1 subagent prompt) + one-line Python default change.

## 1. Problem

Real-world testing exposed that the main agent makes poor autonomous decisions when using claude-eyes. The user's primary complaint:

> "Once it finds the right preview, it often answers from the preview image alone instead of drilling into the raw frames. And it often runs at 2 fps when it costs practically nothing to go higher — it should make better decisions autonomously."

The detailed test report surfaced three root causes:

1. **Preview-as-answer confusion.** For motion/gesture/trail questions, the agent sends only the composited preview image to the frame-analyzer and treats the response as the final answer — skipping the drill pass. On a test case (identifying an "infinity" mouse gesture) this led to 6 consecutive wrong guesses before the shape was identified, and only via manual OpenCV work by the agent.
2. **fps defaults too low.** `DEFAULT_FPS = 3` is inadequate for the majority of analyses. The agent tends to stick near the default or pick overly conservative values from the existing heuristic table. The test report shows the agent picking 5-15 fps for a mouse-trail task where 25-30 was needed.
3. **No retry protocol.** When a first-pass analysis fails or hedges, the agent re-attempts with identical or nearly-identical parameters. There is no structured retry tactic that considers I/O bottleneck, preview mode choice, or region narrowing.

## 2. Goal

The agent should make the right parameter choices the first time and recover from failures intelligently.

Success criteria (measurable against the test report's scenarios):

- **Motion-shape identification** ("what shape am I drawing?") resolves in ≤ 2 attempts, not 6.
- **`stop_recording` drill pass is always executed** when the question is motion-, timing-, or trail-related. Never answered from the preview alone.
- **fps_effective I/O awareness**: when effective fps drops below 50% of nominal, the retry tactic lowers `resolution_scale` or narrows `region` before touching `fps` again.
- **Continuous buffer boundary is respected**: motion-quality questions do NOT get answered from the 2-fps buffer. The agent recognises this and escalates to an on-demand recording.

Non-goals:

- New preview modes (temporal gradient, cursor-only heatmaps) — Spec 9.
- Motion-detection algorithm changes (localized activity) — Spec 9.
- `cleanup_session` grace period, response projections, `query_buffer` on stopped buffer — Spec 8.
- Python tool-level changes beyond the single default bump.

## 3. Architecture

Spec 6 is a prompt-engineering spec. The fix lives in four markdown documents plus one line of Python:

```
src/claude_eyes/config.py              # DEFAULT_FPS: 3 → 10
CLAUDE.md                              # new decision tree, new fps table, retry protocol
.claude/skills/analyze-screen/SKILL.md              # step 0 "categorize", drill-mandatory list
.claude/skills/analyze-page-animation/SKILL.md      # retry protocol cross-reference
.claude/skills/review-recent-activity/SKILL.md      # escalation rule for motion questions
.claude/agents/frame-analyzer.md       # coordinate contract, "preview ≠ answer"
```

The agent's new decision flow has three levels:

### Level 1 — Question categorization (new)

Before any parameter selection, the agent classifies the user's question into one of four categories:

| Category | Examples | Drill required | fps target |
|---|---|---|---|
| **Motion / gesture / trail** | "what shape am I drawing", "traccia il percorso", "cursor path" | **yes** | 25–30 |
| **Timing / transition** | "is the animation smooth", "when does X appear", "flicker" | **yes** | 20–25 |
| **Existence / layout** | "what was on the menu", "which buttons are visible" | no | 10–15 |
| **Long recall** | "what did I do in the last 5 minutes" | no | 2–3 (buffer OK) |

This category drives every downstream choice: drill-or-not, fps, preview mode, retry tactic.

### Level 2 — Parameter selection

A new fps/scale table replaces the current one in `CLAUDE.md`:

| Situation | fps | resolution_scale |
|---|---|---|
| Mouse gesture / drag / cursor path | 25–30 | 0.75 |
| OS animation / Chrome transition | 20–25 | 1.0 |
| Normal UI animation | 15–20 | 1.0 |
| UI walkthrough / multi-step | 10 | 0.75 |
| **Default (no hint otherwise)** | **10** | **0.75** |
| Layout-only check | 5 | 0.5 |
| Long recall / "what did I do" | 2–3 | 0.75 |

Hard rules:

- **Never answer a motion-/timing-/trail-question from the 2 fps continuous buffer.** If the buffer is active and the question falls in those categories, the agent starts an on-demand recording at a higher fps alongside the buffer and uses that.
- **Multi-monitor setups**: if `monitor=0` (virtual screen combining all monitors) and `fps_effective < 50%` of nominal, the agent switches to `region`-scoped capture of only the active monitor on the next attempt.

### Level 3 — Retry protocol

Retry is triggered when any of these conditions hold after the first analysis attempt:

- Subagent response contains hedge words ("I think", "probably", "could be", "hard to tell", "perhaps")
- Response is < 20 words and the question is qualitative
- Response contradicts a specific hint the user provided
- User explicitly says "wrong" / "riprova" / "no, try again"

Retry tactics, applied in this priority order:

1. **I/O-first.** If `fps_effective < 50% × nominal`, lower `resolution_scale` to 0.5 OR switch to single-monitor `region` before touching fps. Alzare fps under I/O bottleneck is wasted.
2. **Preview mode.** For motion/trail with a vague answer, switch `compose_timeline_preview(mode="max")`. For timing, switch to `mode="motion"`. Always re-run the drill pass on the new preview.
3. **Drill scope.** If the drill pass used the whole `active_range`, narrow to a single bucket and drill deeper (higher fps raw frame density).
4. **fps bump.** Only after 1–3 have been applied, bump `fps` by +5 (cap at 30).

The agent retries ONCE. If the second attempt also fails, the agent tells the user what it tried and asks for a hint.

## 4. Concrete changes

### 4.1 `src/claude_eyes/config.py`

```python
DEFAULT_FPS: int = 10  # was 3
```

`DEFAULT_CONTINUOUS_FPS` stays at 2: the buffer is a passive recall tool, not a motion-capture tool. The documentation makes this boundary explicit.

### 4.2 `CLAUDE.md`

New section **"Decision tree: how to pick the right approach"** inserted before the existing `## Parameter heuristics`. It walks through:

1. Question categorization (the 4-tier table above)
2. Parameter selection (the new fps/scale table)
3. Retry protocol (triggers + tactics)
4. Multi-monitor I/O guidance

The existing `## Parameter heuristics` section is replaced by a reference to the decision tree.

New section **"Retry protocol"** after `## Scan-then-drill workflow`. Explicit trigger list and tactic priority.

Updated `## Hard rules`:

- Add: "Preview images are a SCAN tool, never an ANSWER. After the scan pass identifies relevant buckets, the drill pass is MANDATORY for motion-, timing-, or trail-category questions."
- Add: "For motion- or timing-category questions, never rely on the continuous buffer. Start an on-demand recording at fps ≥ 20."
- Add: "When `fps_effective < 50% × fps_nominal`, the retry MUST lower `resolution_scale` or narrow `region` before raising fps."

### 4.3 `.claude/skills/analyze-screen/SKILL.md`

New **Step 0: Categorize the question** before "Pick parameters":

> Classify the user's question into one of: motion/gesture/trail, timing/transition, existence/layout, long-recall. This choice drives fps, preview mode, and whether the drill pass is mandatory. See `CLAUDE.md` decision tree.

Updated Step 5 "Scan then drill":

> **Drill is mandatory for motion/gesture/trail and timing/transition categories.** The preview image is never a valid final answer for these categories — it compresses time and cannot reveal order or smoothness. Even when the preview "seems to show" the answer, dispatch the drill pass on raw frames.

New Step 8 "Retry once if needed":

> If the subagent's answer is uncertain (hedge words, <20 words, conflicts with a user hint), retry once using the tactic priority from `CLAUDE.md § Retry protocol`. If the second attempt also fails, tell the user what you tried and ask for a specific hint.

Updated "Common mistakes to avoid":

- Replace "Asking the scan subagent for a final answer" with a stronger version: "Treating the preview as the answer. The preview is always a scan tool. For motion/timing questions, the drill pass is NOT OPTIONAL — even when the preview looks like it shows the answer."
- Add: "Retrying with identical parameters after a failure. If the first pass failed, change something meaningful (res_scale, region, preview mode) before retrying. Running the same capture again won't help."
- Add: "Raising fps when `fps_effective < 50%`. Under I/O bottleneck, raising fps trades disk thrash for zero extra frames. Lower `resolution_scale` or narrow `region` first."

### 4.4 `.claude/skills/analyze-page-animation/SKILL.md`

Add cross-reference to the new retry protocol in the "Pattern library" preamble:

> After each pattern completes, if the subagent's answer is uncertain, apply the retry protocol from `CLAUDE.md § Retry protocol`. For Chrome contexts, the first retry tactic is usually to narrow `region` to the element's bounding box (DPR-converted) rather than re-recording.

Update fps heuristics table to match the new CLAUDE.md table.

### 4.5 `.claude/skills/review-recent-activity/SKILL.md`

New step **"Step 1.5: Check if the buffer is the right tool"**:

> If the user's question involves motion quality (gestures, trails, smoothness), the 2 fps buffer is **insufficient**. Do not attempt to answer from it. Tell the user: "The continuous buffer is sampled at 2 fps — for motion-quality questions we need an on-demand recording at a higher frame rate. Should I start one?" Then switch to the `analyze-screen` skill with fps ≥ 20.

Add "Common mistake":

> "Answering a motion-quality question from the 2 fps buffer. The buffer is for coarse recall ('what did I do') — never for fine motion analysis."

### 4.6 `.claude/agents/frame-analyzer.md`

New section **"Coordinate contract"** before the output format:

> When images are presented to you, you see them at their actual pixel dimensions (Claude Code's viewer does not rescale the raw image data you receive). If the main agent asks for pixel coordinates:
>
> - Use the actual image dimensions as the coordinate system.
> - In the first sentence of your answer, state the dimensions you are using (e.g., "Frames are 1720×1320 pixels.").
> - Do not invent a "viewer" scale. If pixel coordinates are not explicitly requested, prefer qualitative positions ("top-left quadrant", "center", "row 2 column 3").

New line in principles:

> **The preview image is never the final answer for motion/trail/timing questions.** When you receive a single composited preview image and a motion question, your job is ONLY to identify which temporal bucket(s) contain the motion — do NOT describe the shape or trail from the preview. Return bucket indices only; the main agent will drill to raw frames.

## 5. Behavioural examples

### 5.1 Motion shape (was: 6 failed attempts)

**Before (Spec 5):**
1. Agent starts recording at 15 fps, res_scale 0.75, full multi-monitor
2. After stop, fps_effective is 5 — but agent doesn't react
3. Agent dispatches subagent on the `max` preview only — subagent guesses "C" from ghost trail
4. User says wrong; agent re-records with similar params
5. … repeats 5 more times

**After (Spec 6):**
1. Agent categorizes: motion/gesture → mandatory drill, target fps 25
2. Starts recording at 25 fps, res_scale 0.75, full screen
3. `stop_recording` returns fps_effective=8 — well below 50% of 25
4. Agent retries with res_scale 0.5 (I/O-first) before even dispatching the subagent, OR narrows `region` to the active monitor
5. Second recording: fps_effective 18 — acceptable
6. Dispatches scan on preview → subagent returns bucket indices
7. **Drills** on raw frames from those buckets → subagent gets an ordered series, identifies "infinity"
8. Done in 2 recordings, ≤ 3 subagent dispatches

### 5.2 Motion question asked against running buffer

**Before:**
1. Buffer active at 2 fps
2. User: "what shape am I drawing?"
3. Agent queries buffer, gets 2-fps preview, dispatches subagent
4. Wrong answer from undersampled data

**After:**
1. Buffer active at 2 fps
2. User: "what shape am I drawing?"
3. Agent categorizes: motion → buffer insufficient
4. Agent responds: "The continuous buffer is sampled at 2 fps — for motion analysis we need a dedicated recording at higher fps. I'll start one now, keep drawing."
5. Starts on-demand at 25 fps alongside buffer
6. Analyzes, answers

## 6. Testing

### 6.1 Unit

Update any test that asserts `DEFAULT_FPS == 3` to expect 10. `tests/test_server.py` and `tests/test_recorder.py` are the likely candidates. Also verify `start_recording()` without args creates a session with fps=10.

### 6.2 Prompt consistency

A secondary review pass (spec-reviewer subagent) reads the modified CLAUDE.md + skills + frame-analyzer prompt and checks:

- No contradictions between files.
- The retry protocol is cited consistently.
- The new fps table appears identically in CLAUDE.md and the skill quick-references.

### 6.3 Manual regression (user, in a fresh Claude Code session)

Three scenarios against a freshly-installed plugin:

1. **Passive recall** (baseline): start buffer, use Start menu, ask "what was on the menu". Must work correctly — no regression.
2. **Motion gesture**: draw an infinity with the mouse. The agent must:
   - Start an on-demand recording at fps ≥ 20 within the first try
   - Drill to raw frames (not answer from preview)
   - Recover from low fps_effective by lowering res_scale on retry
   - Identify the shape in ≤ 2 recordings
3. **fps_effective low**: force a multi-monitor capture at high fps where I/O will throttle. The agent must respond on retry by lowering res_scale or narrowing region, not by raising fps.

## 7. Edge cases

- **User specifies fps explicitly**: agent respects it, does not override. The decision tree is a default, not a mandate.
- **Continuous buffer already captured relevant motion by chance**: agent may use the buffer data as a hint (timing window) but must still run an on-demand recording for the analysis itself.
- **Subagent replies confidently but with a wrong answer and no hedge words**: agent cannot detect this; relies on user saying "wrong". The retry protocol still applies once the user does.
- **All retry tactics have been exhausted**: agent tells the user explicitly what it tried and asks for a hint. Does not loop indefinitely.
- **Cleanup between retries**: when retrying an on-demand recording with different parameters, `cleanup_session` MUST be called on the first session before starting the second. The previous session's frames are no longer useful and leaving them accumulates disk.
- **Multi-monitor `region` without known geometry**: if the agent needs to narrow to a single monitor but does not know monitor boundaries (no prior knowledge from the user, no MCP tool exposing monitor geometry), it asks the user one short question: "which monitor is the action on?" — then infers the region from the answer or recommends setting `CLAUDE_EYES_MONITOR` for the session.

## 8. Response contract

No changes. `start_recording`, `stop_recording`, `query_buffer`, `compose_timeline_preview`, `trim_session`, `cleanup_session` response shapes are unchanged.

The only API-visible change is:

- `start_recording()` called without an `fps` argument now returns `config.fps = 10` (was 3). This is documented in the CLAUDE.md upgrade note.

## 9. Rollout

Single PR containing:

1. `config.py` default change + test update (atomic, backwards-compatible at the tool level).
2. `CLAUDE.md` rewrite (decision tree, fps table, retry protocol, hard rules).
3. Three skill file updates.
4. `frame-analyzer.md` prompt update.
5. Spec + plan documents.

Merged to main. First session after merge uses the new defaults. Users who had explicit fps values continue to work unchanged.

## 10. Follow-ups (tracked, not in this spec)

- Spec 7: expose `include_cursor` and `monitor` as MCP tool parameters.
- Spec 8: lifecycle improvements — `query_buffer` on stopped buffer, response projections, softer `cleanup_session`.
- Spec 9: motion-detection improvements — localised activity threshold, temporal-gradient preview, object tracking.
- Spec 10 (if warranted): storage efficiency — in-memory buffering, JPEG quality tuning, optional MP4 output to fix the `fps_effective << fps_nominal` ceiling.

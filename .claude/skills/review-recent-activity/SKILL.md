---
name: review-recent-activity
description: Use when the user asks about something they recently did on screen — "what did I just do", "cosa ho fatto", "riassumi gli ultimi N minuti", "cosa è successo nel buffer", "ricordami cosa stavo facendo". Requires the continuous buffer to already be active (the user must have started it explicitly). For a targeted on-demand capture of a specific Chrome animation, prefer `analyze-page-animation` instead.
---

# review-recent-activity

Orchestrates a query against the continuous rolling buffer: pick a time range, sample frames, dispatch the `frame-analyzer` subagent, synthesize the answer.

## When to use

**Use when:**
- The user references recent past activity on their own screen.
- Phrasing includes "what did I do", "cosa ho fatto", "ultimi minuti", "just now", "a minute ago".
- The continuous buffer is (or was recently) active.

**Do NOT use when:**
- The user wants to analyse a specific animation or UI flow happening now → use `analyze-screen` instead.
- The user has not started the continuous buffer → tell them how to start it and stop.
- A single fresh screenshot would answer the question → use the native screenshot tool.

## Workflow

1. **Check the buffer is active.** If a previous `query_buffer` / `start_continuous_buffer` response indicated the buffer is idle, say so and ask the user whether to start it. Don't start it silently.

1.5. **Check if the buffer is the right tool.** If the user's question involves motion quality (gestures, trails, smoothness, or a shape the cursor is drawing), the 2 fps buffer is **insufficient**. Do not attempt to answer from it. Tell the user:

   > "The continuous buffer is sampled at 2 fps — for motion-quality questions we need an on-demand recording at a higher frame rate. Should I start one?"

   If the user agrees, switch to the `analyze-screen` skill with fps ≥ 20. The continuous buffer can keep running — it coexists with on-demand recordings.

   For existence/layout questions ("what was on the menu", "which apps were open") and long-recall questions ("what did I do in the last 10 minutes"), the buffer is the right tool — continue with the workflow below.

2. **Pick `time_range_s` from phrasing.** Defaults:
   - "just now" / "a moment ago" → 60 s
   - "the last minute" → 60 s
   - "the last few minutes" / "gli ultimi minuti" → 180 s
   - "the last N minutes" → N * 60 s
   - No explicit range → 120 s

3. **Call `mcp__claude_eyes__query_buffer(time_range_s, max_frames=30)`.**
   - If `"error"` is in the result: tell the user the buffer is not active.
   - If `frames` is empty: tell the user nothing was captured in the requested range.
   - If `warning` is present: tell the user the range was clamped to the actual buffer age.

4. **Scan then drill** — the `query_buffer` response already contains `previews` for the queried range.

   a. **Scan pass.** Dispatch `frame-analyzer` with `previews.items[*].preview_path` only. Prompt it to identify which bucket(s) contain activity relevant to the user's question. Return the bucket indices.

   b. **Drill pass.** For each chosen bucket, include only the raw frames from `frames` whose `timestamp_ms` falls inside that bucket's `[ts_start_ms, ts_end_ms]`. Dispatch `frame-analyzer` with that narrower list and the original question. Answer from the second report.

   For "when did I do X" questions, the default `avg` preview from `query_buffer` is usually enough. `compose_timeline_preview` (with `mode="motion"` or different `bucket_s`) currently does **not** address the continuous buffer — it only targets on-demand sessions. If the default preview doesn't surface the moment, rerun `query_buffer` with a narrower `time_range_s` to get tighter bucket coverage.

4.5. **Respect `active_range`.** `query_buffer` attaches `active_range`, `fps_effective`, and `activity_score_mean` just like `stop_recording`.

   - If `active_range` is not null, only scan previews whose `frame_range` intersects `active_range`. For a "what did I do" question, this narrows the scan to the seconds when something actually changed on screen.
   - If `active_range` is null, the continuous buffer captured a static or near-static interval; tell the user "nothing notable happened in the last N seconds" rather than inventing activity.
   - `fps_effective < 0.8 × fps_nominal` is less critical here (continuous buffer runs at low fps by default) but still worth flagging to the user.

5. **Synthesize** the subagent's report into a direct answer. Reference specific moments by their age ("~45 s ago you…") rather than file indices.

6. **Do not call `cleanup_session`.** The continuous buffer is not a regular session — it's managed by `start_continuous_buffer` / `stop_continuous_buffer`.

## Common mistakes to avoid

- **Starting the buffer silently.** The user must ask explicitly. Privacy is at stake.
- **Passing all frames to the subagent.** `max_frames=30` is the default for a reason; don't override upward without cause.
- **Treating the buffer as a regular session.** No `cleanup_session` — `stop_continuous_buffer` is the correct teardown.
- **Answering from an empty result.** If the subagent returns "nothing notable", relay that honestly; don't invent activity.
- **Answering a motion-quality question from the 2 fps buffer.** The buffer is for coarse recall ("what did I do") — never for fine motion analysis. Escalate to `analyze-screen` with higher fps instead.

## Related

- Subagent: `.claude/agents/frame-analyzer.md` (reused, no changes)
- Sibling skill: `.claude/skills/analyze-screen/SKILL.md` (on-demand animation analysis)
- Project guidance: `CLAUDE.md`

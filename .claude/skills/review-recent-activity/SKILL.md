---
name: review-recent-activity
description: Use when the user asks about something they recently did on screen — "what did I just do", "cosa ho fatto", "riassumi gli ultimi N minuti", "cosa è successo nel buffer", "ricordami cosa stavo facendo". Requires the continuous buffer to already be active (the user must have started it explicitly).
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

4. **Dispatch `frame-analyzer`** via the `Task` tool:
   - `subagent_type: "frame-analyzer"`
   - Prompt includes the frame paths (one per line, in order), the user's question, and the `age_s` of the oldest/newest frames so the subagent has temporal context.

5. **Synthesize** the subagent's report into a direct answer. Reference specific moments by their age ("~45 s ago you…") rather than file indices.

6. **Do not call `cleanup_session`.** The continuous buffer is not a regular session — it's managed by `start_continuous_buffer` / `stop_continuous_buffer`.

## Common mistakes to avoid

- **Starting the buffer silently.** The user must ask explicitly. Privacy is at stake.
- **Passing all frames to the subagent.** `max_frames=30` is the default for a reason; don't override upward without cause.
- **Treating the buffer as a regular session.** No `cleanup_session` — `stop_continuous_buffer` is the correct teardown.
- **Answering from an empty result.** If the subagent returns "nothing notable", relay that honestly; don't invent activity.

## Related

- Subagent: `.claude/agents/frame-analyzer.md` (reused, no changes)
- Sibling skill: `.claude/skills/analyze-screen/SKILL.md` (on-demand animation analysis)
- Project guidance: `CLAUDE.md`

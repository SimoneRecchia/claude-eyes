---
name: analyze-screen
description: Use when the user asks to understand visual behavior that unfolds over time — animations, UI transitions, loading states, interactions, or any screen activity that a single screenshot cannot capture. Triggers include phrases like "analyze what happens when…", "is the animation smooth", "cosa succede quando clicco", "analizza l'animazione".
---

# analyze-screen

Orchestrates screen recording and visual analysis via the `claude_eyes` MCP server and the `frame-analyzer` subagent.

## When to use

**Use this skill when the answer requires seeing change over time.** Symptoms and triggers:

- Animation or transition quality questions (smooth, stuttering, glitch).
- "What happens when I do X" style requests.
- UI behavior during loading, interaction, or state change.
- Visual regressions the user cannot pinpoint from a still.

**Do NOT use this skill when:**

- A single screenshot is enough — use the native screenshot tool instead.
- The question can be answered from code, logs, or docs without seeing anything.
- The user is describing something they want *built*, not *analyzed*.

## The workflow

Follow these steps in order. Skipping cleanup at the end is a bug.

1. **Pick parameters.** Read the heuristics in `CLAUDE.md` and choose `fps`, `resolution_scale`, and `region` for the task. Start conservative — you can redo with higher values if the subagent reports insufficient detail.

2. **Start recording.** Call `mcp__claude_eyes__start_recording` with your chosen parameters. Save the returned `session_id` — you will need it for every subsequent call.

3. **Cue the user (if needed).** If the recording captures an action the user has to perform ("click the button", "scroll down"), tell them now, in one short sentence, and wait.

4. **Stop recording.** Call `mcp__claude_eyes__stop_recording(session_id)`. It returns the list of frame paths and metadata.

5. **Dispatch the `frame-analyzer` subagent** via the `Task` tool. Pass:
   - `subagent_type: "frame-analyzer"`
   - A prompt containing: the frame paths (one per line), the user's question, and optional context.

6. **Cleanup.** Call `mcp__claude_eyes__cleanup_session(session_id)`. **Always.** Even if the analysis failed, even if the user interrupted, even if the subagent returned nothing useful.

7. **Answer the user.** Synthesize the subagent's report into a direct, concise answer. Do not paste the whole report — extract what matters for the question.

## Parameter selection quick reference

See `CLAUDE.md` for the full heuristics. Summary:

| Situation | `fps` | `resolution_scale` | `region` |
|---|---|---|---|
| Slow UI transition | 3 | 1.0 | tight bbox |
| Normal animation | 5–8 | 1.0 | tight bbox |
| Fluid/fast animation | 10–15 | 1.0 | tight bbox |
| Layout-only check | 2–3 | 0.5 | full / large area |
| Movement tracking | 5 | 0.25 | full |
| Micro-stutter debug | 20–30 | 1.0 | tight bbox |

## Example dispatch

```
Task(
  subagent_type="frame-analyzer",
  prompt="""
Frame paths (time-ordered):
- C:/.../sessions/sess_abc/frame_0_0.jpg
- C:/.../sessions/sess_abc/frame_1_333.jpg
- ...

Question: Is the button's ripple animation smooth, or does it stutter?

Context: Captured at 10 fps during a user click on #submit.
"""
)
```

## Common mistakes to avoid

- **Forgetting `cleanup_session`.** The `SessionEnd` hook will catch leaks on exit, but inside a long session leaked folders accumulate.
- **Recording the full screen when a 400×200 bbox would do.** Every extra pixel costs disk and subagent tokens.
- **Setting `fps=30` "to be safe".** 30 fps × 10 s = 300 frames. The subagent will be slow and expensive. Match the task.
- **Doing the visual analysis in the main agent.** Main agent = orchestration. Visual reasoning belongs in the subagent.
- **Starting a recording before knowing the question.** Without a clear question you cannot pick parameters, and the subagent has nothing to answer.

## Related

- Subagent: `.claude/agents/frame-analyzer.md`
- Project guidance: `CLAUDE.md`

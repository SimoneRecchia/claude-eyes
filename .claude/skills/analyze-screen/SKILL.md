---
name: analyze-screen
description: Use when the user asks to understand visual behavior that unfolds over time — animations, UI transitions, loading states, interactions, or any screen activity that a single screenshot cannot capture. Triggers include phrases like "analyze what happens when…", "is the animation smooth", "cosa succede quando clicco", "analizza l'animazione". For Chrome pages accessed via Claude-in-Chrome, prefer `analyze-page-animation` which handles DOM selectors and timing-perfect triggering.
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

1. **Categorize the question.** Follow the decision tree in `CLAUDE.md` — motion/gesture/trail, timing/transition, existence/layout, or long-recall. Motion and timing categories require the drill pass and higher fps.

2. **Pick parameters.** Read the heuristics in `CLAUDE.md` and choose `fps`, `resolution_scale`, and `region` for the task. Start with the defaults from the decision tree; only deviate if you have specific reason.

3. **Start recording.** Call `mcp__claude_eyes__start_recording` with your chosen parameters. Save the returned `session_id` — you will need it for every subsequent call.

4. **Cue the user (if needed).** If the recording captures an action the user has to perform ("click the button", "scroll down"), tell them now, in one short sentence, and wait.

5. **Stop recording.** Call `mcp__claude_eyes__stop_recording(session_id)`. It returns the list of frame paths and metadata.

6. **Scan then drill** — optimise token spend on the subagent.

   **The drill pass is MANDATORY for motion/gesture/trail and timing/transition categories.** The preview image compresses time and cannot reveal order, smoothness, or shape evolution — answering from it is a bug. Even when the preview "seems to show" the answer, dispatch the drill pass on raw frames.

   For existence/layout and long-recall categories, the drill pass is recommended but optional if the preview is unambiguous.

   **If `frames_count < 30`**: pass `frame_paths` directly to the subagent, as before.

   **Otherwise** (frames_count ≥ 30, previews are attached to the `stop_recording` response):

   a. **Scan pass.** Dispatch `frame-analyzer` with ONLY `previews.items[*].preview_path`. Prompt it to identify which bucket indices contain the behaviour the user asked about, and to return a list of `bucket_index` values.

   b. **Drill pass.** Using the bucket indices the subagent returned, compute the subset of `frame_paths` whose indices fall inside any chosen bucket's `frame_range`. Dispatch `frame-analyzer` again with that filtered list and the original user question. Answer from the second report.

   If the first dispatch returns no interesting buckets, tell the user nothing notable happened in the recording. Do not dispatch a drill pass on an empty result.

7. **Cleanup.** Call `mcp__claude_eyes__cleanup_session(session_id)`. **Always.** Even if the analysis failed, even if the user interrupted, even if the subagent returned nothing useful.

8. **Retry once if the answer is uncertain.** If the subagent's response hedges ("I think", "probably", "hard to tell"), is under ~20 words for a qualitative question, or conflicts with a hint the user gave, retry with different parameters using the tactic priority in `CLAUDE.md § Retry protocol`. Cleanup the first session before starting the second. If the second attempt also fails, tell the user what you tried and ask for a specific hint.

9. **Answer the user.** Synthesize the subagent's report into a direct, concise answer. Do not paste the whole report — extract what matters for the question.

## Parameter selection quick reference

See `CLAUDE.md` for the full heuristics. Summary:

| Situation | `fps` | `resolution_scale` | `region` |
|---|---|---|---|
| Mouse gesture / cursor path | 25–30 | 0.75 | full or single monitor |
| OS / Chrome animation | 20–25 | 1.0 | tight bbox |
| Normal UI animation | 15–20 | 1.0 | tight bbox |
| UI walkthrough | 10 | 0.75 | tight bbox |
| Default | 10 | 0.75 | full |
| Layout-only check | 5 | 0.5 | full |
| Long recall | 2–3 | 0.75 | full |

### Preview modes (passed via `compose_timeline_preview` if the default doesn't help)

| Mode | Use when |
|---|---|
| `avg` (default) | General "state of the bucket" — static content stays readable, motion shows as soft trail. |
| `max` | Cursor trails, animation smoothness checks, UI with bright elements on dark background. |
| `motion` | Long recordings where the question is "when did something happen" — heatmap of change. |

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
- **Skipping the scan pass when `frames_count >= 30`.** Sending hundreds of raw frames to the subagent burns tokens for no reason. The scan pass is your coarse map.
- **Treating the preview as the answer.** The preview is always a scan tool. For motion/timing/trail questions, the drill pass is NOT OPTIONAL — even when the preview looks like it shows the answer.
- **Retrying with identical parameters after a failure.** If the first pass failed, change something meaningful (res_scale, region, preview mode) before retrying. Running the same capture again won't help.
- **Raising fps when `fps_effective < 50%`.** Under I/O bottleneck, raising fps trades disk thrash for zero extra frames. Lower `resolution_scale` or narrow `region` first.

## Active range (Spec 5)

`stop_recording` attaches `active_range: [first_idx, last_idx] | null`, `fps_effective: float`, and `activity_score_mean: float`. Use them to reduce token spend further and catch I/O bottlenecks.

**Before scan-then-drill:**

1. If `active_range` is not null, filter `frame_paths` to indices in `[first_idx, last_idx]` before scanning. A 400-frame recording with a 30-frame active range drops the scan input by ~90%.
2. If `active_range` is null, the algorithm found no activity above its adaptive threshold — fall back to the full `frame_paths` as before.

**Check `fps_effective`:**

- If `fps_effective < 0.8 × fps_nominal` (the value you passed to `start_recording`), warn the user: the capture is disk-I/O-bound. Suggest a lower `resolution_scale` or tighter `region` for the next recording.

**Optional: `trim_session`.**

After the analysis, if you want to free disk too (not just ignore dead frames in the subagent pass), call `mcp__claude_eyes__trim_session(session_id)`. This deletes everything outside `active_range` and regenerates previews. Never called automatically — ask yourself whether the dead frames might still be useful before trimming.

## Related

- Subagent: `.claude/agents/frame-analyzer.md`
- Project guidance: `CLAUDE.md`

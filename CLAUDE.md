# claudeEyes — project guidance

claudeEyes is an MCP server that gives you **visual awareness of what happens on screen over time**. You can record the screen at a chosen frame rate, then dispatch the `frame-analyzer` subagent to analyze the captured sequence.

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

## Parameter heuristics (for `start_recording`)

You choose these based on the task. Minimize for speed/disk; maximize only when needed.

### `fps` (frames per second, default 3)

| Task | Recommended fps |
|---|---|
| Slow UI transitions, layout changes | 2–3 |
| Normal animations | 5–8 |
| Fluid animations, interactions | 10–15 |
| Micro-stuttering / frame-drop debug | 20–30 |

### `resolution_scale` (0.1–1.0, default 1.0)

| Task | Recommended scale |
|---|---|
| Pixel-perfect detail, small text, fine glitches | 1.0 |
| Layout/color/shape analysis | 0.5 |
| Movement tracking, gross behavior | 0.25 |

### `region` (optional `(x, y, width, height)`)

Prefer a tight bbox whenever the task is localized (a button, a widget, a card). Full screen wastes disk and dilutes the subagent's attention. If the user describes a visible area, translate it to coordinates.

### `session_name` (optional)

Human-readable label for your own tracking. Defaults to auto-generated.

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

## Related files

- Subagent: `.claude/agents/frame-analyzer.md` — vision analysis instructions.
- Skill: `.claude/skills/analyze-screen/SKILL.md` — the orchestration workflow.
- Hooks: `.claude/settings.json` + `.claude/hooks/*.py` — cleanup & logging.
- MCP config: `.mcp.json` — registers the `claude_eyes` stdio server.

See @README.md for repository overview.

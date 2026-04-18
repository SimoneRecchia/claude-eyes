# claudeEyes

MCP server that gives Claude visual awareness of **what happens on screen over time**.

Claude gains the ability to record the screen at a configurable frame rate,
then dispatch a vision-capable subagent (`frame-analyzer`) to analyze the
captured sequence. Use cases: animation debugging, UI flow analysis,
time-based visual phenomena that a single screenshot cannot capture.

## Architecture

- **`claude_eyes` Python package** — deterministic logic: screen capture (`mss`),
  session lifecycle, frame storage/cleanup.
- **MCP server** (`claude_eyes.server`) — exposes 4 tools to Claude via stdio:
  `start_recording`, `stop_recording`, `list_frames`, `cleanup_session`.
- **Subagent** (`.claude/agents/frame-analyzer.md`) — vision analysis of frame sequences.
- **Skill** (`.claude/skills/analyze-screen/`) — orchestrates record → analyze → cleanup.
- **Hooks** (`.claude/hooks/`) — safety net cleanup, recording logs.

See [CLAUDE.md](CLAUDE.md) for how Claude uses the system.

## Status

All three planned specs shipped. 68 tests pass; mypy and ruff clean; real-screen smoke verified.

- **Foundation** (Spec 1) — Python MCP server, 4 on-demand tools (`start_recording` / `stop_recording` / `list_frames` / `cleanup_session`), `frame-analyzer` subagent, `analyze-screen` skill, hooks.
- **Continuous mode** (Spec 2) — rolling buffer with age + disk-cap pruning, 3 tools (`start_continuous_buffer` / `stop_continuous_buffer` / `query_buffer`), uniform-in-time sampling, privacy-guardrail hook, `review-recent-activity` skill.
- **Claude-in-Chrome integration** (Spec 3) — `region_dpr` param on `start_recording`, `analyze-page-animation` skill with six ready-to-use patterns + fallback decision tree, CLAUDE.md disambiguation.

Known limitation: `CLAUDE_EYES_INCLUDE_CURSOR=true` is accepted but cursor capture is still a no-op (warning logged on startup).

## Requirements

- Python 3.13+
- Windows / macOS / Linux (via `mss`)

## Install (dev)

```bash
pip install -e .[dev]
```

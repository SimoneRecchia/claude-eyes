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

Foundation scaffolding. Python implementation follows in the next plan.

## Requirements

- Python 3.13+
- Windows / macOS / Linux (via `mss`)

## Install (dev)

```bash
pip install -e .[dev]
```

# claude-eyes

[![CI](https://github.com/SimoneRecchia/claude-eyes/actions/workflows/ci.yml/badge.svg)](https://github.com/SimoneRecchia/claude-eyes/actions/workflows/ci.yml)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Checked with mypy](https://img.shields.io/badge/mypy-strict-1f5082.svg)](https://mypy-lang.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![MCP](https://img.shields.io/badge/MCP-compatible-6f42c1.svg)](https://modelcontextprotocol.io/)

MCP server that gives Claude **visual awareness of what happens on screen over time**.

A single screenshot answers "what is on screen right now". claude-eyes answers
"what changed on screen between T₀ and T₁" — animations, UI transitions,
loading states, drag/scroll interactions, reveal-on-scroll, media playback,
and anything else that only makes sense as a sequence of frames.

Claude records the screen at a chosen frame rate, then dispatches a
vision-capable subagent (`frame-analyzer`) to analyse the captured sequence.
Cleanup is mandatory and hook-enforced, so leftover frames don't accumulate
on disk.

---

## Mental model

| Use claude-eyes when… | Don't use it when… |
|---|---|
| the question is "what happens when…" | a single screenshot answers it |
| animation quality matters (smoothness, glitches) | the answer is in code or docs |
| UI unfolds over time (loading, transitions, drag) | the user didn't ask for a visual analysis |
| user interaction produces visible feedback | you're tempted to record pre-emptively |

Three skills encode the correct workflow — Claude reaches for these first
instead of calling the MCP tools directly:

- **`analyze-screen`** — desktop / OS UI / any non-browser app.
- **`analyze-page-animation`** — Chrome pages, coordinated with
  Claude-in-Chrome (DOM selectors, precise triggering).
- **`review-recent-activity`** — "what did I just do" queries against the
  rolling buffer (continuous mode).

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Main Claude (orchestration)                            │
│    ├─ invokes skill (analyze-screen / page-animation)   │
│    └─ calls MCP tools via stdio                         │
│                                                         │
│  claude_eyes MCP server (Python, deterministic)         │
│    ├─ screen capture (mss + Pillow)                     │
│    ├─ session lifecycle + frame storage                 │
│    ├─ continuous rolling buffer                         │
│    ├─ bucket-based preview composition (avg/max/motion) │
│    └─ active-range + fps-effective detection            │
│                                                         │
│  frame-analyzer subagent (vision)                       │
│    └─ reads frame paths, answers the user's question    │
└─────────────────────────────────────────────────────────┘
```

Strict separation: the Python package never makes AI calls, and the
subagent never does deterministic computation. The main agent orchestrates
both.

---

## MCP tools (9)

Grouped by use case. See [CLAUDE.md](CLAUDE.md) for parameter heuristics
and workflow rules.

**On-demand recording**
- `start_recording(fps, resolution_scale, region, region_dpr, session_name)`
  — begin capture; returns `session_id`.
- `stop_recording(session_id)` — end capture; returns frame paths,
  bucket previews, `active_range`, `fps_effective`, `activity_score_mean`.
- `list_frames(session_id)` — inspect a running or stopped session
  without ending it.
- `cleanup_session(session_id)` — mandatory teardown. A `SessionEnd` hook
  also wipes orphans as a safety net.

**Continuous rolling buffer**
- `start_continuous_buffer(fps, retention_s, resolution_scale)` — user
  starts it explicitly (privacy-guardrail hook reminds Claude).
- `stop_continuous_buffer()` — stops the background capture.
- `query_buffer(time_range_s, max_frames)` — return sampled frames plus
  previews and activity metadata for the requested window.

**Post-capture**
- `compose_timeline_preview(session_id, bucket_s, mode)` — rebuild
  previews with a different bucket size or blend mode (`avg` / `max` /
  `motion`) when the default doesn't surface the behaviour.
- `trim_session(session_id)` — opt-in destructive trim: delete frames
  outside the detected `active_range` and regenerate previews.

All tools return structured errors (`{"error": "..."}`) instead of raising,
so the agent loop never crashes on a bad session id.

---

## Status

All five planned specs shipped. **113 tests pass**; mypy and ruff clean;
real-screen smoke verified on Windows 11.

- **Foundation** (Spec 1) — MCP server, 4 on-demand tools,
  `frame-analyzer` subagent, `analyze-screen` skill, cleanup hooks.
- **Continuous mode** (Spec 2) — rolling buffer with age + disk-cap
  pruning, 3 buffer tools, uniform-in-time sampling, privacy-guardrail
  hook, `review-recent-activity` skill.
- **Claude-in-Chrome integration** (Spec 3) — `region_dpr` param,
  `analyze-page-animation` skill with six ready-to-use patterns plus a
  fallback decision tree, CLAUDE.md disambiguation.
- **Scan-then-drill** (Spec 4) — bucket-composited previews attached to
  `stop_recording` / `query_buffer`, new `compose_timeline_preview` tool,
  two-pass subagent workflow to slash token spend on long recordings.
- **Capture intelligence** (Spec 5) — post-capture activity detection:
  `active_range` brackets the motion window, `fps_effective` flags
  I/O-bound captures, `activity_score_mean` as a diagnostic field, new
  opt-in `trim_session` tool.

---

## Skills

Three skills live under `.claude/skills/`; each encodes the correct
end-to-end workflow for its situation. The skills are Claude's entry
point — they call the MCP tools in the right order and guarantee
cleanup.

| Skill | Context | Trigger |
|---|---|---|
| `analyze-screen` | Desktop / OS UI / any app | Time-based behaviour outside a browser. |
| `analyze-page-animation` | Chrome page via Claude-in-Chrome | Specific animation or interaction on a page. |
| `review-recent-activity` | Anywhere, user started the rolling buffer | "What did I just do", "cosa è successo negli ultimi minuti". |

---

## Requirements

- Python 3.13+
- Windows / macOS / Linux (via `mss`)
- A Claude client that speaks MCP (Claude Code, Claude Desktop, or any
  stdio-capable harness)

## Install

### As a Claude Code plugin (recommended — one command)

```
/plugin marketplace add SimoneRecchia/claude-eyes
/plugin install claude-eyes@claude-eyes
```

That's it. Claude Code downloads the plugin, registers the MCP server,
loads the three skills (namespaced as `/claude-eyes:analyze-screen`,
`/claude-eyes:analyze-page-animation`, `/claude-eyes:review-recent-activity`),
the vision subagent, and the hooks.

**Prerequisite:** [`uv`](https://docs.astral.sh/uv/) must be on your
`PATH`. The plugin launches its Python MCP server via `uvx`, which
auto-installs Python 3.13 and the project's dependencies in an
isolated environment on first run — no manual `pip install`, no venv.

If `uv` is missing when you start a session, a hook will tell you how
to install it:

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### From source (for contributors)

```bash
git clone https://github.com/SimoneRecchia/claude-eyes
cd claude-eyes
python -m venv .venv
.venv/Scripts/activate   # or `source .venv/bin/activate` on macOS/Linux
pip install -e .[dev]
```

The repo ships a working `.mcp.json` at the root that registers the
server using the local `.venv`. Open the repo in Claude Code and the
MCP server, skills, agents, and hooks all load from the local tree —
no plugin install needed for development.

---

## Configuration

All configuration is environment-variable based and read once at server
startup. Every variable has a sane default, so zero config works.

| Variable | Default | Purpose |
|---|---|---|
| `CLAUDE_EYES_MONITOR` | `0` | `mss` monitor index (0 = all, 1 = primary, …). |
| `CLAUDE_EYES_INCLUDE_CURSOR` | `false` | Currently a no-op; flag reserved for a future cursor-compositing pass. |
| `CLAUDE_EYES_SESSIONS_DIR` | `sessions` | Root directory where session frames are written. |
| `CLAUDE_EYES_CONTINUOUS_FPS` | `2` | Frame rate of the rolling buffer. |
| `CLAUDE_EYES_RETENTION_S` | `300` | Rolling-buffer age cap (seconds). |
| `CLAUDE_EYES_CONTINUOUS_RESOLUTION_SCALE` | `0.75` | Capture scale for the rolling buffer. |
| `CLAUDE_EYES_DISK_CAP_MB` | `1024` | Rolling-buffer hard disk cap. Oldest frames pruned first. |

---

## Development

```bash
# Full test suite
.venv/Scripts/python.exe -m pytest -q

# Type check
.venv/Scripts/python.exe -m mypy src/claude_eyes

# Lint
.venv/Scripts/python.exe -m ruff check src tests
```

All three must pass before merge. 113 tests run in ~22 s.

---

## Project layout

```
src/claude_eyes/
├── server.py          # FastMCP stdio server + 9 tool endpoints
├── recorder.py        # Threaded capture loop, fps pacing, region crop
├── continuous.py      # Rolling-buffer handle + frame sampling
├── storage.py         # Session dir layout, frame list, cleanup
├── session.py         # Registry (persisted across process restarts)
├── compose.py         # Bucketed previews (avg / max / motion)
├── activity.py        # Motion scoring, adaptive threshold, active-range
└── config.py          # Env-var parsing + internal constants

.claude/
├── agents/frame-analyzer.md      # Vision subagent
├── skills/                       # Three orchestration skills
├── hooks/                        # Cleanup + privacy reminder + logs
└── settings.json                 # Hook registrations

tests/                            # 113 tests, deterministic (fake mss)
docs/superpowers/specs/           # Design documents for each spec
docs/superpowers/plans/           # Implementation plans (task checklists)
CLAUDE.md                         # Project guidance for Claude
```

---

## Known limitations

- `CLAUDE_EYES_INCLUDE_CURSOR=true` is accepted but cursor capture is
  still a no-op (a warning is logged on startup).
- Full-screen 1080p capture at 25+ fps can become disk-I/O-bound —
  `fps_effective` will surface this; drop `resolution_scale` or tighten
  `region` to recover.
- The continuous buffer is not tab-scoped; it captures whichever monitor
  `CLAUDE_EYES_MONITOR` points at.

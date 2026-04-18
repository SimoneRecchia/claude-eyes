# Security Policy

claudeEyes records your screen on demand. That makes its security posture
matter more than for most MCP servers. This document spells out what the
tool does with that data, what it does **not** do, and how to report
issues.

## What claudeEyes does with captured frames

- **Frames are written to local disk only.** Default location is
  `sessions/` under the repository working directory, configurable via
  `CLAUDE_EYES_SESSIONS_DIR`.
- **No network activity.** The package does not open sockets, contact
  remote servers, send telemetry, or upload frames anywhere. The only
  I/O is `mss` reading pixels and `Pillow` writing JPEGs.
- **Frames are read by the `frame-analyzer` subagent** — which runs
  inside the same Claude session the user invoked. The analyser sees
  frame file paths, opens the JPEGs, and answers the user's question.
  Whatever the Claude provider does with vision inputs is out of scope
  for this project (see the provider's privacy policy).
- **`cleanup_session` deletes the session folder.** A `SessionEnd`
  hook (`.claude/hooks/cleanup_orphan_sessions.py`) is registered to
  wipe any session still on disk when Claude Code exits. This is a
  safety net — the agent is also supposed to call `cleanup_session`
  explicitly after each analysis.
- **The continuous rolling buffer is explicitly gated.** It only
  starts when the user asks for it, a privacy-guardrail hook injects
  a reminder when it does, and it self-prunes by age and disk cap so
  it cannot silently fill the disk.

## Threat model

| Threat | How claudeEyes handles it |
|---|---|
| Malicious MCP client instructs Claude to record without user consent | Tool calls are visible in the Claude Code transcript and `start_continuous_buffer` fires a user-facing reminder hook. No tool starts recording without the agent calling it, and the agent is instructed (via `CLAUDE.md`) never to record pre-emptively. |
| Attacker reads old session frames from disk | Frames live under user-owned filesystem permissions. Use OS-level access controls. `cleanup_session` + the `SessionEnd` hook limit the window in which stale frames exist. |
| Prompt-injection payload in a captured frame ("ignore previous instructions…") | The subagent is a vision model analysing images; the main agent's system prompt and `CLAUDE.md` include instruction-injection defenses. Still, users should avoid recording screens that contain obviously hostile content. |
| Resource exhaustion (disk) from a recording that never stops | `SAFETY_CAP_SECONDS` (30 min) hard-stops on-demand recordings. The continuous buffer enforces both an age cap (`retention_s`) and a disk cap (`disk_cap_mb`). |
| Third party on the same machine reads frames mid-recording | Out of scope — claudeEyes assumes a single-user local environment. Do not run it on a shared host. |

## What is explicitly out of scope

- Encrypting frames at rest. They are plain JPEGs.
- Redacting sensitive regions of the screen. The user chooses the capture
  region; whatever is in that region is captured verbatim.
- Multi-user / shared-host deployments.
- Hardening against a compromised Python environment or a modified MCP
  client — if an attacker can already run code as your user, they don't
  need claudeEyes to see your screen.

## Reporting a vulnerability

If you find a security issue, please **do not open a public GitHub issue**.
Instead, email the maintainer directly — use the email visible on the
[GitHub profile](https://github.com/SimoneRecchia). Include:

- A description of the issue and why you believe it's a security concern.
- Steps to reproduce (ideally a minimal PoC).
- The claudeEyes version (git SHA) you tested against.
- Your preferred disclosure timeline, if any.

You'll get an acknowledgement within a few days. If the issue is
confirmed, a fix will be prepared on a private branch, released, and
then disclosed publicly with credit (unless you prefer anonymity).

## Supported versions

This project is pre-1.0. Only the latest commit on `main` receives
security updates.

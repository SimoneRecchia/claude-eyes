#!/usr/bin/env python3
"""PostToolUse hook for ``mcp__claude_eyes__stop_recording``.

Logs structured metadata about each completed recording to
``.claude/logs/recordings.jsonl`` and injects an ``additionalContext``
reminder to the main agent to call ``cleanup_session`` once analysis
is done.

Exit code is always 0 (non-blocking). On malformed input the hook
exits silently — it must never break the agent's flow.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", "."))
    log_dir = project_dir / ".claude" / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"[claude-eyes] cannot create log dir: {exc}", file=sys.stderr)
        return 0

    tool_input = payload.get("tool_input") or {}
    tool_response = payload.get("tool_response") or {}
    session_id = tool_input.get("session_id") or tool_response.get("session_id")

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "frames_count": tool_response.get("frames_count"),
        "duration_s": tool_response.get("duration_s"),
        "frames_dir": tool_response.get("frames_dir"),
    }

    try:
        with (log_dir / "recordings.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError as exc:
        print(f"[claude-eyes] log write failed: {exc}", file=sys.stderr)

    reminder = (
        f"[claude-eyes] Recording session '{session_id}' stopped. "
        "Remember to call mcp__claude_eyes__cleanup_session after the "
        "frame-analyzer subagent has finished."
    )
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": reminder,
        }
    }
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())

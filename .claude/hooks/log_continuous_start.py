#!/usr/bin/env python3
"""PostToolUse hook for ``mcp__claude_eyes__start_continuous_buffer``.

Logs the event to ``.claude/logs/continuous.jsonl`` and injects an
``additionalContext`` reminder so Claude tells the user that their screen
is now being recorded continuously (privacy guardrail).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
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

    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "event": "continuous_buffer_started",
        "fps": tool_input.get("fps"),
        "retention_s": tool_input.get("retention_s"),
        "resolution_scale": tool_input.get("resolution_scale"),
        "started_at": tool_response.get("started_at"),
    }

    try:
        with (log_dir / "continuous.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError as exc:
        print(f"[claude-eyes] log write failed: {exc}", file=sys.stderr)

    reminder = (
        "[claude-eyes] The continuous screen buffer is now ACTIVE. "
        "You MUST tell the user in your next response that their screen is "
        "being recorded continuously, and remind them they can stop it with "
        "stop_continuous_buffer at any time."
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

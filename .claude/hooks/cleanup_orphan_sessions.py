#!/usr/bin/env python3
"""SessionEnd hook — cleanup orphan claudeEyes recording sessions.

Runs when the Claude Code session ends. Removes any recording session
folders left behind in ``sessions/`` because the main agent forgot to
call ``cleanup_session``. Safety net only — the main agent is still
expected to clean up after every analysis.

Exit code is always 0 (non-blocking). Errors are logged to stderr.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def main() -> None:
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", "."))
    sessions_dir = project_dir / "sessions"

    if not sessions_dir.is_dir():
        return

    removed = 0
    errors: list[str] = []
    for entry in sessions_dir.iterdir():
        if not entry.is_dir():
            continue
        try:
            shutil.rmtree(entry)
            removed += 1
        except OSError as exc:
            errors.append(f"{entry.name}: {exc}")

    if removed:
        print(
            f"[claudeEyes] SessionEnd cleanup: removed {removed} orphan session(s).",
            file=sys.stderr,
        )
    for err in errors:
        print(f"[claudeEyes] cleanup failed: {err}", file=sys.stderr)


if __name__ == "__main__":
    main()
    sys.exit(0)

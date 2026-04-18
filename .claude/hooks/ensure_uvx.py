#!/usr/bin/env python3
"""SessionStart hook: verify ``uvx`` is on PATH.

When claudeEyes is installed as a Claude Code plugin, its MCP server is
launched via ``uvx --from git+https://github.com/SimoneRecchia/claudeEyes
claude-eyes``. That requires ``uv`` (which ships ``uvx``) to be
installed on the user's machine.

This hook runs once per session start. If ``uvx`` is present, it exits
silently. If missing, it injects an ``additionalContext`` reminder so
Claude can tell the user how to install ``uv`` before the first MCP
tool call fails with a less helpful error.

The hook never installs ``uv`` itself — user consent is required for
any external software install.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import sys


def _uv_install_instructions() -> str:
    return (
        "[claudeEyes] I noticed ``uvx`` is not available on this system. "
        "The claudeEyes plugin uses ``uv`` to run its Python MCP server "
        "without any manual setup. Please install ``uv`` with one of:\n\n"
        "  macOS / Linux:  curl -LsSf https://astral.sh/uv/install.sh | sh\n"
        "  Windows:        powershell -c \"irm https://astral.sh/uv/install.ps1 | iex\"\n\n"
        "After installing, restart Claude Code. Until then, the claudeEyes "
        "MCP tools will not be callable. Please tell the user about this "
        "in your next response."
    )


def main() -> int:
    # Drain stdin so Claude Code doesn't block on the pipe.
    with contextlib.suppress(OSError):
        sys.stdin.read()

    if shutil.which("uvx") is not None:
        return 0

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": _uv_install_instructions(),
        }
    }
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())

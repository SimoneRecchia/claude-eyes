"""Shared pytest fixtures for claude-eyes."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def sessions_dir(tmp_path: Path) -> Path:
    """A throwaway sessions/ directory for a single test."""
    d = tmp_path / "sessions"
    d.mkdir()
    return d

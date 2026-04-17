# claudeEyes Foundation — Python MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Python side of claudeEyes — an MCP server exposing four deterministic tools (`start_recording`, `stop_recording`, `list_frames`, `cleanup_session`) that capture screen frames and manage sessions on disk.

**Architecture:** A single Python package `claude_eyes` split by responsibility: `config` (defaults + env), `session` (session model + JSON registry), `storage` (frame file layout), `recorder` (background thread around `mss`), `server` (FastMCP app wiring tools to the above). No AI calls from Python — visual analysis lives in the `frame-analyzer` subagent dispatched by the main Claude agent.

**Tech Stack:** Python 3.13, `mcp>=1.0` (FastMCP / stdio), `mss>=9.0`, `Pillow>=10.0`, `pytest`, `pytest-asyncio`, `ruff`, `mypy`.

**Prerequisite:** branch `feat/foundation` already has scaffold (CLAUDE.md, subagent, skill, hooks, `pyproject.toml`, `src/claude_eyes/__init__.py`, `src/claude_eyes/server.py` stub, `.mcp.json`). All work below happens on this branch.

---

## File structure to create

```
src/claude_eyes/
├── __init__.py            # exists — leave alone
├── config.py              # Task 1 — constants + ServerConfig
├── session.py             # Task 2-3 — RecordingSession + SessionRegistry
├── storage.py             # Task 4 — frame save/list/cleanup
├── recorder.py            # Task 5 — background-thread screen capture
└── server.py              # Task 6-9 — replaces current stub, FastMCP app

tests/
├── __init__.py            # Task 0 — empty
├── conftest.py            # Task 0 — shared fixtures
├── test_config.py         # Task 1
├── test_session.py        # Task 2-3
├── test_storage.py        # Task 4
├── test_recorder.py       # Task 5
└── test_server.py         # Task 6-10 — integration
```

---

## Task 0: Install deps and create test scaffold

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Install the project in editable mode with dev extras**

Run:
```bash
.venv/Scripts/python.exe -m pip install -e ".[dev]"
```
Expected: ends with `Successfully installed claude-eyes-0.1.0 ...` plus pytest / mss / mcp / Pillow / ruff / mypy.

- [ ] **Step 2: Create `tests/__init__.py` (empty file)**

```python
```
(zero bytes is fine, just ensures pytest treats `tests/` as a package)

- [ ] **Step 3: Create `tests/conftest.py` with a shared `sessions_dir` fixture**

```python
"""Shared pytest fixtures for claudeEyes."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def sessions_dir(tmp_path: Path) -> Path:
    """A throwaway sessions/ directory for a single test."""
    d = tmp_path / "sessions"
    d.mkdir()
    return d
```

- [ ] **Step 4: Verify pytest discovers the suite (0 tests, no errors)**

Run:
```bash
.venv/Scripts/python.exe -m pytest -q
```
Expected: `no tests ran` (exit 5) or `0 passed`. No collection errors.

- [ ] **Step 5: Commit**

```bash
git add tests/__init__.py tests/conftest.py
git commit -m "test: add pytest scaffold and shared fixtures"
```

---

## Task 1: Config module

**Files:**
- Create: `src/claude_eyes/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py`:
```python
"""Tests for claude_eyes.config."""
from __future__ import annotations

from pathlib import Path

import pytest

from claude_eyes.config import (
    DEFAULT_FPS,
    DEFAULT_RESOLUTION_SCALE,
    JPEG_QUALITY,
    SAFETY_CAP_SECONDS,
    ServerConfig,
)


def test_internal_constants_have_expected_defaults() -> None:
    assert DEFAULT_FPS == 3
    assert DEFAULT_RESOLUTION_SCALE == 1.0
    assert JPEG_QUALITY == 85
    assert SAFETY_CAP_SECONDS == 30 * 60


def test_server_config_defaults_when_env_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAUDE_EYES_MONITOR", raising=False)
    monkeypatch.delenv("CLAUDE_EYES_INCLUDE_CURSOR", raising=False)
    monkeypatch.delenv("CLAUDE_EYES_SESSIONS_DIR", raising=False)

    cfg = ServerConfig.from_env()

    assert cfg.monitor == 0
    assert cfg.include_cursor is False
    assert cfg.sessions_dir == Path("sessions")


def test_server_config_reads_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CLAUDE_EYES_MONITOR", "2")
    monkeypatch.setenv("CLAUDE_EYES_INCLUDE_CURSOR", "true")
    monkeypatch.setenv("CLAUDE_EYES_SESSIONS_DIR", str(tmp_path / "custom"))

    cfg = ServerConfig.from_env()

    assert cfg.monitor == 2
    assert cfg.include_cursor is True
    assert cfg.sessions_dir == tmp_path / "custom"


@pytest.mark.parametrize("value,expected", [
    ("true", True), ("True", True), ("TRUE", True),
    ("false", False), ("False", False), ("0", False), ("", False),
])
def test_include_cursor_env_parsing(monkeypatch: pytest.MonkeyPatch, value: str, expected: bool) -> None:
    monkeypatch.setenv("CLAUDE_EYES_INCLUDE_CURSOR", value)
    cfg = ServerConfig.from_env()
    assert cfg.include_cursor is expected
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_config.py -v
```
Expected: `ModuleNotFoundError: No module named 'claude_eyes.config'` (collection error).

- [ ] **Step 3: Write the implementation**

`src/claude_eyes/config.py`:
```python
"""claudeEyes configuration — internal constants and user-controlled env overrides."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Internal constants — not exposed as tool parameters.
JPEG_QUALITY: int = 85
SAFETY_CAP_SECONDS: int = 30 * 60  # anti-runaway recording cap
DEFAULT_FPS: int = 3
DEFAULT_RESOLUTION_SCALE: float = 1.0


def _parse_bool(value: str) -> bool:
    return value.strip().lower() == "true"


@dataclass(frozen=True)
class ServerConfig:
    """User-controlled config, read once from env vars at server startup."""

    monitor: int = 0
    include_cursor: bool = False
    sessions_dir: Path = Path("sessions")

    @classmethod
    def from_env(cls) -> "ServerConfig":
        return cls(
            monitor=int(os.environ.get("CLAUDE_EYES_MONITOR", "0")),
            include_cursor=_parse_bool(os.environ.get("CLAUDE_EYES_INCLUDE_CURSOR", "false")),
            sessions_dir=Path(os.environ.get("CLAUDE_EYES_SESSIONS_DIR", "sessions")),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_config.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/claude_eyes/config.py tests/test_config.py
git commit -m "feat(config): add ServerConfig and module constants"
```

---

## Task 2: RecordingSession dataclass

**Files:**
- Create: `src/claude_eyes/session.py`
- Create: `tests/test_session.py`

- [ ] **Step 1: Write the failing tests for the dataclass**

`tests/test_session.py`:
```python
"""Tests for claude_eyes.session."""
from __future__ import annotations

from pathlib import Path

from claude_eyes.session import RecordingSession


def test_create_session_generates_id_and_frames_dir(sessions_dir: Path) -> None:
    s = RecordingSession.create(
        name="",
        fps=5,
        resolution_scale=0.5,
        region=None,
        monitor=0,
        include_cursor=False,
        sessions_dir=sessions_dir,
    )

    assert s.session_id.startswith("sess_")
    assert len(s.session_id) == len("sess_") + 12
    assert s.name == s.session_id  # empty name falls back to id
    assert s.fps == 5
    assert s.resolution_scale == 0.5
    assert s.region is None
    assert s.stopped_at is None
    assert s.frames_count == 0
    assert s.frames_dir == str(sessions_dir / s.session_id)
    assert s.started_at.endswith("+00:00")  # UTC ISO


def test_create_session_preserves_explicit_name(sessions_dir: Path) -> None:
    s = RecordingSession.create(
        name="button-click",
        fps=3, resolution_scale=1.0, region=(10, 20, 30, 40),
        monitor=1, include_cursor=True, sessions_dir=sessions_dir,
    )

    assert s.name == "button-click"
    assert s.region == (10, 20, 30, 40)
    assert s.monitor == 1
    assert s.include_cursor is True


def test_session_to_dict_roundtrips(sessions_dir: Path) -> None:
    s = RecordingSession.create(
        name="x", fps=4, resolution_scale=1.0, region=None,
        monitor=0, include_cursor=False, sessions_dir=sessions_dir,
    )
    d = s.to_dict()
    s2 = RecordingSession(**d)
    assert s == s2
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_session.py -v
```
Expected: `ModuleNotFoundError: No module named 'claude_eyes.session'`.

- [ ] **Step 3: Write the implementation**

`src/claude_eyes/session.py`:
```python
"""Recording session model + JSON-backed registry."""
from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _make_id() -> str:
    return "sess_" + secrets.token_hex(6)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RecordingSession:
    session_id: str
    name: str
    fps: int
    resolution_scale: float
    region: tuple[int, int, int, int] | None
    monitor: int
    include_cursor: bool
    started_at: str
    stopped_at: str | None = None
    frames_count: int = 0
    frames_dir: str = ""

    @classmethod
    def create(
        cls,
        *,
        name: str,
        fps: int,
        resolution_scale: float,
        region: tuple[int, int, int, int] | None,
        monitor: int,
        include_cursor: bool,
        sessions_dir: Path,
    ) -> "RecordingSession":
        sid = _make_id()
        return cls(
            session_id=sid,
            name=name or sid,
            fps=fps,
            resolution_scale=resolution_scale,
            region=tuple(region) if region is not None else None,
            monitor=monitor,
            include_cursor=include_cursor,
            started_at=utc_now_iso(),
            frames_dir=str(sessions_dir / sid),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if data["region"] is not None:
            data["region"] = list(data["region"])  # JSON-safe
        return data
```

Note about `to_dict`: dataclass `asdict` converts tuples to lists when going through JSON; the test above does not use JSON, it reconstructs via `RecordingSession(**d)`. That works because the constructor accepts a list and stores it — but the equality check will fail if we convert region to list. Keep `region` as a tuple in `to_dict` by reverting.

Revised `to_dict`:
```python
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_session.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/claude_eyes/session.py tests/test_session.py
git commit -m "feat(session): add RecordingSession dataclass"
```

---

## Task 3: SessionRegistry

**Files:**
- Modify: `src/claude_eyes/session.py` (append `SessionRegistry`)
- Modify: `tests/test_session.py` (append registry tests)

- [ ] **Step 1: Add failing registry tests**

Append to `tests/test_session.py`:
```python
import pytest

from claude_eyes.session import SessionRegistry


def _make(sessions_dir: Path, name: str = "x") -> RecordingSession:
    return RecordingSession.create(
        name=name, fps=3, resolution_scale=1.0, region=None,
        monitor=0, include_cursor=False, sessions_dir=sessions_dir,
    )


def test_registry_add_get_remove(sessions_dir: Path) -> None:
    reg = SessionRegistry(sessions_dir)
    s = _make(sessions_dir)

    reg.add(s)

    assert reg.get(s.session_id) == s
    assert reg.all() == [s]

    reg.remove(s.session_id)

    assert reg.get(s.session_id) is None
    assert reg.all() == []


def test_registry_persists_across_instances(sessions_dir: Path) -> None:
    reg1 = SessionRegistry(sessions_dir)
    s = _make(sessions_dir, name="persisted")
    reg1.add(s)

    reg2 = SessionRegistry(sessions_dir)

    assert reg2.get(s.session_id) == s


def test_registry_update_changes_fields(sessions_dir: Path) -> None:
    reg = SessionRegistry(sessions_dir)
    s = _make(sessions_dir)
    reg.add(s)

    s.frames_count = 42
    s.stopped_at = "2026-01-01T00:00:00+00:00"
    reg.update(s)

    reg2 = SessionRegistry(sessions_dir)
    loaded = reg2.get(s.session_id)
    assert loaded is not None
    assert loaded.frames_count == 42
    assert loaded.stopped_at == "2026-01-01T00:00:00+00:00"


def test_registry_tolerates_corrupt_json(sessions_dir: Path) -> None:
    (sessions_dir / ".registry.json").write_text("{not json", encoding="utf-8")
    reg = SessionRegistry(sessions_dir)  # must not raise
    assert reg.all() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_session.py -v
```
Expected: 4 failures with `ImportError: cannot import name 'SessionRegistry'`.

- [ ] **Step 3: Append `SessionRegistry` to `src/claude_eyes/session.py`**

```python
class SessionRegistry:
    """JSON-backed registry of recording sessions.

    Persists to ``<sessions_dir>/.registry.json`` so that a server restart
    preserves session metadata (frame data on disk is the source of truth
    for frames themselves).
    """

    def __init__(self, sessions_dir: Path) -> None:
        self.sessions_dir = sessions_dir
        self.registry_path = sessions_dir / ".registry.json"
        self._data: dict[str, RecordingSession] = {}
        self._load()

    def _load(self) -> None:
        if not self.registry_path.is_file():
            return
        try:
            raw = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, dict):
            return
        for sid, item in raw.items():
            if not isinstance(item, dict):
                continue
            region = item.get("region")
            if isinstance(region, list):
                item["region"] = tuple(region)
            try:
                self._data[sid] = RecordingSession(**item)
            except TypeError:
                continue

    def _save(self) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        payload = {sid: sess.to_dict() for sid, sess in self._data.items()}
        # tuples aren't JSON-native; convert for storage only
        for sess in payload.values():
            if sess.get("region") is not None:
                sess["region"] = list(sess["region"])
        self.registry_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def add(self, session: RecordingSession) -> None:
        self._data[session.session_id] = session
        self._save()

    def get(self, session_id: str) -> RecordingSession | None:
        return self._data.get(session_id)

    def update(self, session: RecordingSession) -> None:
        self._data[session.session_id] = session
        self._save()

    def remove(self, session_id: str) -> None:
        self._data.pop(session_id, None)
        self._save()

    def all(self) -> list[RecordingSession]:
        return list(self._data.values())
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_session.py -v
```
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/claude_eyes/session.py tests/test_session.py
git commit -m "feat(session): add JSON-backed SessionRegistry"
```

---

## Task 4: Frame storage

**Files:**
- Create: `src/claude_eyes/storage.py`
- Create: `tests/test_storage.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_storage.py`:
```python
"""Tests for claude_eyes.storage."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from claude_eyes.storage import (
    cleanup_session_dir,
    frame_filename,
    list_frames,
    save_frame,
)


def _img(color: tuple[int, int, int] = (255, 0, 0)) -> Image.Image:
    return Image.new("RGB", (10, 10), color)


def test_frame_filename_format() -> None:
    assert frame_filename(0, 0) == "frame_00000_0000000000.jpg"
    assert frame_filename(42, 1234) == "frame_00042_0000001234.jpg"


def test_save_frame_writes_jpeg(tmp_path: Path) -> None:
    sess = tmp_path / "s1"
    p = save_frame(sess, index=0, timestamp_ms=0, image=_img())

    assert p.exists()
    assert p.suffix == ".jpg"
    assert p.stat().st_size > 0
    # re-open to confirm it's a valid JPEG
    reopened = Image.open(p)
    assert reopened.size == (10, 10)
    assert reopened.format == "JPEG"


def test_list_frames_returns_sorted_metadata(tmp_path: Path) -> None:
    sess = tmp_path / "s2"
    save_frame(sess, 2, 700, _img())
    save_frame(sess, 0, 100, _img())
    save_frame(sess, 1, 400, _img())

    frames = list_frames(sess)

    assert [f["index"] for f in frames] == [0, 1, 2]
    assert [f["timestamp_ms"] for f in frames] == [100, 400, 700]
    for f in frames:
        assert Path(f["path"]).exists()


def test_list_frames_empty_for_missing_dir(tmp_path: Path) -> None:
    assert list_frames(tmp_path / "nope") == []


def test_cleanup_session_dir_removes_and_reports_bytes(tmp_path: Path) -> None:
    sess = tmp_path / "s3"
    save_frame(sess, 0, 0, _img())
    save_frame(sess, 1, 100, _img())
    assert sess.exists()

    freed = cleanup_session_dir(sess)

    assert freed > 0
    assert not sess.exists()


def test_cleanup_session_dir_missing_is_noop(tmp_path: Path) -> None:
    assert cleanup_session_dir(tmp_path / "never-existed") == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_storage.py -v
```
Expected: `ModuleNotFoundError: No module named 'claude_eyes.storage'`.

- [ ] **Step 3: Write the implementation**

`src/claude_eyes/storage.py`:
```python
"""Frame file layout on disk + cleanup."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import TypedDict

from PIL import Image

from .config import JPEG_QUALITY


class FrameInfo(TypedDict):
    path: str
    index: int
    timestamp_ms: int


def frame_filename(index: int, timestamp_ms: int) -> str:
    return f"frame_{index:05d}_{timestamp_ms:010d}.jpg"


def save_frame(
    session_dir: Path,
    index: int,
    timestamp_ms: int,
    image: Image.Image,
) -> Path:
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / frame_filename(index, timestamp_ms)
    image.save(path, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return path


def list_frames(session_dir: Path) -> list[FrameInfo]:
    if not session_dir.is_dir():
        return []
    out: list[FrameInfo] = []
    for p in sorted(session_dir.glob("frame_*.jpg")):
        parts = p.stem.split("_")
        if len(parts) != 3:
            continue
        try:
            idx = int(parts[1])
            ts = int(parts[2])
        except ValueError:
            continue
        out.append({"path": str(p), "index": idx, "timestamp_ms": ts})
    return out


def cleanup_session_dir(session_dir: Path) -> int:
    """Remove session_dir recursively. Returns total bytes freed.

    If the directory does not exist, returns 0.
    """
    if not session_dir.is_dir():
        return 0
    total = sum(f.stat().st_size for f in session_dir.rglob("*") if f.is_file())
    shutil.rmtree(session_dir)
    return total
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_storage.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/claude_eyes/storage.py tests/test_storage.py
git commit -m "feat(storage): add frame save/list/cleanup helpers"
```

---

## Task 5: Screen recorder (background thread)

**Files:**
- Create: `src/claude_eyes/recorder.py`
- Create: `tests/test_recorder.py`

- [ ] **Step 1: Write the failing tests using a fake mss backend**

`tests/test_recorder.py`:
```python
"""Tests for claude_eyes.recorder — use a fake mss backend to avoid real screen capture."""
from __future__ import annotations

import time
from pathlib import Path

import pytest


class _FakeScreenshot:
    """Mimics mss.base.ScreenShot — `rgb` is raw RGB bytes, `size` is (w, h)."""

    def __init__(self, w: int = 8, h: int = 8) -> None:
        self.size = (w, h)
        self.rgb = b"\x7f" * (w * h * 3)


class _FakeMSS:
    """Context-manager replacement for `mss.mss()`."""

    def __init__(self) -> None:
        self.monitors = [
            {"left": 0, "top": 0, "width": 8, "height": 8},
            {"left": 0, "top": 0, "width": 8, "height": 8},
        ]

    def __enter__(self) -> "_FakeMSS":
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def grab(self, _monitor: dict) -> _FakeScreenshot:
        return _FakeScreenshot()


@pytest.fixture
def fake_mss(monkeypatch: pytest.MonkeyPatch) -> None:
    import claude_eyes.recorder as rec_mod

    monkeypatch.setattr(rec_mod.mss, "mss", _FakeMSS)


def test_recorder_captures_frames_at_target_fps(tmp_path: Path, fake_mss: None) -> None:
    from claude_eyes.recorder import start_recorder, stop_recorder

    sess = tmp_path / "rec1"
    handle = start_recorder(
        session_dir=sess, fps=10, resolution_scale=1.0,
        region=None, monitor_index=0,
    )
    time.sleep(0.55)  # ~5 ticks at 10 fps
    count = stop_recorder(handle)

    assert 3 <= count <= 8, f"unexpected frame count: {count}"
    saved = sorted(sess.glob("frame_*.jpg"))
    assert len(saved) == count


def test_recorder_honours_region_and_scale(tmp_path: Path, fake_mss: None) -> None:
    from claude_eyes.recorder import start_recorder, stop_recorder

    sess = tmp_path / "rec2"
    handle = start_recorder(
        session_dir=sess, fps=20, resolution_scale=0.5,
        region=(0, 0, 8, 8), monitor_index=0,
    )
    time.sleep(0.25)
    stop_recorder(handle)

    files = list(sess.glob("frame_*.jpg"))
    assert files, "expected at least one frame"
    # Scaled down to 4x4 — just confirm the file is a JPEG (PIL will not
    # accept a 0x0 image, so any readable JPEG is enough).
    from PIL import Image as _I
    with _I.open(files[0]) as img:
        assert img.size == (4, 4)


def test_stop_recorder_returns_zero_when_stopped_immediately(
    tmp_path: Path, fake_mss: None
) -> None:
    from claude_eyes.recorder import start_recorder, stop_recorder

    handle = start_recorder(
        session_dir=tmp_path / "rec3", fps=3, resolution_scale=1.0,
        region=None, monitor_index=0,
    )
    count = stop_recorder(handle, timeout=2.0)
    assert count >= 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_recorder.py -v
```
Expected: `ModuleNotFoundError: No module named 'claude_eyes.recorder'`.

- [ ] **Step 3: Write the implementation**

`src/claude_eyes/recorder.py`:
```python
"""Screen capture worker — runs in a daemon thread around ``mss``."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

import mss
from PIL import Image

from .config import SAFETY_CAP_SECONDS
from .storage import save_frame


@dataclass
class RecorderHandle:
    thread: threading.Thread
    stop_event: threading.Event
    frames_counter: list[int]  # 1-element mutable for cross-thread count
    started_monotonic: float


def _capture_loop(
    *,
    stop_event: threading.Event,
    session_dir: Path,
    fps: int,
    resolution_scale: float,
    region: tuple[int, int, int, int] | None,
    monitor_index: int,
    frames_counter: list[int],
    started_monotonic: float,
) -> None:
    interval = 1.0 / fps
    next_tick = started_monotonic
    with mss.mss() as sct:
        if region is not None:
            x, y, w, h = region
            target = {"left": x, "top": y, "width": w, "height": h}
        else:
            # monitors[0] is the full virtual screen across all displays
            target = sct.monitors[monitor_index]

        while not stop_event.is_set():
            now = time.monotonic()
            if now - started_monotonic > SAFETY_CAP_SECONDS:
                break
            if now < next_tick:
                if stop_event.wait(timeout=next_tick - now):
                    break

            ts_ms = int((time.monotonic() - started_monotonic) * 1000)
            raw = sct.grab(target)
            img = Image.frombytes("RGB", raw.size, raw.rgb)
            if resolution_scale != 1.0:
                new_size = (
                    max(1, int(img.width * resolution_scale)),
                    max(1, int(img.height * resolution_scale)),
                )
                img = img.resize(new_size, Image.LANCZOS)

            save_frame(session_dir, frames_counter[0], ts_ms, img)
            frames_counter[0] += 1
            next_tick += interval


def start_recorder(
    *,
    session_dir: Path,
    fps: int,
    resolution_scale: float,
    region: tuple[int, int, int, int] | None,
    monitor_index: int,
) -> RecorderHandle:
    session_dir.mkdir(parents=True, exist_ok=True)
    stop_event = threading.Event()
    counter: list[int] = [0]
    started = time.monotonic()
    thread = threading.Thread(
        target=_capture_loop,
        kwargs=dict(
            stop_event=stop_event,
            session_dir=session_dir,
            fps=fps,
            resolution_scale=resolution_scale,
            region=region,
            monitor_index=monitor_index,
            frames_counter=counter,
            started_monotonic=started,
        ),
        daemon=True,
        name=f"claude-eyes-recorder-{session_dir.name}",
    )
    thread.start()
    return RecorderHandle(
        thread=thread,
        stop_event=stop_event,
        frames_counter=counter,
        started_monotonic=started,
    )


def stop_recorder(handle: RecorderHandle, timeout: float = 5.0) -> int:
    handle.stop_event.set()
    handle.thread.join(timeout=timeout)
    return handle.frames_counter[0]
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_recorder.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/claude_eyes/recorder.py tests/test_recorder.py
git commit -m "feat(recorder): add background-thread screen capture around mss"
```

---

## Task 6: MCP server scaffold + `start_recording` tool

**Files:**
- Modify: `src/claude_eyes/server.py` (replace the current stub entirely)
- Create: `tests/test_server.py`

- [ ] **Step 1: Write the failing test for `start_recording`**

`tests/test_server.py`:
```python
"""Tests for claude_eyes.server — exercise tools directly (not via stdio)."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from tests.test_recorder import _FakeMSS  # reuse fake backend


@pytest.fixture
def patched_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Patch env + mss BEFORE importing server, so module-level init uses them."""
    monkeypatch.setenv("CLAUDE_EYES_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("CLAUDE_EYES_MONITOR", "0")
    monkeypatch.setenv("CLAUDE_EYES_INCLUDE_CURSOR", "false")

    # Fresh import each test
    import importlib
    import claude_eyes.recorder as rec_mod
    monkeypatch.setattr(rec_mod.mss, "mss", _FakeMSS)

    import claude_eyes.server as server
    importlib.reload(server)
    return server


def test_start_recording_creates_session_and_directory(patched_server, tmp_path: Path) -> None:
    result = patched_server.start_recording(fps=5, resolution_scale=1.0, region=None, session_name="t1")

    assert result["session_id"].startswith("sess_")
    assert result["config"]["fps"] == 5
    assert result["config"]["resolution_scale"] == 1.0
    assert result["config"]["monitor"] == 0
    assert result["config"]["include_cursor"] is False
    # folder created
    assert (tmp_path / "sessions" / result["session_id"]).exists()

    # cleanup side-effect so subsequent tests are isolated
    patched_server.cleanup_session(result["session_id"])
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_server.py::test_start_recording_creates_session_and_directory -v
```
Expected: `AttributeError` (start_recording or cleanup_session not defined yet) or the stub `SystemExit(1)`.

- [ ] **Step 3: Replace `src/claude_eyes/server.py` entirely**

```python
"""claudeEyes MCP server — stdio transport via FastMCP."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import DEFAULT_FPS, DEFAULT_RESOLUTION_SCALE, ServerConfig
from .recorder import RecorderHandle, start_recorder, stop_recorder
from .session import RecordingSession, SessionRegistry, utc_now_iso
from .storage import cleanup_session_dir, list_frames as list_frames_on_disk


_config: ServerConfig = ServerConfig.from_env()
_registry: SessionRegistry = SessionRegistry(_config.sessions_dir)
_active: dict[str, RecorderHandle] = {}

mcp = FastMCP("claude_eyes")


@mcp.tool()
def start_recording(
    fps: int = DEFAULT_FPS,
    resolution_scale: float = DEFAULT_RESOLUTION_SCALE,
    region: tuple[int, int, int, int] | None = None,
    session_name: str | None = None,
) -> dict[str, Any]:
    """Begin a new screen recording session.

    Returns a ``session_id`` used for every subsequent call. The session
    folder is created under the configured ``sessions_dir``.
    """
    session = RecordingSession.create(
        name=session_name or "",
        fps=fps,
        resolution_scale=resolution_scale,
        region=region,
        monitor=_config.monitor,
        include_cursor=_config.include_cursor,
        sessions_dir=_config.sessions_dir,
    )
    handle = start_recorder(
        session_dir=Path(session.frames_dir),
        fps=fps,
        resolution_scale=resolution_scale,
        region=session.region,
        monitor_index=_config.monitor,
    )
    _active[session.session_id] = handle
    _registry.add(session)
    return {
        "session_id": session.session_id,
        "started_at": session.started_at,
        "config": {
            "fps": fps,
            "resolution_scale": resolution_scale,
            "region": list(session.region) if session.region else None,
            "monitor": _config.monitor,
            "include_cursor": _config.include_cursor,
        },
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
```

Note: the other three tools (`stop_recording`, `list_frames`, `cleanup_session`) are added in Tasks 7-9 below. For this task, importing `cleanup_session_dir` / `stop_recorder` is harmless — they are used once the next tasks land. Leaving the imports now avoids noise later.

However, the test for Task 6 calls `patched_server.cleanup_session(...)` as a cleanup side-effect. To avoid circular test-ordering, **add the `cleanup_session` tool NOW** (its body is tiny) so the Task 6 test can run. Full implementation for Task 9 just adds tests — do not re-edit the code.

Append to `server.py` before `def main()`:

```python
@mcp.tool()
def cleanup_session(session_id: str) -> dict[str, Any]:
    """Delete all frames and registry data for a session. Always call after analysis."""
    session = _registry.get(session_id)
    if session is None:
        return {"deleted": False, "freed_bytes": 0, "reason": "unknown session"}
    if session_id in _active:
        stop_recorder(_active.pop(session_id))
    freed = cleanup_session_dir(Path(session.frames_dir))
    _registry.remove(session_id)
    return {"deleted": True, "freed_bytes": freed}
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_server.py -v
```
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/claude_eyes/server.py tests/test_server.py
git commit -m "feat(server): FastMCP app with start_recording + cleanup_session"
```

---

## Task 7: `stop_recording` tool

**Files:**
- Modify: `src/claude_eyes/server.py` (add tool)
- Modify: `tests/test_server.py` (add test)

- [ ] **Step 1: Add failing test**

Append to `tests/test_server.py`:
```python
def test_stop_recording_returns_frame_metadata(patched_server) -> None:
    start = patched_server.start_recording(fps=10, resolution_scale=1.0, region=None)
    sid = start["session_id"]
    time.sleep(0.4)
    result = patched_server.stop_recording(sid)

    assert result["session_id"] == sid
    assert result["frames_count"] >= 1
    assert result["duration_s"] > 0
    assert Path(result["frames_dir"]).is_dir()
    assert len(result["frame_paths"]) == result["frames_count"]

    patched_server.cleanup_session(sid)


def test_stop_recording_unknown_session_returns_error(patched_server) -> None:
    result = patched_server.stop_recording("sess_doesnotexist")
    assert "error" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_server.py -v
```
Expected: `AttributeError: module 'claude_eyes.server' has no attribute 'stop_recording'`.

- [ ] **Step 3: Add the tool to `server.py`** (insert before `cleanup_session`)

```python
@mcp.tool()
def stop_recording(session_id: str) -> dict[str, Any]:
    """Stop an active recording and return frame metadata.

    The session stays in the registry so ``list_frames`` / ``cleanup_session``
    can still reach it. Call ``cleanup_session`` once the frame-analyzer
    subagent has returned.
    """
    handle = _active.pop(session_id, None)
    if handle is None:
        return {"error": f"no active recording for session_id={session_id}"}
    frames_count = stop_recorder(handle)
    duration_s = time.monotonic() - handle.started_monotonic

    session = _registry.get(session_id)
    if session is None:
        return {"error": f"session {session_id} missing from registry"}
    session.stopped_at = utc_now_iso()
    session.frames_count = frames_count
    _registry.update(session)

    frames = list_frames_on_disk(Path(session.frames_dir))
    return {
        "session_id": session_id,
        "frames_count": frames_count,
        "duration_s": duration_s,
        "frames_dir": session.frames_dir,
        "frame_paths": [f["path"] for f in frames],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_server.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/claude_eyes/server.py tests/test_server.py
git commit -m "feat(server): add stop_recording tool"
```

---

## Task 8: `list_frames` tool

**Files:**
- Modify: `src/claude_eyes/server.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_server.py`:
```python
def test_list_frames_returns_current_frames(patched_server) -> None:
    start = patched_server.start_recording(fps=10, resolution_scale=1.0, region=None)
    sid = start["session_id"]
    time.sleep(0.35)
    listed = patched_server.list_frames(sid)

    assert listed["session_id"] == sid
    assert len(listed["frames"]) >= 1
    first = listed["frames"][0]
    assert set(first.keys()) == {"path", "index", "timestamp_ms"}

    patched_server.stop_recording(sid)
    patched_server.cleanup_session(sid)


def test_list_frames_unknown_session_returns_error(patched_server) -> None:
    result = patched_server.list_frames("sess_nope")
    assert "error" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_server.py -v
```
Expected: `AttributeError: ... 'list_frames'`.

- [ ] **Step 3: Add the tool to `server.py`** (insert before `cleanup_session`)

```python
@mcp.tool()
def list_frames(session_id: str) -> dict[str, Any]:
    """List frames of a session without stopping it. Safe on active sessions."""
    session = _registry.get(session_id)
    if session is None:
        return {"error": f"unknown session {session_id}"}
    return {
        "session_id": session_id,
        "frames": list_frames_on_disk(Path(session.frames_dir)),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_server.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/claude_eyes/server.py tests/test_server.py
git commit -m "feat(server): add list_frames tool"
```

---

## Task 9: `cleanup_session` test coverage

**Files:**
- Modify: `tests/test_server.py`

The tool itself was added in Task 6. This task just proves its behaviour.

- [ ] **Step 1: Add failing tests**

Append to `tests/test_server.py`:
```python
def test_cleanup_session_removes_frames_and_registry(patched_server) -> None:
    start = patched_server.start_recording(fps=10, resolution_scale=1.0, region=None)
    sid = start["session_id"]
    time.sleep(0.3)
    patched_server.stop_recording(sid)
    frames_dir = Path(patched_server._registry.get(sid).frames_dir)
    assert frames_dir.is_dir()

    result = patched_server.cleanup_session(sid)

    assert result["deleted"] is True
    assert result["freed_bytes"] > 0
    assert not frames_dir.exists()
    assert patched_server._registry.get(sid) is None


def test_cleanup_session_unknown_session_reports_not_deleted(patched_server) -> None:
    result = patched_server.cleanup_session("sess_ghost")
    assert result["deleted"] is False
    assert result["freed_bytes"] == 0


def test_cleanup_session_stops_still_active_recorder(patched_server) -> None:
    start = patched_server.start_recording(fps=10, resolution_scale=1.0, region=None)
    sid = start["session_id"]
    # do NOT call stop_recording — cleanup should still succeed
    time.sleep(0.2)
    result = patched_server.cleanup_session(sid)
    assert result["deleted"] is True
```

- [ ] **Step 2: Run tests to verify behavior**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_server.py -v
```
Expected: 8 passed. (All three new tests should pass because the tool was implemented in Task 6.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_server.py
git commit -m "test(server): lock down cleanup_session contract"
```

---

## Task 10: End-to-end smoke test + full suite green

**Files:**
- Modify: `tests/test_server.py` (append smoke)

- [ ] **Step 1: Add an end-to-end smoke test**

Append to `tests/test_server.py`:
```python
def test_full_flow_start_list_stop_cleanup(patched_server, tmp_path: Path) -> None:
    start = patched_server.start_recording(fps=10, resolution_scale=0.5, region=(0, 0, 8, 8))
    sid = start["session_id"]
    assert start["config"]["resolution_scale"] == 0.5

    time.sleep(0.4)

    mid = patched_server.list_frames(sid)
    assert len(mid["frames"]) >= 1

    end = patched_server.stop_recording(sid)
    assert end["frames_count"] == len(end["frame_paths"])

    cleanup = patched_server.cleanup_session(sid)
    assert cleanup["deleted"] is True
    assert patched_server._registry.get(sid) is None
```

- [ ] **Step 2: Run the whole suite**

Run:
```bash
.venv/Scripts/python.exe -m pytest -v
```
Expected: all tests green (config: 6, session: 7, storage: 6, recorder: 3, server: 9). Total ~31 passing.

- [ ] **Step 3: Run the type checker and linter**

Run:
```bash
.venv/Scripts/python.exe -m mypy src/claude_eyes
.venv/Scripts/python.exe -m ruff check src tests
```
Expected: both clean. If mypy complains about `mss` / `PIL` lacking stubs, add to `pyproject.toml`:

```toml
[[tool.mypy.overrides]]
module = ["mss", "mss.*", "PIL", "PIL.*"]
ignore_missing_imports = true
```

Re-run mypy.

- [ ] **Step 4: Commit**

```bash
git add tests/test_server.py pyproject.toml
git commit -m "test: end-to-end smoke; appease mypy for mss/PIL stubs"
```

---

## Task 11: Manual smoke against a real screen

No code changes. Verifies the server actually launches and captures real pixels on the user's machine.

- [ ] **Step 1: Launch the server directly to ensure it starts**

Run:
```bash
.venv/Scripts/python.exe -m claude_eyes.server
```
Expected: process runs and waits on stdin for MCP messages. Kill with Ctrl+C. No tracebacks.

- [ ] **Step 2: Quick Python smoke — capture a real 1-second recording**

Run (PowerShell or bash):
```bash
.venv/Scripts/python.exe -c "
import time, pathlib
from claude_eyes.server import start_recording, stop_recording, cleanup_session
s = start_recording(fps=5, resolution_scale=0.5, region=None, session_name='smoke')
print('started', s['session_id'])
time.sleep(1.0)
r = stop_recording(s['session_id'])
print('frames:', r['frames_count'], 'dir:', r['frames_dir'])
cleanup_session(s['session_id'])
print('cleaned')
"
```
Expected: prints `frames: 4` or `5`, the `sessions/sess_.../` directory briefly existed and is now gone. No tracebacks.

- [ ] **Step 3: Restart Claude Code so it picks up `.mcp.json`**

Outside this task. Not a code step.

- [ ] **Step 4: (Optional) push the branch**

```bash
git push -u origin feat/foundation
```

No commit in this task.

---

## Self-Review

**Spec coverage.** The four MCP tools promised in `CLAUDE.md` (`start_recording`, `stop_recording`, `list_frames`, `cleanup_session`) are each covered by a task with tests. The six public parameters of `start_recording` (`fps`, `resolution_scale`, `region`, `monitor`, `include_cursor`, `session_name`) are covered: Claude-controlled three in the tool signature (Task 6); user-controlled two via `ServerConfig.from_env` (Task 1); `session_name` in Task 6. JPEG q=85 and the 30-minute safety cap are fixed internal constants (Task 1, used in Task 4 and Task 5 respectively).

**Placeholder scan.** No "TBD" / "add error handling" / "similar to above" / undefined symbols detected. Every step that produces code shows the full code. Every test step shows exact commands and expected output.

**Type consistency.**
- `RecordingSession.region` is `tuple[int,int,int,int] | None` everywhere.
- `start_recorder` takes keyword-only args (`session_dir`, `fps`, `resolution_scale`, `region`, `monitor_index`) — matches the call site in `server.start_recording`.
- `RecorderHandle.started_monotonic` (float) is used in `stop_recording` for `duration_s` — matches.
- `frames_counter` is a 1-element `list[int]` in both `_capture_loop` and `RecorderHandle` — matches.
- `list_frames` is the tool name on `server` AND the helper name in `storage`. To avoid shadowing, `server.py` imports the helper as `list_frames_on_disk`. Checked.

No gaps found. Plan is ready.

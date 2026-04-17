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
        return asdict(self)


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

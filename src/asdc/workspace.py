"""Per-workspace isolation.

A workspace is a company's/agency's own island of data: its entities, its
templates, its generated documents, its conversation. A brand-new user gets
a brand-new workspace with none of that pre-filled - onboarding happens by
talking to the assistant, not by seeding demo data.
"""
from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .store import EntityStore
from .templates import TemplateStore


@dataclass
class WorkspaceInfo:
    id: str
    name: str
    created_at: str


class WorkspaceNotFound(KeyError):
    pass


class WorkspaceRegistry:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._index_path = self.root / "index.json"
        if not self._index_path.exists():
            self._index_path.write_text("[]", encoding="utf-8")

    def _read_index(self) -> list[dict]:
        return json.loads(self._index_path.read_text(encoding="utf-8"))

    def _write_index(self, items: list[dict]) -> None:
        self._index_path.write_text(
            json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def create(self, name: str = "مساحة عمل جديدة") -> WorkspaceInfo:
        workspace_id = secrets.token_hex(6)
        workspace_dir = self.root / workspace_id
        workspace_dir.mkdir(parents=True)
        (workspace_dir / "entities.json").write_text("[]", encoding="utf-8")
        (workspace_dir / "templates.json").write_text("[]", encoding="utf-8")
        (workspace_dir / "conversation.json").write_text("[]", encoding="utf-8")
        (workspace_dir / "templates").mkdir()
        (workspace_dir / "documents").mkdir()

        info = WorkspaceInfo(
            id=workspace_id, name=name, created_at=datetime.now(timezone.utc).isoformat()
        )
        items = self._read_index()
        items.append({"id": info.id, "name": info.name, "created_at": info.created_at})
        self._write_index(items)
        return info

    def get_info(self, workspace_id: str) -> Optional[WorkspaceInfo]:
        for item in self._read_index():
            if item["id"] == workspace_id:
                return WorkspaceInfo(**item)
        return None

    def rename(self, workspace_id: str, name: str) -> None:
        items = self._read_index()
        for item in items:
            if item["id"] == workspace_id:
                item["name"] = name
        self._write_index(items)

    def exists(self, workspace_id: str) -> bool:
        return (self.root / workspace_id / "entities.json").exists()

    def require(self, workspace_id: str) -> WorkspaceInfo:
        info = self.get_info(workspace_id)
        if info is None or not self.exists(workspace_id):
            raise WorkspaceNotFound(workspace_id)
        return info

    def path(self, workspace_id: str) -> Path:
        return self.root / workspace_id

    def load_stores(self, workspace_id: str) -> tuple[EntityStore, TemplateStore]:
        self.require(workspace_id)
        wpath = self.path(workspace_id)
        entities = EntityStore.from_file(wpath / "entities.json")
        templates = TemplateStore.from_file(wpath / "templates.json")
        return entities, templates

    def load_conversation(self, workspace_id: str) -> list[dict]:
        path = self.path(workspace_id) / "conversation.json"
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))

    def save_conversation(self, workspace_id: str, messages: list[dict]) -> None:
        path = self.path(workspace_id) / "conversation.json"
        path.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")

"""In-memory entity store backed by a JSON file.

Stands in for the "قاعدة بيانات وقوالب مستندات موجودة مسبقًا" mentioned in
the system prompt. A real deployment would swap this for an actual database
without touching the NLU/validation/execution layers above it.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


class Entity:
    def __init__(self, id: str, type: str, name: str, fields: dict[str, str],
                 documents: Optional[list[dict[str, Any]]] = None):
        self.id = id
        self.type = type
        self.name = name
        self.fields = fields
        self.documents = documents if documents is not None else []

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "fields": self.fields,
            "documents": self.documents,
        }

    def has_locked_document(self) -> bool:
        return any(doc.get("status") in ("موقّع", "مُرسل") for doc in self.documents)


class EntityStore:
    def __init__(self, entities: list[Entity], path: Optional[Path] = None):
        self._entities: dict[str, Entity] = {e.id: e for e in entities}
        self._path = path
        self._next_seq = 1

    @classmethod
    def from_file(cls, path: Path) -> "EntityStore":
        raw = json.loads(path.read_text(encoding="utf-8"))
        entities = [Entity(**item) for item in raw]
        return cls(entities, path=path)

    def save(self, path: Optional[Path] = None) -> None:
        target = path or self._path
        if target is None:
            raise ValueError("no path configured for this store")
        target.write_text(
            json.dumps([e.to_dict() for e in self._entities.values()],
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get(self, entity_id: str) -> Optional[Entity]:
        return self._entities.get(entity_id)

    def all(self) -> list[Entity]:
        return list(self._entities.values())

    def by_type(self, entity_type: str) -> list[Entity]:
        return [e for e in self._entities.values() if e.type == entity_type]

    def find_by_name(self, name: str, entity_type: Optional[str] = None) -> list[Entity]:
        candidates = self._entities.values()
        if entity_type:
            candidates = (e for e in candidates if e.type == entity_type)
        return [e for e in candidates if e.name == name]

    def add(self, type: str, name: str, fields: dict[str, str]) -> Entity:
        entity_id = f"{type}_{self._next_seq:04d}"
        while entity_id in self._entities:
            self._next_seq += 1
            entity_id = f"{type}_{self._next_seq:04d}"
        self._next_seq += 1
        entity = Entity(id=entity_id, type=type, name=name, fields=fields)
        self._entities[entity_id] = entity
        return entity

    def update_fields(self, entity_id: str, fields: dict[str, str]) -> Entity:
        entity = self._entities.get(entity_id)
        if entity is None:
            raise KeyError(f"unknown entity_id: {entity_id}")
        entity.fields.update(fields)
        return entity

"""Template store + document generation.

Implements rule 5 from the system prompt: a generate_document request for an
entity that already has a signed/sent document must create a brand new,
separate document version and must never touch the old one.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import docx_template
from .store import Entity

LOCKED_STATUSES = {"موقّع", "مُرسل"}

_PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")


@dataclass
class Template:
    name: str
    applies_to: str
    fields: list[str]
    body: Optional[str] = None
    source_path: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "applies_to": self.applies_to,
            "fields": self.fields,
            "body": self.body,
            "source_path": self.source_path,
        }


class TemplateStore:
    def __init__(self, templates: list[Template], path: Optional[Path] = None):
        self._templates: dict[str, Template] = {t.name: t for t in templates}
        self._path = path

    @classmethod
    def from_file(cls, path: Path) -> "TemplateStore":
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls([Template(**item) for item in raw], path=path)

    def save(self, path: Optional[Path] = None) -> None:
        target = path or self._path
        if target is None:
            raise ValueError("no path configured for this store")
        target.write_text(
            json.dumps([t.to_dict() for t in self._templates.values()],
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get(self, name: str) -> Optional[Template]:
        return self._templates.get(name)

    def names(self) -> list[str]:
        return list(self._templates.keys())

    def add(self, template: Template) -> Template:
        self._templates[template.name] = template
        return template


@dataclass
class GeneratedDocument:
    id: str
    template: str
    entity_id: str
    content: str
    is_new_version: bool
    superseded_status: Optional[str] = None
    missing_fields: list[str] = field(default_factory=list)


def render_template(template: Template, entity: Entity) -> tuple[str, list[str]]:
    """Fill {placeholder} tokens from the entity's own fields (plus name).

    Returns (rendered_text, missing_field_names). A missing field is left as
    the literal placeholder rather than invented - callers must reject
    generation when missing_fields is non-empty, per rule 1 of the prompt.
    """
    values = {"الاسم": entity.name, **entity.fields}
    missing: list[str] = []

    def _sub(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            missing.append(key)
            return match.group(0)
        return str(values[key])

    rendered = _PLACEHOLDER_RE.sub(_sub, template.body)
    return rendered, missing


def generate_document(
    template: Template,
    entity: Entity,
    documents_dir: Path,
    doc_id_factory: Optional[Any] = None,
) -> GeneratedDocument:
    is_docx = template.source_path is not None
    rendered_doc = None
    content = ""
    if is_docx:
        values = {"الاسم": entity.name, **entity.fields}
        rendered_doc, missing = docx_template.build_rendered_docx(Path(template.source_path), values)
    else:
        content, missing = render_template(template, entity)

    was_locked = entity.has_locked_document()
    superseded_status = None
    if was_locked:
        locked = next(d for d in entity.documents if d.get("status") in LOCKED_STATUSES)
        superseded_status = locked.get("status")

    doc_id = doc_id_factory() if doc_id_factory else f"doc_{int(datetime.now(timezone.utc).timestamp() * 1000)}"

    record = {
        "id": doc_id,
        "template": template.name,
        "status": "مسودة",
        "created_at": datetime.now(timezone.utc).date().isoformat(),
    }

    if not missing:
        # Only persist the new version; existing locked documents are left
        # untouched (rule 5) - we append, never overwrite.
        entity.documents.append(record)
        documents_dir.mkdir(parents=True, exist_ok=True)
        if is_docx:
            output_path = documents_dir / f"{doc_id}.docx"
            rendered_doc.save(str(output_path))
            content = f"[docx generated: {output_path.name}]"
        else:
            (documents_dir / f"{doc_id}.txt").write_text(content, encoding="utf-8")

    return GeneratedDocument(
        id=doc_id,
        template=template.name,
        entity_id=entity.id,
        content=content,
        is_new_version=was_locked,
        superseded_status=superseded_status,
        missing_fields=missing,
    )

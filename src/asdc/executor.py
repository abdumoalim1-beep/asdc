"""Executes a validated NLUResponse against the entity/template store.

Callers must run validator.validate() first and only call execute() when
ok=True - execute() re-checks the same invariants defensively and raises
rather than guessing if something is missing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .schema import NLUResponse
from .store import Entity, EntityStore
from .templates import TemplateStore, generate_document
from .validator import validate


class ExecutionRefused(RuntimeError):
    """Raised when execute() is asked to act on an unvalidated/invalid response."""


@dataclass
class ExecutionResult:
    intent: str
    human_message: str
    detail: dict[str, Any] = field(default_factory=dict)


def execute(
    response: NLUResponse,
    entities: EntityStore,
    templates: TemplateStore,
    documents_dir: Path,
) -> ExecutionResult:
    if response.intent in ("ambiguous", "unsupported"):
        return ExecutionResult(intent=response.intent, human_message=response.human_message)

    result = validate(response, entities, templates)
    if not result.ok:
        raise ExecutionRefused("; ".join(result.errors))

    if response.intent == "update_field":
        entity = entities.update_fields(response.matched_entity_id, response.fields_to_update)
        return ExecutionResult(
            intent=response.intent,
            human_message=response.human_message,
            detail={"entity_id": entity.id, "fields": dict(entity.fields)},
        )

    if response.intent == "add_entity":
        entity = entities.add(
            type=response.entity_type,
            name=response.entity_reference,
            fields=dict(response.fields_to_update),
        )
        return ExecutionResult(
            intent=response.intent,
            human_message=response.human_message,
            detail={"entity_id": entity.id},
        )

    if response.intent == "generate_document":
        entity = entities.get(response.matched_entity_id)
        template = templates.get(response.template_requested)
        doc = generate_document(template, entity, documents_dir)
        if doc.missing_fields:
            raise ExecutionRefused(
                f"cannot generate '{template.name}' for {entity.id}: "
                f"missing fields {doc.missing_fields} (rule 1 - never invent data)"
            )
        return ExecutionResult(
            intent=response.intent,
            human_message=response.human_message,
            detail={
                "document_id": doc.id,
                "entity_id": entity.id,
                "is_new_version": doc.is_new_version,
                "superseded_status": doc.superseded_status,
            },
        )

    if response.intent == "query":
        matches: list[Entity]
        if response.matched_entity_id:
            found = entities.get(response.matched_entity_id)
            matches = [found] if found else []
        elif response.entity_type:
            matches = entities.by_type(response.entity_type)
        else:
            matches = entities.all()
        return ExecutionResult(
            intent=response.intent,
            human_message=response.human_message,
            detail={"results": [e.to_dict() for e in matches]},
        )

    raise ExecutionRefused(f"unhandled intent: {response.intent}")

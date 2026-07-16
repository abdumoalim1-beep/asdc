"""Cross-checks a parsed NLUResponse against real data before execution.

The model's JSON is never trusted directly (see notes at the end of the
system prompt): matched_entity_id must actually exist, template_requested
must actually be an available template, and the response must carry enough
information for the executor to act without guessing.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .schema import NLUResponse
from .store import EntityStore
from .templates import TemplateStore


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)


def validate(response: NLUResponse, entities: EntityStore, templates: TemplateStore) -> ValidationResult:
    errors: list[str] = []

    if response.intent in ("ambiguous", "unsupported", "chat"):
        # Nothing to execute; the model already deferred to the user.
        return ValidationResult(ok=True)

    if response.intent == "update_field":
        if not response.matched_entity_id:
            errors.append(
                "update_field requires matched_entity_id; the current JSON contract "
                "has no batch-target field, so a null id can't be safely applied to "
                "multiple entities and must be re-classified as ambiguous upstream."
            )
        elif entities.get(response.matched_entity_id) is None:
            errors.append(f"matched_entity_id '{response.matched_entity_id}' does not exist")
        if not response.fields_to_update:
            errors.append("update_field requires a non-empty fields_to_update")

    elif response.intent == "add_entity":
        if not response.entity_type:
            errors.append("add_entity requires entity_type")
        if not response.entity_reference:
            errors.append("add_entity requires entity_reference (the new entity's name)")
        if response.entity_type and response.entity_reference:
            duplicates = entities.find_by_name(response.entity_reference, response.entity_type)
            if duplicates:
                errors.append(
                    f"an entity named '{response.entity_reference}' of type "
                    f"'{response.entity_type}' already exists (id={duplicates[0].id}); "
                    "this should have been classified as update_field or ambiguous"
                )

    elif response.intent == "generate_document":
        if not response.template_requested:
            errors.append("generate_document requires template_requested")
        elif templates.get(response.template_requested) is None:
            errors.append(f"template_requested '{response.template_requested}' is not available")
        if not response.matched_entity_id:
            errors.append("generate_document requires matched_entity_id")
        else:
            entity = entities.get(response.matched_entity_id)
            if entity is None:
                errors.append(f"matched_entity_id '{response.matched_entity_id}' does not exist")
            elif response.template_requested:
                template = templates.get(response.template_requested)
                if template is not None and template.applies_to != entity.type:
                    errors.append(
                        f"template '{template.name}' applies to '{template.applies_to}', "
                        f"not '{entity.type}'"
                    )

    elif response.intent == "query":
        if response.entity_type is None and response.matched_entity_id is None:
            # A fully unscoped query is still valid - it just means "list everything".
            pass

    return ValidationResult(ok=not errors, errors=errors)

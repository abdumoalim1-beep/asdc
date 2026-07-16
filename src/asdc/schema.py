"""Strict schema for the JSON the NLU model must return.

Mirrors the response contract defined in prompts/system_prompt.txt exactly.
Anything that doesn't validate against this is treated as a broken model
response, not a valid action - see llm_client.parse_response.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, model_validator

Intent = Literal[
    "add_entity",
    "update_field",
    "generate_document",
    "query",
    "ambiguous",
    "unsupported",
]

Confidence = Literal["high", "medium", "low"]


class NLUResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Intent
    confidence: Confidence
    entity_type: Optional[str] = None
    entity_reference: Optional[str] = None
    matched_entity_id: Optional[str] = None
    fields_to_update: dict[str, str] = {}
    template_requested: Optional[str] = None
    clarification_needed: Optional[str] = None
    human_message: str

    @model_validator(mode="after")
    def _ambiguous_needs_clarification(self) -> "NLUResponse":
        if self.intent == "ambiguous" and not self.clarification_needed:
            raise ValueError(
                "intent=ambiguous requires a non-empty clarification_needed"
            )
        return self

import pytest
from pydantic import ValidationError

from asdc.schema import NLUResponse


def test_valid_update_field_response():
    response = NLUResponse.model_validate(
        {
            "intent": "update_field",
            "confidence": "high",
            "entity_type": "منتج",
            "entity_reference": "باقة الفعاليات",
            "matched_entity_id": "prod_014",
            "fields_to_update": {"السعر": "500"},
            "template_requested": None,
            "clarification_needed": None,
            "human_message": "تم تحديث السعر.",
        }
    )
    assert response.intent == "update_field"
    assert response.fields_to_update == {"السعر": "500"}


def test_ambiguous_without_clarification_is_rejected():
    with pytest.raises(ValidationError):
        NLUResponse.model_validate(
            {
                "intent": "ambiguous",
                "confidence": "low",
                "entity_type": None,
                "entity_reference": None,
                "matched_entity_id": None,
                "fields_to_update": {},
                "template_requested": None,
                "clarification_needed": None,
                "human_message": "محتاج توضيح.",
            }
        )


def test_unknown_intent_is_rejected():
    with pytest.raises(ValidationError):
        NLUResponse.model_validate(
            {
                "intent": "delete_entity",
                "confidence": "high",
                "entity_type": None,
                "entity_reference": None,
                "matched_entity_id": None,
                "fields_to_update": {},
                "template_requested": None,
                "clarification_needed": None,
                "human_message": "x",
            }
        )


def test_extra_fields_are_rejected():
    with pytest.raises(ValidationError):
        NLUResponse.model_validate(
            {
                "intent": "query",
                "confidence": "high",
                "entity_type": None,
                "entity_reference": None,
                "matched_entity_id": None,
                "fields_to_update": {},
                "template_requested": None,
                "clarification_needed": None,
                "human_message": "x",
                "extra_field": "not allowed",
            }
        )

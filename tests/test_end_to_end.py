"""Full pipeline test: LLMClient.classify -> validator.validate -> executor.execute.

Uses a fake completion_fn (no network/API key needed) that returns the
example-1 response verbatim from the system prompt, proving the wiring
between all layers works end to end.
"""
import json

from asdc.executor import execute
from asdc.llm_client import LLMClient
from asdc.validator import validate

FAKE_MODEL_REPLY = json.dumps(
    {
        "intent": "update_field",
        "confidence": "high",
        "entity_type": "منتج",
        "entity_reference": "باقة الفعاليات",
        "matched_entity_id": "prod_014",
        "fields_to_update": {"السعر": "500"},
        "template_requested": None,
        "clarification_needed": None,
        "human_message": "تم تحديث سعر باقة الفعاليات إلى 500 ريال.",
    },
    ensure_ascii=False,
)


def test_full_pipeline_update_field(entities, templates, documents_dir):
    def fake_completion(system_prompt: str, user_payload: str) -> str:
        assert "باقة الفعاليات" in user_payload
        return FAKE_MODEL_REPLY

    client = LLMClient(fake_completion)
    response = client.classify(
        "غيّر سعر باقة الفعاليات لـ 500 ريال",
        [e.to_dict() for e in entities.all()],
        [],
    )

    result = validate(response, entities, templates)
    assert result.ok, result.errors

    execution = execute(response, entities, templates, documents_dir)
    assert entities.get("prod_014").fields["السعر"] == "500"
    assert execution.human_message == "تم تحديث سعر باقة الفعاليات إلى 500 ريال."

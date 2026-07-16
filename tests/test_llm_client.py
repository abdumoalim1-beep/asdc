import json

import pytest

from asdc.llm_client import (
    MalformedModelResponse,
    build_user_payload,
    load_system_prompt,
    parse_response,
)

VALID_JSON = json.dumps(
    {
        "intent": "query",
        "confidence": "high",
        "entity_type": "عميل",
        "entity_reference": None,
        "matched_entity_id": None,
        "fields_to_update": {},
        "template_requested": None,
        "clarification_needed": None,
        "human_message": "هذي قائمة العملاء.",
    },
    ensure_ascii=False,
)


def test_parse_response_accepts_clean_json():
    response = parse_response(VALID_JSON)
    assert response.intent == "query"


def test_parse_response_strips_accidental_code_fences():
    fenced = f"```json\n{VALID_JSON}\n```"
    response = parse_response(fenced)
    assert response.intent == "query"


def test_parse_response_rejects_non_json():
    with pytest.raises(MalformedModelResponse):
        parse_response("هذا مو جيسون")


def test_parse_response_rejects_schema_violation():
    with pytest.raises(MalformedModelResponse):
        parse_response(json.dumps({"intent": "query"}))


def test_build_user_payload_includes_all_context_keys():
    payload = json.loads(
        build_user_payload("مرحبا", [{"id": "x"}], [{"name": "t"}], [{"role": "user", "content": "hi"}])
    )
    assert set(payload.keys()) == {
        "user_message",
        "workspace_entities",
        "available_templates",
        "conversation_history",
    }
    assert payload["user_message"] == "مرحبا"


def test_load_system_prompt_matches_contract_markers():
    text = load_system_prompt()
    assert "json.loads()" in text
    assert "add_entity" in text and "unsupported" in text

from asdc.schema import NLUResponse
from asdc.validator import validate


def _response(**overrides):
    base = dict(
        intent="update_field",
        confidence="high",
        entity_type=None,
        entity_reference=None,
        matched_entity_id=None,
        fields_to_update={},
        template_requested=None,
        clarification_needed=None,
        human_message="ok",
    )
    base.update(overrides)
    return NLUResponse.model_validate(base)


def test_update_field_valid(entities, templates):
    response = _response(matched_entity_id="prod_014", fields_to_update={"السعر": "500"})
    result = validate(response, entities, templates)
    assert result.ok, result.errors


def test_update_field_unknown_entity_is_rejected(entities, templates):
    response = _response(matched_entity_id="prod_999", fields_to_update={"السعر": "500"})
    result = validate(response, entities, templates)
    assert not result.ok


def test_update_field_without_target_is_rejected(entities, templates):
    response = _response(matched_entity_id=None, fields_to_update={"السعر": "500"})
    result = validate(response, entities, templates)
    assert not result.ok


def test_generate_document_valid(entities, templates):
    response = _response(
        intent="generate_document",
        matched_entity_id="client_003",
        template_requested="عقد تقديم خدمات",
    )
    result = validate(response, entities, templates)
    assert result.ok, result.errors


def test_generate_document_unknown_template_is_rejected(entities, templates):
    response = _response(
        intent="generate_document",
        matched_entity_id="client_003",
        template_requested="قالب غير موجود",
    )
    result = validate(response, entities, templates)
    assert not result.ok


def test_generate_document_mismatched_template_type_is_rejected(entities, templates):
    response = _response(
        intent="generate_document",
        matched_entity_id="prod_014",
        template_requested="عقد تقديم خدمات",
    )
    result = validate(response, entities, templates)
    assert not result.ok


def test_add_entity_duplicate_name_is_rejected(entities, templates):
    response = _response(
        intent="add_entity",
        entity_type="مؤثر",
        entity_reference="سارة العتيبي",
        fields_to_update={"المعرف": "@sara_style"},
    )
    result = validate(response, entities, templates)
    assert not result.ok


def test_add_entity_new_name_is_accepted(entities, templates):
    response = _response(
        intent="add_entity",
        entity_type="مؤثر",
        entity_reference="نورة الشهراني",
        fields_to_update={"المعرف": "@noura"},
    )
    result = validate(response, entities, templates)
    assert result.ok, result.errors


def test_ambiguous_always_ok_without_touching_data(entities, templates):
    response = _response(intent="ambiguous", clarification_needed="أي عميل تقصد؟")
    result = validate(response, entities, templates)
    assert result.ok


def test_chat_always_ok_without_touching_data(entities, templates):
    response = _response(intent="chat", human_message="مساحة عملك فيها عميلان ومنتج واحد.")
    result = validate(response, entities, templates)
    assert result.ok

import pytest

from asdc.executor import ExecutionRefused, execute
from asdc.schema import NLUResponse


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


def test_update_field_persists_change(entities, templates, documents_dir):
    response = _response(matched_entity_id="prod_014", fields_to_update={"السعر": "500"})
    result = execute(response, entities, templates, documents_dir)
    assert result.detail["fields"]["السعر"] == "500"
    assert entities.get("prod_014").fields["السعر"] == "500"


def test_update_field_refuses_unknown_entity(entities, templates, documents_dir):
    response = _response(matched_entity_id="prod_999", fields_to_update={"السعر": "500"})
    with pytest.raises(ExecutionRefused):
        execute(response, entities, templates, documents_dir)


def test_generate_document_first_version(entities, templates, documents_dir):
    response = _response(
        intent="generate_document",
        matched_entity_id="client_003",
        template_requested="عقد تقديم خدمات",
        human_message="جاري تجهيز العقد.",
    )
    result = execute(response, entities, templates, documents_dir)
    assert result.detail["is_new_version"] is False
    entity = entities.get("client_003")
    assert len(entity.documents) == 1
    generated_file = documents_dir / f"{result.detail['document_id']}.txt"
    assert generated_file.exists()
    assert "شركة الرياض للتسويق" in generated_file.read_text(encoding="utf-8")


def test_generate_document_never_overwrites_signed_document(entities, templates, documents_dir):
    entity = entities.get("client_009")
    original_doc_count = len(entity.documents)
    original_signed = dict(entity.documents[0])

    response = _response(
        intent="generate_document",
        matched_entity_id="client_009",
        template_requested="عقد تقديم خدمات",
        human_message="بما إن فيه عقد موقّع سابق، رح أنشئ نسخة جديدة منفصلة.",
    )
    result = execute(response, entities, templates, documents_dir)

    assert result.detail["is_new_version"] is True
    assert result.detail["superseded_status"] == "موقّع"
    assert entity.documents[0] == original_signed  # untouched
    assert len(entity.documents) == original_doc_count + 1
    assert entity.documents[-1]["status"] != "موقّع"


def test_generate_document_refuses_when_field_missing(entities, templates, documents_dir):
    # اتفاقية تعاون مؤثر needs المعرف/المنصة which infl_007 already has, so
    # strip one to prove the executor won't invent it.
    entities.get("infl_007").fields.pop("المنصة")
    response = _response(
        intent="generate_document",
        matched_entity_id="infl_007",
        template_requested="اتفاقية تعاون مؤثر",
    )
    with pytest.raises(ExecutionRefused):
        execute(response, entities, templates, documents_dir)
    assert entities.get("infl_007").documents == []


def test_add_entity_creates_record(entities, templates, documents_dir):
    response = _response(
        intent="add_entity",
        entity_type="مؤثر",
        entity_reference="نورة الشهراني",
        fields_to_update={"المعرف": "@noura"},
        human_message="تمت الإضافة.",
    )
    result = execute(response, entities, templates, documents_dir)
    new_entity = entities.get(result.detail["entity_id"])
    assert new_entity.name == "نورة الشهراني"
    assert new_entity.fields["المعرف"] == "@noura"


def test_query_by_type(entities, templates, documents_dir):
    response = _response(intent="query", entity_type="منتج", human_message="هذي المنتجات.")
    result = execute(response, entities, templates, documents_dir)
    assert {e["id"] for e in result.detail["results"]} == {"prod_014"}


def test_query_all_when_unscoped(entities, templates, documents_dir):
    response = _response(intent="query", human_message="هذي كل البيانات.")
    result = execute(response, entities, templates, documents_dir)
    assert len(result.detail["results"]) == len(entities.all())


def test_ambiguous_executes_as_noop(entities, templates, documents_dir):
    response = _response(
        intent="ambiguous",
        clarification_needed="أي عميل تقصد؟",
        human_message="محتاج توضيح.",
    )
    result = execute(response, entities, templates, documents_dir)
    assert result.detail == {}


def test_unsupported_executes_as_noop(entities, templates, documents_dir):
    response = _response(intent="unsupported", human_message="خارج نطاقي.")
    result = execute(response, entities, templates, documents_dir)
    assert result.detail == {}


def test_chat_executes_as_noop_without_touching_entities(entities, templates, documents_dir):
    before = [e.to_dict() for e in entities.all()]
    response = _response(intent="chat", human_message="مساحة عملك فيها عميلان ومنتج واحد ومؤثران.")
    result = execute(response, entities, templates, documents_dir)
    assert result.detail == {}
    assert [e.to_dict() for e in entities.all()] == before

import json
import shutil
from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient

from asdc import server
from asdc.llm_client import LLMClient
from asdc.store import EntityStore
from asdc.templates import TemplateStore

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"


@pytest.fixture
def api(tmp_path, monkeypatch):
    tmp_data = tmp_path / "data"
    shutil.copytree(DATA_DIR, tmp_data)
    tmp_docs = tmp_path / "documents"

    monkeypatch.setattr(server, "entities", EntityStore.from_file(tmp_data / "workspace_entities.json"))
    monkeypatch.setattr(server, "templates", TemplateStore.from_file(tmp_data / "available_templates.json"))
    monkeypatch.setattr(server, "DATA_DIR", tmp_data)
    monkeypatch.setattr(server, "DOCUMENTS_DIR", tmp_docs)
    monkeypatch.setattr(server, "TEMPLATES_DIR", tmp_data / "templates")
    monkeypatch.setattr(server, "_client", None)

    return TestClient(server.app)


def _set_fake_reply(monkeypatch, reply_json: dict) -> None:
    def fake_completion(system_prompt: str, payload: str) -> str:
        return json.dumps(reply_json, ensure_ascii=False)

    monkeypatch.setattr(server, "_client", LLMClient(fake_completion))


def test_state_reports_real_counts_from_tmp_data(api):
    res = api.get("/api/state")
    assert res.status_code == 200
    data = res.json()
    assert data["stats"] == {"عميل": 2, "منتج": 1, "مؤثر": 2}
    assert len(data["files"]) == 1  # client_009's pre-existing signed contract
    assert data["files"][0]["status"] == "موقّع"


def test_chat_update_field_real_pipeline(api, monkeypatch):
    _set_fake_reply(
        monkeypatch,
        {
            "intent": "update_field",
            "confidence": "high",
            "entity_type": "منتج",
            "entity_reference": "باقة الفعاليات",
            "matched_entity_id": "prod_014",
            "fields_to_update": {"السعر": "700"},
            "template_requested": None,
            "clarification_needed": None,
            "human_message": "تم تحديث السعر إلى 700 ريال.",
        },
    )
    res = api.post("/api/chat", json={"message": "غيّر سعر باقة الفعاليات لـ 700 ريال", "history": []})
    assert res.status_code == 200
    data = res.json()
    assert data["intent"] == "update_field"
    assert data["detail"]["fields"]["السعر"] == "700"
    assert server.entities.get("prod_014").fields["السعر"] == "700"


def test_chat_generate_document_updates_state(api, monkeypatch):
    _set_fake_reply(
        monkeypatch,
        {
            "intent": "generate_document",
            "confidence": "high",
            "entity_type": "عميل",
            "entity_reference": "شركة الرياض للتسويق",
            "matched_entity_id": "client_003",
            "fields_to_update": {},
            "template_requested": "عقد تقديم خدمات",
            "clarification_needed": None,
            "human_message": "جاري تجهيز العقد.",
        },
    )
    res = api.post("/api/chat", json={"message": "جهز عقد لشركة الرياض للتسويق", "history": []})
    data = res.json()
    assert data["intent"] == "generate_document"
    assert data["detail"]["is_new_version"] is False

    state = api.get("/api/state").json()
    assert len(state["files"]) == 2  # the pre-existing signed one + this new draft


def test_chat_intent_is_a_noop(api, monkeypatch):
    _set_fake_reply(
        monkeypatch,
        {
            "intent": "chat",
            "confidence": "high",
            "entity_type": None,
            "entity_reference": None,
            "matched_entity_id": None,
            "fields_to_update": {},
            "template_requested": None,
            "clarification_needed": None,
            "human_message": "مساحة عملك فيها عميلان ومنتج واحد ومؤثران.",
        },
    )
    before = api.get("/api/state").json()
    res = api.post("/api/chat", json={"message": "اشرح لي مساحة العمل", "history": []})
    data = res.json()
    assert data["intent"] == "chat"
    assert data["detail"] == {}
    after = api.get("/api/state").json()
    assert before == after


def test_chat_ambiguous_surfaces_clarification(api, monkeypatch):
    _set_fake_reply(
        monkeypatch,
        {
            "intent": "ambiguous",
            "confidence": "low",
            "entity_type": "مؤثر",
            "entity_reference": "سارة",
            "matched_entity_id": None,
            "fields_to_update": {},
            "template_requested": None,
            "clarification_needed": "عندي أكثر من سارة، أي وحدة تقصد؟",
            "human_message": "محتاج توضيح.",
        },
    )
    res = api.post("/api/chat", json={"message": "أضف صورة جديدة لسارة", "history": []})
    data = res.json()
    assert data["intent"] == "ambiguous"
    assert data["clarification_needed"] == "عندي أكثر من سارة، أي وحدة تقصد؟"


def test_chat_execution_refused_does_not_crash(api, monkeypatch):
    _set_fake_reply(
        monkeypatch,
        {
            "intent": "generate_document",
            "confidence": "high",
            "entity_type": "عميل",
            "entity_reference": "شركة الرياض للتسويق",
            "matched_entity_id": "client_003",
            "fields_to_update": {},
            "template_requested": "قالب غير موجود إطلاقًا",
            "clarification_needed": None,
            "human_message": "جاري التجهيز.",
        },
    )
    res = api.post("/api/chat", json={"message": "جهز مستند غريب", "history": []})
    assert res.status_code == 200
    data = res.json()
    assert data["intent"] == "refused"
    assert data["error"]


def test_chat_malformed_model_reply_does_not_crash(api, monkeypatch):
    monkeypatch.setattr(server, "_client", LLMClient(lambda sp, up: "هذا مو JSON"))
    res = api.post("/api/chat", json={"message": "أي شي", "history": []})
    assert res.status_code == 200
    data = res.json()
    assert data["intent"] == "error"
    assert data["error"]


def test_upload_template_with_explicit_placeholders_needs_no_llm(api, tmp_path):
    docx_path = tmp_path / "raw.docx"
    doc = Document()
    doc.add_paragraph("عقد للعميل: {{الاسم}}")
    doc.save(str(docx_path))

    with open(docx_path, "rb") as fh:
        res = api.post(
            "/api/templates/upload",
            files={"file": ("raw.docx", fh, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            data={"name": "عقد اختباري", "applies_to": "عميل"},
        )
    assert res.status_code == 200
    data = res.json()
    assert data["fields"] == ["الاسم"]
    assert server.templates.get("عقد اختباري") is not None

import json
from pathlib import Path

import pytest

from asdc import agent
from asdc.store import EntityStore
from asdc.templates import TemplateStore


@pytest.fixture
def empty_entities(tmp_path: Path):
    path = tmp_path / "entities.json"
    path.write_text("[]", encoding="utf-8")
    return EntityStore.from_file(path)


@pytest.fixture
def empty_templates(tmp_path: Path):
    path = tmp_path / "templates.json"
    path.write_text("[]", encoding="utf-8")
    return TemplateStore.from_file(path)


def _tool_call(call_id: str, name: str, arguments: dict) -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}


def test_workspace_snapshot_flags_empty_workspace(empty_entities, empty_templates):
    snapshot = json.loads(agent.workspace_snapshot(empty_entities, empty_templates))
    assert snapshot["workspace_entities"] == []
    assert snapshot["available_templates"] == []
    assert "note" in snapshot


def test_workspace_snapshot_no_note_when_populated(entities, templates):
    snapshot = json.loads(agent.workspace_snapshot(entities, templates))
    assert snapshot["workspace_entities"]
    assert "note" not in snapshot


def test_run_turn_plain_reply_needs_no_tool(empty_entities, empty_templates, documents_dir):
    def fake_model(messages):
        return {"role": "assistant", "content": "أهلًا! عرّفني بشركتك عشان أبدأ أساعدك."}

    result = agent.run_turn(fake_model, empty_entities, empty_templates, documents_dir, [], "مرحبا")
    assert result.reply == "أهلًا! عرّفني بشركتك عشان أبدأ أساعدك."
    assert result.actions == []
    assert result.messages[-2]["role"] == "user"
    assert result.messages[-1]["role"] == "assistant"


def test_run_turn_executes_add_entity_tool_call(empty_entities, empty_templates, documents_dir):
    calls = []

    def fake_model(messages):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "role": "assistant", "content": "",
                "tool_calls": [_tool_call("c1", "add_entity", {"entity_type": "عميل", "name": "شركة الاختبار", "fields": {}})],
            }
        return {"role": "assistant", "content": "تمام، أضفت شركة الاختبار كعميل جديد."}

    result = agent.run_turn(fake_model, empty_entities, empty_templates, documents_dir, [], "عندي عميل اسمه شركة الاختبار")

    assert len(result.actions) == 1
    assert result.actions[0].tool == "add_entity"
    assert result.actions[0].ok is True
    assert empty_entities.all()[0].name == "شركة الاختبار"
    assert result.reply == "تمام، أضفت شركة الاختبار كعميل جديد."

    # the second model call must have seen the tool result in its messages
    tool_messages = [m for m in calls[1] if m.get("role") == "tool"]
    assert tool_messages
    assert json.loads(tool_messages[0]["content"])["ok"] is True


def test_run_turn_reports_failed_tool_call_without_crashing(entities, templates, documents_dir):
    def fake_model(messages):
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        if not tool_msgs:
            return {
                "role": "assistant", "content": "",
                "tool_calls": [_tool_call("c1", "update_field", {"entity_id": "prod_999", "fields": {"السعر": "10"}})],
            }
        payload = json.loads(tool_msgs[0]["content"])
        assert payload["ok"] is False
        return {"role": "assistant", "content": "ما لقيت هذا المنتج عندك، تأكد من الاسم؟"}

    result = agent.run_turn(fake_model, entities, templates, documents_dir, [], "غيّر سعر منتج غير موجود")
    assert result.actions[0].ok is False
    assert result.actions[0].error
    assert "ما لقيت" in result.reply


def test_run_turn_handles_multiple_tool_calls_in_one_step(entities, templates, documents_dir):
    def fake_model(messages):
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        if not tool_msgs:
            return {
                "role": "assistant", "content": "",
                "tool_calls": [
                    _tool_call("c1", "update_field", {"entity_id": "prod_014", "fields": {"السعر": "999"}}),
                    _tool_call("c2", "query_entities", {"entity_type": "عميل"}),
                ],
            }
        return {"role": "assistant", "content": "حدّثت السعر وهذي قائمة عملائك."}

    result = agent.run_turn(fake_model, entities, templates, documents_dir, [], "غيّر السعر ووريني العملاء")
    assert len(result.actions) == 2
    assert entities.get("prod_014").fields["السعر"] == "999"
    assert result.actions[1].tool == "query_entities"
    assert len(result.actions[1].detail["results"]) == 2


def test_run_turn_caps_runaway_tool_loop(empty_entities, empty_templates, documents_dir):
    def fake_model(messages):
        return {
            "role": "assistant", "content": "",
            "tool_calls": [_tool_call("c", "query_entities", {})],
        }

    result = agent.run_turn(fake_model, empty_entities, empty_templates, documents_dir, [], "استمر")
    assert len(result.actions) == agent.MAX_STEPS
    assert "خطوات" in result.reply

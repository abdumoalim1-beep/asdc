"""Tool-calling conversational core.

Replaces the old "one message -> one classified intent" flow: the model
talks freely and only reaches for a tool when it actually needs to touch
data. Every tool call still gets funneled through the exact same
validator.validate / executor.execute used by the old flow - none of that
safety layer changed, only how a decision to act reaches it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .executor import ExecutionRefused, execute
from .schema import NLUResponse
from .store import EntityStore
from .templates import TemplateStore

SYSTEM_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent.parent / "prompts" / "assistant_system_prompt.txt"
)

DEFAULT_MODEL = "gpt-5-mini"
MAX_STEPS = 5

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add_entity",
            "description": "إضافة كيان جديد لمساحة العمل (عميل، منتج، مؤثر، أو أي نوع آخر يذكره المستخدم).",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_type": {"type": "string", "description": "نوع الكيان كما يسميه المستخدم، مثل 'عميل' أو 'منتج'"},
                    "name": {"type": "string", "description": "اسم الكيان"},
                    "fields": {
                        "type": "object",
                        "description": "حقول إضافية ذكرها المستخدم صراحة فقط، بدون اختراع أي قيمة لم تُذكر",
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": ["entity_type", "name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_field",
            "description": "تحديث حقل أو أكثر لكيان موجود فعلًا في workspace_entities بمعرّفه.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string", "description": "معرّف الكيان كما يظهر في workspace_entities"},
                    "fields": {
                        "type": "object",
                        "description": "الحقول والقيم الجديدة كما ذُكرت حرفيًا",
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": ["entity_id", "fields"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_document",
            "description": (
                "توليد مستند من قالب متاح في available_templates لكيان محدد. "
                "المستندات الموقّعة أو المُرسلة سابقًا لا تتعدّل - تُنشأ نسخة جديدة تلقائيًا."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string"},
                    "template_name": {"type": "string", "description": "اسم القالب بالضبط كما يظهر في available_templates"},
                },
                "required": ["entity_id", "template_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_entities",
            "description": "استرجاع بيانات كيانات موجودة بدون أي تعديل، فلترة اختيارية حسب النوع أو معرّف محدد.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_type": {"type": "string"},
                    "entity_id": {"type": "string"},
                },
            },
        },
    },
]


def load_system_prompt(path: Path = SYSTEM_PROMPT_PATH) -> str:
    return path.read_text(encoding="utf-8")


def workspace_snapshot(entities: EntityStore, templates: TemplateStore) -> str:
    payload = {
        "workspace_entities": [e.to_dict() for e in entities.all()],
        "available_templates": [
            {"name": t.name, "applies_to": t.applies_to, "fields": t.fields}
            for t in (templates.get(n) for n in templates.names())
        ],
    }
    if not payload["workspace_entities"] and not payload["available_templates"]:
        payload["note"] = "مساحة عمل جديدة تمامًا، لا يوجد فيها أي بيانات أو قوالب بعد."
    return json.dumps(payload, ensure_ascii=False)


class UnknownTool(ValueError):
    pass


def _to_nlu_response(tool_name: str, args: dict[str, Any]) -> NLUResponse:
    if tool_name == "add_entity":
        return NLUResponse(
            intent="add_entity", confidence="high",
            entity_type=args.get("entity_type"), entity_reference=args.get("name"),
            matched_entity_id=None, fields_to_update=args.get("fields") or {},
            template_requested=None, clarification_needed=None, human_message="",
        )
    if tool_name == "update_field":
        return NLUResponse(
            intent="update_field", confidence="high",
            entity_type=None, entity_reference=None,
            matched_entity_id=args.get("entity_id"), fields_to_update=args.get("fields") or {},
            template_requested=None, clarification_needed=None, human_message="",
        )
    if tool_name == "generate_document":
        return NLUResponse(
            intent="generate_document", confidence="high",
            entity_type=None, entity_reference=None,
            matched_entity_id=args.get("entity_id"), fields_to_update={},
            template_requested=args.get("template_name"), clarification_needed=None, human_message="",
        )
    if tool_name == "query_entities":
        return NLUResponse(
            intent="query", confidence="high",
            entity_type=args.get("entity_type"), entity_reference=None,
            matched_entity_id=args.get("entity_id"), fields_to_update={},
            template_requested=None, clarification_needed=None, human_message="",
        )
    raise UnknownTool(tool_name)


@dataclass
class AgentAction:
    tool: str
    arguments: dict[str, Any]
    ok: bool
    detail: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class AgentTurnResult:
    reply: str
    actions: list[AgentAction]
    messages: list[dict]


def _dispatch_tool(
    name: str, args: dict[str, Any], entities: EntityStore, templates: TemplateStore, documents_dir: Path
) -> AgentAction:
    try:
        response = _to_nlu_response(name, args)
    except UnknownTool as exc:
        return AgentAction(tool=name, arguments=args, ok=False, error=f"unknown tool: {exc}")

    try:
        result = execute(response, entities, templates, documents_dir)
    except ExecutionRefused as exc:
        return AgentAction(tool=name, arguments=args, ok=False, error=str(exc))

    entities.save()
    return AgentAction(tool=name, arguments=args, ok=True, detail=result.detail)


# A model call takes the full OpenAI-style message list (including the
# `tools` definitions already bound) and returns the assistant message dict
# as OpenAI's SDK would (with optional "tool_calls").
ModelCallFn = Callable[[list[dict]], dict]


def openai_tool_model(model: str = DEFAULT_MODEL, api_key: Optional[str] = None) -> ModelCallFn:
    from openai import OpenAI

    client = OpenAI(api_key=api_key) if api_key else OpenAI()

    def _call(messages: list[dict]) -> dict:
        response = client.chat.completions.create(model=model, messages=messages, tools=TOOLS)
        message = response.choices[0].message
        result: dict[str, Any] = {"role": "assistant", "content": message.content or ""}
        if message.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in message.tool_calls
            ]
        return result

    return _call


def run_turn(
    call_model: ModelCallFn,
    entities: EntityStore,
    templates: TemplateStore,
    documents_dir: Path,
    history: list[dict],
    user_message: str,
    system_prompt: Optional[str] = None,
) -> AgentTurnResult:
    """Run one user turn to completion, including any tool-call round trips.

    `history` is the prior conversation (assistant/user/tool messages, no
    system messages - those are rebuilt fresh here since workspace data can
    have changed). Returns the updated history to persist for next time.
    """
    prompt = system_prompt or load_system_prompt()
    messages: list[dict] = (
        [
            {"role": "system", "content": prompt},
            {"role": "system", "content": workspace_snapshot(entities, templates)},
        ]
        + history
        + [{"role": "user", "content": user_message}]
    )

    actions: list[AgentAction] = []
    for _ in range(MAX_STEPS):
        assistant_message = call_model(messages)
        tool_calls = assistant_message.get("tool_calls")

        if not tool_calls:
            messages.append({"role": "assistant", "content": assistant_message.get("content", "")})
            new_history = messages[2:]  # drop the two system messages
            return AgentTurnResult(reply=assistant_message.get("content", ""), actions=actions, messages=new_history)

        messages.append(assistant_message)
        for tc in tool_calls:
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            action = _dispatch_tool(tc["function"]["name"], args, entities, templates, documents_dir)
            actions.append(action)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(
                        {"ok": action.ok, "detail": action.detail, "error": action.error}, ensure_ascii=False
                    ),
                }
            )

    fallback = "صار عندي عدد كبير من الخطوات المتتالية - جرّب تعيد صياغة طلبك بشكل أبسط."
    messages.append({"role": "assistant", "content": fallback})
    return AgentTurnResult(reply=fallback, actions=actions, messages=messages[2:])

"""Wraps the NLU model call described in prompts/system_prompt.txt.

The system prompt requires the caller to send workspace_entities and
available_templates with every request (the model has no memory of its
own), and requires the model's reply to be raw JSON parseable by
json.loads with no markdown fences. This module builds that request and
enforces that contract on the way back.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional

from .schema import NLUResponse

SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "system_prompt.txt"

DEFAULT_MODEL = "gpt-5-mini"


def load_system_prompt(path: Path = SYSTEM_PROMPT_PATH) -> str:
    return path.read_text(encoding="utf-8")


def build_user_payload(
    user_message: str,
    workspace_entities: list[dict[str, Any]],
    available_templates: list[dict[str, Any]],
    conversation_history: Optional[list[dict[str, str]]] = None,
) -> str:
    """Serialize the per-request context exactly as the prompt expects it."""
    payload = {
        "user_message": user_message,
        "workspace_entities": workspace_entities,
        "available_templates": available_templates,
        "conversation_history": conversation_history or [],
    }
    return json.dumps(payload, ensure_ascii=False)


class MalformedModelResponse(ValueError):
    """Raised when the model's reply isn't the exact JSON contract requires."""


def parse_response(raw_text: str) -> NLUResponse:
    text = raw_text.strip()
    # Be forgiving of accidental ```json fences even though the prompt
    # forbids them - a broken response should fail validation, not the parse.
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MalformedModelResponse(f"model reply is not valid JSON: {exc}") from exc
    try:
        return NLUResponse.model_validate(data)
    except Exception as exc:  # pydantic.ValidationError
        raise MalformedModelResponse(f"model reply failed schema validation: {exc}") from exc


# A completion function takes (system_prompt, user_payload_json) -> raw model text.
CompletionFn = Callable[[str, str], str]


def openai_completion_fn(model: str = DEFAULT_MODEL, api_key: Optional[str] = None) -> CompletionFn:
    """Build a CompletionFn backed by the OpenAI Chat Completions API.

    Imports `openai` lazily so the rest of the package works without it
    installed (e.g. under test, where a fake CompletionFn is injected).
    """
    from openai import OpenAI

    client = OpenAI(api_key=api_key) if api_key else OpenAI()

    def _complete(system_prompt: str, user_payload: str) -> str:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_payload},
            ],
        )
        return response.choices[0].message.content or ""

    return _complete


class LLMClient:
    def __init__(self, completion_fn: CompletionFn, system_prompt: Optional[str] = None):
        self._completion_fn = completion_fn
        self._system_prompt = system_prompt or load_system_prompt()

    def classify(
        self,
        user_message: str,
        workspace_entities: list[dict[str, Any]],
        available_templates: list[dict[str, Any]],
        conversation_history: Optional[list[dict[str, str]]] = None,
    ) -> NLUResponse:
        payload = build_user_payload(
            user_message, workspace_entities, available_templates, conversation_history
        )
        raw = self._completion_fn(self._system_prompt, payload)
        return parse_response(raw)

"""Interactive REPL wiring the whole pipeline together.

  user message -> LLMClient.classify -> validator.validate -> executor.execute

Run with: python -m asdc.cli
Requires OPENAI_API_KEY in the environment (see README). ASDC_MODEL
overrides the default model.
"""
from __future__ import annotations

import dataclasses
import os
import sys
from pathlib import Path

from .executor import ExecutionRefused, execute
from .llm_client import DEFAULT_MODEL, LLMClient, MalformedModelResponse, openai_completion_fn
from .store import EntityStore
from .templates import TemplateStore

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data"
DOCUMENTS_DIR = REPO_ROOT / "documents"


def main() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set - see README for setup.", file=sys.stderr)
        sys.exit(1)

    model = os.environ.get("ASDC_MODEL", DEFAULT_MODEL)
    entities = EntityStore.from_file(DATA_DIR / "workspace_entities.json")
    templates = TemplateStore.from_file(DATA_DIR / "available_templates.json")
    client = LLMClient(openai_completion_fn(model=model))

    print(f"asdc — Smart Document Automation (model: {model}). اكتب 'خروج' للإنهاء.")
    history: list[dict[str, str]] = []

    while True:
        try:
            user_message = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_message:
            continue
        if user_message in ("خروج", "exit", "quit"):
            break

        try:
            response = client.classify(
                user_message,
                [e.to_dict() for e in entities.all()],
                [dataclasses.asdict(templates.get(n)) for n in templates.names()],
                history,
            )
        except MalformedModelResponse as exc:
            print(f"[خطأ] رد النموذج غير صالح: {exc}")
            continue

        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": response.human_message})

        if response.intent == "ambiguous":
            print(f"[توضيح مطلوب] {response.clarification_needed}")
            continue

        try:
            result = execute(response, entities, templates, DOCUMENTS_DIR)
        except ExecutionRefused as exc:
            print(f"[تم الرفض قبل التنفيذ] {exc}")
            continue

        print(result.human_message)
        if result.detail:
            print(f"  detail: {result.detail}")

    entities.save()


if __name__ == "__main__":
    main()

"""Interactive REPL wiring the whole pipeline together.

  user message -> LLMClient.classify -> validator.validate -> executor.execute

Run with: python -m asdc.cli
Requires OPENAI_API_KEY in the environment (see README). ASDC_MODEL
overrides the default model.

Pass --batch <file> to run a list of Arabic instructions (one per line,
'#' starts a comment) through the same pipeline non-interactively - each
line still names its own entity explicitly, so the "no implicit batch
target" rule (validator.py) applies exactly as it does in the REPL.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

from .executor import ExecutionRefused, execute
from .llm_client import DEFAULT_MODEL, LLMClient, MalformedModelResponse, openai_completion_fn
from .store import EntityStore
from .templates import TemplateStore

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data"
DOCUMENTS_DIR = REPO_ROOT / "documents"


def _template_context(templates: TemplateStore) -> list[dict]:
    return [
        {"name": t.name, "applies_to": t.applies_to, "fields": t.fields}
        for t in (templates.get(n) for n in templates.names())
    ]


def process_message(
    user_message: str,
    client: LLMClient,
    entities: EntityStore,
    templates: TemplateStore,
    documents_dir: Path,
    history: list[dict[str, str]],
) -> None:
    try:
        response = client.classify(
            user_message,
            [e.to_dict() for e in entities.all()],
            _template_context(templates),
            history,
        )
    except MalformedModelResponse as exc:
        print(f"[خطأ] رد النموذج غير صالح: {exc}")
        return

    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": response.human_message})

    if response.intent in ("ambiguous", "unsupported"):
        label = "توضيح مطلوب" if response.intent == "ambiguous" else "خارج النطاق"
        detail = response.clarification_needed if response.intent == "ambiguous" else response.human_message
        print(f"[{label}] {detail}")
        return

    try:
        result = execute(response, entities, templates, documents_dir)
    except ExecutionRefused as exc:
        print(f"[تم الرفض قبل التنفيذ] {exc}")
        return

    print(result.human_message)
    if result.detail:
        print(f"  detail: {result.detail}")


def _run_batch(client: LLMClient, entities: EntityStore, templates: TemplateStore, batch_file: Path) -> None:
    history: list[dict[str, str]] = []
    lines = [
        line.strip()
        for line in batch_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    for i, user_message in enumerate(lines, start=1):
        print(f"\n[{i}/{len(lines)}] > {user_message}")
        process_message(user_message, client, entities, templates, DOCUMENTS_DIR, history)


def _run_repl(client: LLMClient, entities: EntityStore, templates: TemplateStore) -> None:
    print("asdc — Smart Document Automation. اكتب 'خروج' للإنهاء.")
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
        process_message(user_message, client, entities, templates, DOCUMENTS_DIR, history)


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="asdc — Smart Document Automation")
    parser.add_argument("--batch", type=Path, help="ملف فيه قائمة تعليمات عربية، سطر لكل تعليمة")
    args = parser.parse_args(argv)

    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set - see README for setup.", file=sys.stderr)
        sys.exit(1)

    model = os.environ.get("ASDC_MODEL", DEFAULT_MODEL)
    entities = EntityStore.from_file(DATA_DIR / "workspace_entities.json")
    templates = TemplateStore.from_file(DATA_DIR / "available_templates.json")
    client = LLMClient(openai_completion_fn(model=model))

    if args.batch:
        _run_batch(client, entities, templates, args.batch)
    else:
        _run_repl(client, entities, templates)

    entities.save()


if __name__ == "__main__":
    main()

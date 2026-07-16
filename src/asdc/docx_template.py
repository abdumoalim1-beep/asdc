"""Real .docx template support: detect {{placeholder}} fields, fill them in
while keeping the original file's formatting, and (when a template has no
explicit placeholders yet) propose candidate fields via the LLM - extractive
only, never inventing text that isn't literally in the document.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from docx import Document
from docx.document import Document as DocumentObject
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

from .llm_client import CompletionFn, MalformedModelResponse

PLACEHOLDER_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")

FIELD_DETECTION_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent.parent / "prompts" / "template_field_detection_prompt.txt"
)


def load_field_detection_prompt(path: Path = FIELD_DETECTION_PROMPT_PATH) -> str:
    return path.read_text(encoding="utf-8")


def _iter_table_paragraphs(table: Table):
    for row in table.rows:
        for cell in row.cells:
            yield from _iter_cell_paragraphs(cell)


def _iter_cell_paragraphs(cell: _Cell):
    yield from cell.paragraphs
    for nested_table in cell.tables:
        yield from _iter_table_paragraphs(nested_table)


def _iter_all_paragraphs(doc: DocumentObject):
    yield from doc.paragraphs
    for table in doc.tables:
        yield from _iter_table_paragraphs(table)


def _paragraph_text(paragraph: Paragraph) -> str:
    return "".join(run.text for run in paragraph.runs)


def extract_placeholders(path: Path) -> list[str]:
    doc = Document(str(path))
    found: list[str] = []
    for paragraph in _iter_all_paragraphs(doc):
        for match in PLACEHOLDER_RE.finditer(_paragraph_text(paragraph)):
            name = match.group(1)
            if name not in found:
                found.append(name)
    return found


def extract_full_text(path: Path) -> str:
    doc = Document(str(path))
    return "\n".join(_paragraph_text(p) for p in _iter_all_paragraphs(doc) if p.runs)


def _replace_in_paragraph(paragraph: Paragraph, values: dict[str, str]) -> list[str]:
    if not paragraph.runs:
        return []
    text = _paragraph_text(paragraph)
    if "{{" not in text:
        return []

    missing: list[str] = []

    def _sub(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            missing.append(key)
            return match.group(0)
        return str(values[key])

    new_text = PLACEHOLDER_RE.sub(_sub, text)
    paragraph.runs[0].text = new_text
    for run in paragraph.runs[1:]:
        run.text = ""
    return missing


def build_rendered_docx(template_path: Path, values: dict[str, str]) -> tuple[DocumentObject, list[str]]:
    """Fill every {{placeholder}} in the template from `values`.

    Returns (document, missing_field_names). Never invents a value for a
    missing field - callers must refuse to save when missing_field_names is
    non-empty, matching rule 1 of the NLU system prompt.
    """
    doc = Document(str(template_path))
    missing: list[str] = []
    for paragraph in _iter_all_paragraphs(doc):
        for name in _replace_in_paragraph(paragraph, values):
            if name not in missing:
                missing.append(name)
    return doc, missing


def _clean_suggestions(raw_suggestions: list[dict], template_text: str) -> list[dict[str, str]]:
    cleaned: list[dict[str, str]] = []
    seen_fields: set[str] = set()
    for item in raw_suggestions:
        example = str(item.get("example_text", "")).strip()
        field_name = str(item.get("field_name", "")).strip()
        if not example or not field_name:
            continue
        if example not in template_text:
            # Extractive check failed - the model quoted text that isn't
            # literally in the document, so drop it rather than trust it.
            continue
        if field_name in seen_fields:
            continue
        seen_fields.add(field_name)
        cleaned.append({"example_text": example, "field_name": field_name})
    return cleaned


def suggest_placeholders_with_llm(
    template_text: str,
    completion_fn: CompletionFn,
    known_field_names: Optional[list[str]] = None,
) -> list[dict[str, str]]:
    system_prompt = load_field_detection_prompt()
    payload = json.dumps(
        {"template_text": template_text, "known_field_names": known_field_names or []},
        ensure_ascii=False,
    )
    raw = completion_fn(system_prompt, payload)
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MalformedModelResponse(f"field-detection reply is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise MalformedModelResponse("field-detection reply must be a JSON array")
    return _clean_suggestions(data, template_text)


def apply_suggestions_to_docx(
    template_path: Path, suggestions: list[dict[str, str]], output_path: Path
) -> list[str]:
    doc = Document(str(template_path))
    inserted: list[str] = []
    for paragraph in _iter_all_paragraphs(doc):
        if not paragraph.runs:
            continue
        text = _paragraph_text(paragraph)
        changed = False
        for item in suggestions:
            example, field_name = item["example_text"], item["field_name"]
            if example in text:
                text = text.replace(example, f"{{{{{field_name}}}}}")
                changed = True
                if field_name not in inserted:
                    inserted.append(field_name)
        if changed:
            paragraph.runs[0].text = text
            for run in paragraph.runs[1:]:
                run.text = ""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    return inserted

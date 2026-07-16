"""Register a real .docx file as an available template.

If the uploaded file already contains {{field}} placeholders they're used
as-is. If it doesn't, pass a completion_fn (e.g. openai_completion_fn()) to
have the model propose candidate fields extractively - each suggestion is
verified against the document's literal text before being trusted (see
docx_template._clean_suggestions).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Optional

from . import docx_template
from .llm_client import DEFAULT_MODEL, CompletionFn, openai_completion_fn
from .templates import Template, TemplateStore

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data"
TEMPLATES_DIR = DATA_DIR / "templates"
TEMPLATES_JSON = DATA_DIR / "available_templates.json"


class TemplateRegistrationError(RuntimeError):
    pass


def _slugify(name: str) -> str:
    return re.sub(r"[^\w؀-ۿ]+", "_", name).strip("_") or "template"


def register_docx_template(
    source_docx: Path,
    name: str,
    applies_to: str,
    templates_dir: Path,
    templates: TemplateStore,
    known_field_names: Optional[list[str]] = None,
    completion_fn: Optional[CompletionFn] = None,
) -> Template:
    fields = docx_template.extract_placeholders(source_docx)
    stored_path = templates_dir / f"{_slugify(name)}.docx"

    if fields:
        templates_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(source_docx, stored_path)
    else:
        if completion_fn is None:
            raise TemplateRegistrationError(
                "لا توجد متغيرات {{...}} صريحة في القالب، ولا يوجد completion_fn "
                "للتعرف التلقائي عليها - أضف الصيغة يدويًا أو مرّر --auto"
            )
        text = docx_template.extract_full_text(source_docx)
        suggestions = docx_template.suggest_placeholders_with_llm(
            text, completion_fn, known_field_names=known_field_names
        )
        if not suggestions:
            raise TemplateRegistrationError("تعذّر التعرف تلقائيًا على أي حقول متغيرة في هذا القالب")
        fields = docx_template.apply_suggestions_to_docx(source_docx, suggestions, stored_path)

    template = Template(name=name, applies_to=applies_to, fields=fields, source_path=str(stored_path))
    templates.add(template)
    return template


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="سجّل قالب Word (.docx) جديد في النظام")
    parser.add_argument("docx_path")
    parser.add_argument("name")
    parser.add_argument("applies_to")
    parser.add_argument(
        "--auto", action="store_true",
        help="استخدم النموذج للتعرف على المتغيرات تلقائيًا لو ما فيه {{...}} صريحة بالقالب",
    )
    args = parser.parse_args(argv)

    templates = TemplateStore.from_file(TEMPLATES_JSON)
    known_fields = sorted({f for name in templates.names() for f in templates.get(name).fields})

    completion_fn = None
    if args.auto:
        if not os.environ.get("OPENAI_API_KEY"):
            print("OPENAI_API_KEY غير مضبوط - مطلوب لاستخدام --auto", file=sys.stderr)
            sys.exit(1)
        completion_fn = openai_completion_fn(model=os.environ.get("ASDC_MODEL", DEFAULT_MODEL))

    try:
        template = register_docx_template(
            Path(args.docx_path), args.name, args.applies_to, TEMPLATES_DIR, templates,
            known_field_names=known_fields, completion_fn=completion_fn,
        )
    except TemplateRegistrationError as exc:
        print(f"[فشل التسجيل] {exc}", file=sys.stderr)
        sys.exit(1)

    templates.save(TEMPLATES_JSON)
    print(f"تم تسجيل القالب '{template.name}' (applies_to={template.applies_to})")
    print(f"الحقول المكتشفة: {template.fields}")
    print(f"مسار الملف المخزّن: {template.source_path}")


if __name__ == "__main__":
    main()

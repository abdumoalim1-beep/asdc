"""HTTP layer over the real engine: same classify -> validate -> execute
pipeline as cli.py, just exposed as JSON endpoints for the web UI instead of
a REPL. No behavior lives here that isn't already in llm_client/validator/
executor - this module only translates between HTTP and those calls.

Run with: uvicorn asdc.server:app --reload
Requires OPENAI_API_KEY in the environment.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .executor import ExecutionRefused, execute
from .llm_client import DEFAULT_MODEL, LLMClient, MalformedModelResponse, openai_completion_fn
from .register_template import TemplateRegistrationError, register_docx_template
from .store import EntityStore
from .templates import TemplateStore

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data"
DOCUMENTS_DIR = REPO_ROOT / "documents"
TEMPLATES_DIR = DATA_DIR / "templates"
WEB_DIR = REPO_ROOT / "web"
WORKSPACE_NAME = "الوكالة الرئيسية"

app = FastAPI(title="asdc")

entities = EntityStore.from_file(DATA_DIR / "workspace_entities.json")
templates = TemplateStore.from_file(DATA_DIR / "available_templates.json")
_client: Optional[LLMClient] = None


def get_client() -> LLMClient:
    global _client
    if _client is None:
        model = os.environ.get("ASDC_MODEL", DEFAULT_MODEL)
        _client = LLMClient(openai_completion_fn(model=model))
    return _client


def lazy_openai_completion_fn(model: str):
    """Defer building the OpenAI client until a call is actually made.

    register_docx_template only invokes completion_fn when a template has no
    explicit {{field}} placeholders - most uploads won't need it, so this
    avoids requiring OPENAI_API_KEY for those.
    """
    built: dict = {}

    def _call(system_prompt: str, payload: str) -> str:
        if "fn" not in built:
            built["fn"] = openai_completion_fn(model=model)
        return built["fn"](system_prompt, payload)

    return _call


def template_context() -> list[dict]:
    return [
        {"name": t.name, "applies_to": t.applies_to, "fields": t.fields}
        for t in (templates.get(n) for n in templates.names())
    ]


class ChatRequest(BaseModel):
    message: str
    history: list[dict[str, str]] = []


class ChatResponse(BaseModel):
    intent: str
    confidence: str = "high"
    human_message: str
    clarification_needed: Optional[str] = None
    detail: dict = {}
    error: Optional[str] = None


@app.get("/api/state")
def state() -> dict:
    stats: dict[str, int] = {}
    for e in entities.all():
        stats[e.type] = stats.get(e.type, 0) + 1

    files = []
    for e in entities.all():
        for doc in e.documents:
            files.append(
                {
                    "id": doc["id"],
                    "template": doc["template"],
                    "status": doc["status"],
                    "created_at": doc["created_at"],
                    "entity_id": e.id,
                    "entity_name": e.name,
                }
            )
    files.sort(key=lambda d: d["id"], reverse=True)

    return {"workspace_name": WORKSPACE_NAME, "stats": stats, "files": files}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    try:
        response = get_client().classify(
            req.message,
            [e.to_dict() for e in entities.all()],
            template_context(),
            req.history,
        )
    except MalformedModelResponse as exc:
        return ChatResponse(
            intent="error", human_message="صار خطأ بفهم رد النموذج، جرّب مرة ثانية.", error=str(exc)
        )

    if response.intent in ("ambiguous", "unsupported", "chat"):
        return ChatResponse(
            intent=response.intent,
            confidence=response.confidence,
            human_message=response.human_message,
            clarification_needed=response.clarification_needed,
        )

    try:
        result = execute(response, entities, templates, DOCUMENTS_DIR)
    except ExecutionRefused as exc:
        return ChatResponse(
            intent="refused",
            confidence=response.confidence,
            human_message=response.human_message,
            error=str(exc),
        )

    entities.save()
    return ChatResponse(
        intent=response.intent,
        confidence=response.confidence,
        human_message=result.human_message,
        detail=result.detail,
    )


@app.post("/api/templates/upload")
async def upload_template(
    file: UploadFile = File(...), name: str = Form(...), applies_to: str = Form(...)
) -> dict:
    tmp_dir = Path(tempfile.mkdtemp())
    tmp_path = tmp_dir / (file.filename or "template.docx")
    tmp_path.write_bytes(await file.read())

    known_fields = sorted({f for n in templates.names() for f in templates.get(n).fields})
    model = os.environ.get("ASDC_MODEL", DEFAULT_MODEL)
    try:
        template = register_docx_template(
            tmp_path, name, applies_to, TEMPLATES_DIR, templates,
            known_field_names=known_fields, completion_fn=lazy_openai_completion_fn(model),
        )
    except TemplateRegistrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    templates.save(DATA_DIR / "available_templates.json")
    return {"name": template.name, "applies_to": template.applies_to, "fields": template.fields}


if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

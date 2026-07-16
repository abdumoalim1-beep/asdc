"""HTTP layer over the tool-calling agent (agent.py).

Every workspace is isolated (workspace.py): a brand-new visitor gets a
brand-new, completely empty workspace and onboards by talking to the
assistant - no forms, no pre-seeded demo data. All the safety rules still
live in validator.py/executor.py, unchanged; this module only wires HTTP
around agent.run_turn and the workspace registry.

Run with: uvicorn asdc.server:app --reload
Requires OPENAI_API_KEY in the environment for actual chat turns (browsing
the static UI and creating workspaces works without it).
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agent
from .register_template import TemplateRegistrationError, register_docx_template
from .workspace import WorkspaceNotFound, WorkspaceRegistry

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data"
WEB_DIR = REPO_ROOT / "web"

app = FastAPI(title="asdc")
registry = WorkspaceRegistry(DATA_DIR / "workspaces")

_model_call: Optional[agent.ModelCallFn] = None


def get_model_call() -> agent.ModelCallFn:
    global _model_call
    if _model_call is None:
        model = os.environ.get("ASDC_MODEL", agent.DEFAULT_MODEL)
        _model_call = agent.openai_tool_model(model=model)
    return _model_call


def _lazy_completion_fn(model: str):
    """CompletionFn-shaped lazy wrapper for register_docx_template's LLM
    auto-detect path - only builds an OpenAI client if actually called."""
    from .llm_client import openai_completion_fn

    built: dict = {}

    def _call(system_prompt: str, payload: str) -> str:
        if "fn" not in built:
            built["fn"] = openai_completion_fn(model=model)
        return built["fn"](system_prompt, payload)

    return _call


@app.exception_handler(WorkspaceNotFound)
def _workspace_not_found_handler(request: Request, exc: WorkspaceNotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": f"workspace not found: {exc}"})


class CreateWorkspaceRequest(BaseModel):
    name: str = "مساحة عمل جديدة"


class WorkspaceOut(BaseModel):
    id: str
    name: str
    created_at: str


class ChatRequest(BaseModel):
    message: str


class ActionOut(BaseModel):
    tool: str
    ok: bool
    detail: dict = {}
    error: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    actions: list[ActionOut]


@app.post("/api/workspaces", response_model=WorkspaceOut)
def create_workspace(req: CreateWorkspaceRequest) -> WorkspaceOut:
    info = registry.create(req.name)
    return WorkspaceOut(id=info.id, name=info.name, created_at=info.created_at)


@app.get("/api/workspaces/{workspace_id}/state")
def workspace_state(workspace_id: str) -> dict:
    info = registry.require(workspace_id)
    entities, _templates = registry.load_stores(workspace_id)

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

    return {
        "workspace_id": info.id,
        "workspace_name": info.name,
        "is_new": not entities.all() and not files,
        "stats": stats,
        "files": files,
    }


@app.post("/api/workspaces/{workspace_id}/chat", response_model=ChatResponse)
def chat(workspace_id: str, req: ChatRequest) -> ChatResponse:
    registry.require(workspace_id)
    entities, templates = registry.load_stores(workspace_id)
    history = registry.load_conversation(workspace_id)
    documents_dir = registry.path(workspace_id) / "documents"

    result = agent.run_turn(
        get_model_call(), entities, templates, documents_dir, history, req.message
    )
    registry.save_conversation(workspace_id, result.messages)

    return ChatResponse(
        reply=result.reply,
        actions=[
            ActionOut(tool=a.tool, ok=a.ok, detail=a.detail, error=a.error) for a in result.actions
        ],
    )


@app.post("/api/workspaces/{workspace_id}/templates/upload")
async def upload_template(
    workspace_id: str,
    file: UploadFile = File(...),
    name: str = Form(...),
    applies_to: str = Form(...),
) -> dict:
    registry.require(workspace_id)
    _entities, templates = registry.load_stores(workspace_id)
    workspace_path = registry.path(workspace_id)

    tmp_dir = Path(tempfile.mkdtemp())
    tmp_path = tmp_dir / (file.filename or "template.docx")
    tmp_path.write_bytes(await file.read())

    known_fields = sorted({f for n in templates.names() for f in templates.get(n).fields})
    model = os.environ.get("ASDC_MODEL", agent.DEFAULT_MODEL)
    try:
        template = register_docx_template(
            tmp_path, name, applies_to, workspace_path / "templates", templates,
            known_field_names=known_fields, completion_fn=_lazy_completion_fn(model),
        )
    except TemplateRegistrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    templates.save(workspace_path / "templates.json")
    return {"name": template.name, "applies_to": template.applies_to, "fields": template.fields}


if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from asdc.store import EntityStore  # noqa: E402
from asdc.templates import TemplateStore  # noqa: E402

DATA_DIR = REPO_ROOT / "data"


@pytest.fixture
def entities() -> EntityStore:
    return EntityStore.from_file(DATA_DIR / "workspace_entities.json")


@pytest.fixture
def templates() -> TemplateStore:
    return TemplateStore.from_file(DATA_DIR / "available_templates.json")


@pytest.fixture
def documents_dir(tmp_path: Path) -> Path:
    return tmp_path / "documents"

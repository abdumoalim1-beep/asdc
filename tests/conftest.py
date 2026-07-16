import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from asdc.store import EntityStore  # noqa: E402
from asdc.templates import TemplateStore  # noqa: E402

DATA_DIR = REPO_ROOT / "data"


@pytest.fixture
def entities(tmp_path: Path) -> EntityStore:
    # Load from a copy, never the tracked file - a store.save() call during
    # a test must not be able to mutate the real repo data.
    copy_path = tmp_path / "workspace_entities.json"
    shutil.copy(DATA_DIR / "workspace_entities.json", copy_path)
    return EntityStore.from_file(copy_path)


@pytest.fixture
def templates(tmp_path: Path) -> TemplateStore:
    copy_path = tmp_path / "available_templates.json"
    shutil.copy(DATA_DIR / "available_templates.json", copy_path)
    return TemplateStore.from_file(copy_path)


@pytest.fixture
def documents_dir(tmp_path: Path) -> Path:
    return tmp_path / "documents"

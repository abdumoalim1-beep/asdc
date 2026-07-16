from asdc.workspace import WorkspaceNotFound, WorkspaceRegistry


def test_create_gives_fresh_empty_workspace(tmp_path):
    registry = WorkspaceRegistry(tmp_path / "workspaces")
    info = registry.create("شركة تجريبية")

    entities, templates = registry.load_stores(info.id)
    assert entities.all() == []
    assert templates.names() == []
    assert (registry.path(info.id) / "documents").is_dir()
    assert (registry.path(info.id) / "templates").is_dir()


def test_registry_persists_across_instances(tmp_path):
    root = tmp_path / "workspaces"
    info = WorkspaceRegistry(root).create("شركة أ")
    reopened = WorkspaceRegistry(root)
    assert reopened.get_info(info.id).name == "شركة أ"


def test_require_raises_for_unknown_workspace(tmp_path):
    registry = WorkspaceRegistry(tmp_path / "workspaces")
    try:
        registry.require("does-not-exist")
        assert False, "expected WorkspaceNotFound"
    except WorkspaceNotFound:
        pass


def test_conversation_round_trips(tmp_path):
    registry = WorkspaceRegistry(tmp_path / "workspaces")
    info = registry.create()
    assert registry.load_conversation(info.id) == []
    registry.save_conversation(info.id, [{"role": "user", "content": "مرحبا"}])
    assert registry.load_conversation(info.id) == [{"role": "user", "content": "مرحبا"}]


def test_two_workspaces_are_isolated(tmp_path):
    registry = WorkspaceRegistry(tmp_path / "workspaces")
    a = registry.create("أ")
    b = registry.create("ب")

    entities_a, _ = registry.load_stores(a.id)
    entities_a.add(type="عميل", name="عميل في مساحة أ", fields={})
    entities_a.save()

    entities_b, _ = registry.load_stores(b.id)
    assert entities_b.all() == []

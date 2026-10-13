from pathlib import Path

from firmware_agent.project_layout import (
    GENERATED_ARTIFACT_FILES,
    REQUIRED_FILES,
    SYSTEM_DESIGN_REL_PATH,
    ensure_project_layout,
    inspect_project_layout,
    reset_system_design_template,
)


def test_ensure_project_layout_creates_required_tree(tmp_path: Path):
    project = tmp_path / "demo"
    report = ensure_project_layout(project)

    assert (project / "Docs" / "config.yaml").exists()
    assert (project / "Docs" / "prd" / "requirements.md").exists()
    assert (project / "Docs" / "hardware" / "registers").exists()
    assert (project / "Docs" / "hardware" / "pin_map.json").exists()
    assert (project / "Docs" / "bsp").exists()
    assert (project / "Docs" / "toolchain" / "build.yaml").exists()
    assert (project / "Docs" / "ai-generation").exists()
    assert (project / "Docs" / "ai-generation" / "fw-architecture" / "system-design" / "system-design.md").exists()
    assert (project / "Docs" / "ai-generation" / "system-design.compiled.json").exists()
    assert (project / "Docs" / "ai-generation" / "fw-architecture" / "README.md").exists()
    assert (project / "Docs" / "ai-generation" / "fw-architecture" / "architecture" / "architecture.mmd").exists()
    assert (project / "Docs" / "ai-generation" / "fw-architecture" / "module-design" / "module-design.md").exists()
    assert (project / "Docs" / "ai-generation" / "register-init" / "README.md").exists()
    assert (project / "Docs" / "ai-generation" / "dev-environment" / "README.md").exists()
    assert (project / "Docs" / "ai-generation" / "knowledge" / "rules.json").exists()
    assert (project / "Docs" / "ai-generation" / "knowledge" / "requirements_index.json").exists()
    assert (project / "Docs" / "ai-generation" / "knowledge" / "register_index.json").exists()
    assert (project / "Docs" / "ai-generation" / "knowledge" / "artifact_graph.json").exists()
    assert (project / "Docs" / "ai-generation" / "memory" / "candidate_memory.json").exists()
    assert report.created_dirs or report.created_files


def test_inspect_project_layout_no_missing_after_ensure(tmp_path: Path):
    project = tmp_path / "demo2"
    ensure_project_layout(project)

    items = inspect_project_layout(project)
    assert items
    assert all(item.exists for item in items)


def test_reset_schema_template_overwrites_file(tmp_path: Path):
    project = tmp_path / "demo3"
    ensure_project_layout(project)
    schema_path = project / SYSTEM_DESIGN_REL_PATH

    schema_path.write_text("BROKEN", encoding="utf-8")
    reset_system_design_template(project)

    content = schema_path.read_text(encoding="utf-8")
    assert "# Embedded-Pi System Design Schema" in content
    assert "## SCHEMA" in content


def test_incremental_sync_preserves_user_docs_and_updates_managed_files(tmp_path: Path):
    project = tmp_path / "demo4"
    ensure_project_layout(project)

    user_prd = project / "Docs" / "prd" / "requirements.md"
    managed_readme = project / "Docs" / "ai-generation" / "fw-architecture" / "README.md"

    user_prd.write_text("# User PRD\n\nDo not overwrite me.\n", encoding="utf-8")
    managed_readme.write_text("stale bootstrap content\n", encoding="utf-8")

    report = ensure_project_layout(project)

    assert user_prd.read_text(encoding="utf-8") == "# User PRD\n\nDo not overwrite me.\n"
    assert managed_readme.read_text(encoding="utf-8") == REQUIRED_FILES["Docs/ai-generation/fw-architecture/README.md"]
    assert "Docs/ai-generation/fw-architecture/README.md" in report.updated_files


def test_incremental_sync_does_not_overwrite_system_design_without_reset(tmp_path: Path):
    project = tmp_path / "demo5"
    ensure_project_layout(project)
    schema_path = project / SYSTEM_DESIGN_REL_PATH

    schema_path.write_text("# Custom Schema\n", encoding="utf-8")
    ensure_project_layout(project)

    assert schema_path.read_text(encoding="utf-8") == "# Custom Schema\n"


def test_incremental_sync_preserves_generated_artifacts(tmp_path: Path):
    """Generated outputs must survive repeated `epi` runs.

    Regression: they resolved to SYNC_MANAGED, so ensure_project_layout() rewrote them
    back to their empty seed template on every run - and it runs before the workflow
    that produces them.
    """
    project = tmp_path / "demo6"
    ensure_project_layout(project)

    payload = '{"version":"custom","rules":[{"id":"R1"}]}\n'
    touched = []
    for rel in sorted(GENERATED_ARTIFACT_FILES):
        target = project / rel
        target.write_text(payload, encoding="utf-8")
        touched.append(target)

    report = ensure_project_layout(project)

    for target in touched:
        assert target.read_text(encoding="utf-8") == payload
    assert not set(report.updated_files) & GENERATED_ARTIFACT_FILES


def test_generated_requirements_survive_layout_resync(tmp_path: Path):
    """Exact incident: ingest_prd wrote requirements, a later bare `epi` run wiped them."""
    project = tmp_path / "demo7"
    ensure_project_layout(project)

    index = project / "Docs" / "ai-generation" / "knowledge" / "requirements_index.json"
    index.write_text(
        '{"version":"0.1","requirements":[{"req_id":"R-001","title":"Power On/Off"}]}\n',
        encoding="utf-8",
    )

    ensure_project_layout(project)

    assert "Power On/Off" in index.read_text(encoding="utf-8")


def test_static_scaffold_is_still_synced(tmp_path: Path):
    """The fix must not disable syncing of genuinely static ai-generation scaffolds."""
    project = tmp_path / "demo8"
    ensure_project_layout(project)

    readme = project / "Docs" / "ai-generation" / "fw-architecture" / "README.md"
    readme.write_text("# stale\n", encoding="utf-8")

    report = ensure_project_layout(project)

    assert readme.read_text(encoding="utf-8") == REQUIRED_FILES["Docs/ai-generation/fw-architecture/README.md"]
    assert "Docs/ai-generation/fw-architecture/README.md" in report.updated_files

from pathlib import Path

from firmware_agent.project_layout import (
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


def test_incremental_sync_overwrites_generated_knowledge_files(tmp_path: Path):
    project = tmp_path / "demo6"
    ensure_project_layout(project)

    generated_rules = project / "Docs" / "ai-generation" / "knowledge" / "rules.json"
    generated_rules.write_text('{"version":"custom","rules":[{"id":"R1"}]}\n', encoding="utf-8")

    report = ensure_project_layout(project)

    assert generated_rules.read_text(encoding="utf-8") == REQUIRED_FILES["Docs/ai-generation/knowledge/rules.json"]
    assert "Docs/ai-generation/knowledge/rules.json" in report.updated_files

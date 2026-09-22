import json
from pathlib import Path

from firmware_agent.project_layout import ensure_project_layout
from firmware_agent.schema.compiler import compile_system_design


def test_schema_compile_from_template(tmp_path: Path):
    project = tmp_path / "schema-demo"
    ensure_project_layout(project)

    ok, msg = compile_system_design(project)
    assert ok, msg

    assert (project / "Docs" / "ai-generation" / "system-design.compiled.json").exists()
    assert (project / "Docs" / "ai-generation" / "fw-architecture" / "architecture" / "architecture.json").exists()
    assert (project / "Docs" / "ai-generation" / "fw-architecture" / "module-design" / "module_design_table.json").exists()
    assert (project / "Docs" / "ai-generation" / "register-init" / "register_init_table.json").exists()
    assert (project / "Docs" / "ai-generation" / "dev-environment" / "dev_environment.json").exists()


def test_schema_compile_reads_mermaid_from_mmd_file(tmp_path: Path):
    project = tmp_path / "schema-demo-mmd"
    ensure_project_layout(project)

    ok, msg = compile_system_design(project)
    assert ok, msg

    compiled = json.loads(
        (project / "Docs" / "ai-generation" / "system-design.compiled.json").read_text(encoding="utf-8")
    )
    mermaid = compiled["LAYER_ARCHITECTURE_GRAPH"]["mermaid"]
    assert "flowchart TB" in mermaid
    assert "D1 --> M1 --> O1 --> T1" in mermaid

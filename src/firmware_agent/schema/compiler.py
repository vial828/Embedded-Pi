from __future__ import annotations

import json
from pathlib import Path

from firmware_agent.schema.parser import parse_system_design
from firmware_agent.schema.validator import validate_parsed


def compile_system_design(project_dir: Path) -> tuple[bool, str]:
    docs_root = project_dir / "Docs"
    md_path = docs_root / "ai-generation" / "fw-architecture" / "system-design" / "system-design.md"
    if not md_path.exists():
        legacy_path = docs_root / "ai-generation" / "system-design.md"
        if legacy_path.exists():
            md_path = legacy_path
        else:
            return False, f"missing schema file: {md_path}"

    parsed = parse_system_design(md_path)
    errors = validate_parsed(parsed)
    if errors:
        return False, "\n".join(errors)

    out_root = docs_root / "ai-generation"
    (out_root / "fw-architecture" / "architecture").mkdir(parents=True, exist_ok=True)
    (out_root / "fw-architecture" / "module-design").mkdir(parents=True, exist_ok=True)
    (out_root / "register-init").mkdir(parents=True, exist_ok=True)
    (out_root / "dev-environment").mkdir(parents=True, exist_ok=True)

    (out_root / "system-design.compiled.json").write_text(
        json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_root / "fw-architecture" / "architecture" / "architecture.json").write_text(
        json.dumps(parsed.get("LAYER_ARCHITECTURE_GRAPH", {}), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_root / "fw-architecture" / "module-design" / "module_design_table.json").write_text(
        json.dumps(parsed.get("MODULE_DESIGN_TABLE", {}), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_root / "register-init" / "register_init_table.json").write_text(
        json.dumps(parsed.get("REGISTER_INIT_TABLE", {}), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_root / "dev-environment" / "dev_environment.json").write_text(
        json.dumps(parsed.get("DEV_ENVIRONMENT", {}), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return True, f"compiled schema: {out_root / 'system-design.compiled.json'}"

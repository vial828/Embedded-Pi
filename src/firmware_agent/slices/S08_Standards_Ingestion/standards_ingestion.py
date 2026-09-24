from __future__ import annotations

import json
from pathlib import Path


def ingest_standards(docs_root: Path) -> Path:
    standards_dir = docs_root / "standards"
    out = docs_root / "ai-generation" / "knowledge" / "rules.json"
    out.parent.mkdir(parents=True, exist_ok=True)

    rules: list[dict] = []
    for name in ["coding_standard.md", "constitution.md"]:
        p = standards_dir / name
        if not p.exists():
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            rules.append(
                {
                    "source_id": f"STD-{name.upper()}-{i:03d}",
                    "text": line,
                    "source_path": str(p).replace("\\", "/"),
                }
            )

    out.write_text(json.dumps({"version": "0.1", "rules": rules}, ensure_ascii=False, indent=2), encoding="utf-8")
    return out

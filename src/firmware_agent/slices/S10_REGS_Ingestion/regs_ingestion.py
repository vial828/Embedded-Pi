from __future__ import annotations

import json
from pathlib import Path


def ingest_registers(docs_root: Path) -> Path:
    regs_dir = docs_root / "hardware" / "registers"
    out = docs_root / "ai-generation" / "knowledge" / "register_index.json"
    out.parent.mkdir(parents=True, exist_ok=True)

    items: list[dict] = []
    if regs_dir.exists():
        idx = 1
        for p in sorted(regs_dir.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8") or "{}")
            except Exception:
                data = {}
            items.append(
                {
                    "id": f"REG-{idx:03d}",
                    "source_id": f"REGSRC-{idx:03d}",
                    "file": str(p).replace("\\", "/"),
                    "keys": sorted(list(data.keys())) if isinstance(data, dict) else [],
                }
            )
            idx += 1

    out.write_text(json.dumps({"version": "0.1", "register_items": items}, ensure_ascii=False, indent=2), encoding="utf-8")
    return out

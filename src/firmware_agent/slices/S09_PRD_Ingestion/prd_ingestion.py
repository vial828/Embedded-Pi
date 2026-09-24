from __future__ import annotations

import json
from pathlib import Path


def ingest_prd(docs_root: Path) -> Path:
    prd_path = docs_root / "prd" / "requirements.md"
    out = docs_root / "ai-generation" / "knowledge" / "requirements_index.json"
    out.parent.mkdir(parents=True, exist_ok=True)

    reqs: list[dict] = []
    if prd_path.exists():
        rid = 1
        for line in prd_path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            reqs.append(
                {
                    "req_id": f"R-{rid:03d}",
                    "text": text,
                    "source": str(prd_path).replace("\\", "/"),
                    "source_id": f"PRD-{rid:03d}",
                }
            )
            rid += 1

    out.write_text(json.dumps({"version": "0.1", "requirements": reqs}, ensure_ascii=False, indent=2), encoding="utf-8")
    return out

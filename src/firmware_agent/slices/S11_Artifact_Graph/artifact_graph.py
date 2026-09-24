from __future__ import annotations

import json
from pathlib import Path


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8") or "{}")


def build_artifact_graph(docs_root: Path) -> Path:
    knowledge = docs_root / "ai-generation" / "knowledge"
    out = knowledge / "artifact_graph.json"
    knowledge.mkdir(parents=True, exist_ok=True)

    reqs = _load(knowledge / "requirements_index.json").get("requirements", [])
    regs = _load(knowledge / "register_index.json").get("register_items", [])

    nodes = []
    edges = []

    for r in reqs:
        rid = r.get("req_id", "N/A")
        nodes.append({"id": rid, "type": "requirement"})

    for reg in regs:
        gid = reg.get("id", "N/A")
        nodes.append({"id": gid, "type": "register_source"})

    for r in reqs:
        for reg in regs:
            edges.append(
                {
                    "src": r.get("req_id", "N/A"),
                    "dst": reg.get("id", "N/A"),
                    "type": "may_impact",
                }
            )

    out.write_text(json.dumps({"version": "0.1", "nodes": nodes, "edges": edges}, ensure_ascii=False, indent=2), encoding="utf-8")
    return out

"""Derive development order from a Mermaid diagram, using the shared rules.

Development order is a derived quantity: the longest path over the edge classes
marked `"ordering": true` in graph-rules.json, SCC-condensed so a genuine
feedback loop collapses into one column instead of breaking the ordering.

    python tools/derive_dev_order.py [name.graph.json]
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):   # Windows 控制台默认 cp936/cp1252，中文会炸
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_interactive_graph as g  # noqa: E402
import mermaid_doc  # noqa: E402


def main() -> int:
    cfg_path = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).resolve().parents[1] / "epi-dev-slices-overview.graph.json")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    base = cfg_path.parent
    rules = g.load_rules((base / cfg["rules"]).resolve())
    doc = mermaid_doc.parse((base / cfg["mmd"]).read_text(encoding="utf-8"))
    edges = g.classify(doc, rules)

    ordering = set(rules.get("layering", {}).get("classes") or
                   [p["class"] for p in rules["palette"] if p.get("ordering")])
    labelled = {p["class"]: p["title"] for p in rules["palette"]}
    print(f"{cfg['mmd']}  排序类别: {' + '.join(sorted(labelled[c] for c in ordering))}")
    kinds = Counter(e["kind"] for e in edges)
    print("边: " + " / ".join(f"{labelled.get(k, k)} {v}" for k, v in sorted(kinds.items())))

    lvl, loop, members = g.levels(edges, ordering, doc.no_layout_ids())
    # 同环节点合并成一个单元，只标一次 ⟳
    groups = defaultdict(list)
    for n, cid in members.items():
        groups[cid].append(n)
    unit = {}
    for cid, ns in groups.items():
        for n in ns:
            unit[n] = "{" + ",".join(sorted(ns)) + "}"
    comps = defaultdict(list)
    all_nodes = set(lvl) | {e["src"] for e in edges} | {e["dst"] for e in edges}
    for n in all_nodes:
        comps[lvl.get(n, 0)].append(unit.get(n, n))
    for l in comps:
        comps[l] = sorted(set(comps[l]))

    direct = defaultdict(set)
    for e in edges:
        if e["kind"] in ordering:
            direct[e["dst"]].add(e["src"])

    print("\n=== 开发顺序（{} = 同一环，须一起设计或先钉接口）===")
    for l in sorted(comps):
        print(f"  L{l}  {'  '.join(comps[l])}")

    print("\n=== 直接数据前驱（可与之对照文档「开发依赖」列）===")
    for n in sorted(direct):
        print(f"  {n} <- {' '.join(sorted(direct[n]))}")
    if loop:
        print(f"\n数据环: {' '.join(sorted(loop))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

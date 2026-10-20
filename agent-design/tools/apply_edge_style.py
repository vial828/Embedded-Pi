"""Regenerate the linkStyle block of a Mermaid flowchart from its own arrows.

The edge class - and therefore its colour - is read off the file, not from a
hand-maintained table:

    -->                       the palette entry declaring syntax "solid"
    -.->                      the entry declaring "dashed"
    -.-> with a ？ in label    the entry declaring "dashed?"

so the tool is idempotent: run it twice, nothing changes. Colours come from
graph-rules.json, which is also what the interactive renderer uses - the two can
no longer disagree.

    python tools/apply_edge_style.py <file.mmd> <file.md> [--rules graph-rules.json]

Why this exists: the style block used to be hand-written, 133 lines for 82 links,
50 indices assigned twice, and the picture rendered a third of its solid edges in
orange while its own comment said otherwise.
"""

import argparse
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_interactive_graph as graph_tool  # noqa: E402
import mermaid_doc  # noqa: E402
import sync_diagram_md  # noqa: E402

LINK_LINE = re.compile(r"^(\s*)(\S.*?)\s*(-->|-\.->)\s*(?:\|([^|]*)\|\s*)?(\S.*?)\s*$")
STYLE_MARK = "%% 样式"
STYLE_RE = re.compile(r"^\s*%+\s*样式")


def classify(label: str, dashed: bool, rules):
    """The only judgement an editor makes: which arrow, and whether the label says ？.

    Matched against each palette entry's declared `syntax`, not against dash: once two
    classes share a line style (both solid, differing only in colour), inferring the
    class from the dash silently maps every edge onto whichever entry happens to be
    listed first.
    """
    wanted = "dashed?" if (dashed and ("？" in label or "?" in label)) else ("dashed" if dashed else "solid")
    for entry in rules["palette"]:
        if entry.get("syntax") == wanted:
            return entry["class"]
    return next(iter({p["class"]: p for p in rules["palette"]}))


def main() -> int:
    ap = argparse.ArgumentParser(description="按箭头规则重生成 linkStyle 块")
    ap.add_argument("mmd", type=Path)
    ap.add_argument("md", type=Path)
    ap.add_argument("--rules", type=Path,
                    default=Path(__file__).resolve().parent / "graph-rules.json")
    a = ap.parse_args()

    rules = graph_tool.load_rules(a.rules)
    by_class = {p["class"]: p for p in rules["palette"]}
    default_class = next((p["class"] for p in rules["palette"] if p.get("ordering")), None)

    src = a.mmd.read_text(encoding="utf-8").rstrip().splitlines()
    cut = next((i for i, l in enumerate(src) if STYLE_RE.match(l)), None)
    if cut is None:
        raise SystemExit(f"{a.mmd.name} 里找不到 `{STYLE_MARK}` 样式块起始标记")
    body = src[:cut]
    while body and not body[-1].strip():
        body.pop()   # 否则每跑一次多一个空行

    doc = mermaid_doc.parse("\n".join(body))
    if doc.problems:
        raise SystemExit("这些行看起来是边但解析失败：\n"
                         + "\n".join(f"  line {n}: {t}" for n, t in doc.problems))
    kind_of = {i: classify(e.label, e.dashed, rules) for i, e in enumerate(doc.edges)}

    counts = {}
    for i in range(len(doc.edges)):
        counts[kind_of[i]] = counts.get(kind_of[i], 0) + 1

    style = [
        f"  {STYLE_MARK}：颜色由 tools/apply_edge_style.py 依 graph-rules.json 生成，勿手改",
        "  %% 类别只由箭头写法决定（--> 数据流，-.-> 控制流，-.->且标签含 ？ 待定），配色是输出不是输入",
        f"  linkStyle default stroke:{by_class[default_class]['stroke'].upper()},"
        f"stroke-width:{by_class[default_class].get('width', '2.2px')}",
    ]
    for i in range(len(doc.edges)):
        spec = by_class[kind_of[i]]
        width = "3.2px" if spec.get("warn") else "2.2px"
        line = f"  linkStyle {i} stroke:{spec['stroke'].upper()},stroke-width:{width}"
        # A `-.->` arrow carries its own dash pattern. Setting only the colour leaves
        # it dotted, which is how "solid blue" came out looking like a dotted line:
        # solid classes must clear the pattern explicitly.
        line += ",stroke-dasharray:6 3" if spec.get("dash") else ",stroke-dasharray:0"
        style.append(line)

    a.mmd.write_text("\n".join(body + [""] + style) + "\n", encoding="utf-8")
    sync_diagram_md.sync(a.mmd, a.md)
    titles = {p["class"]: p["title"] for p in rules["palette"]}
    print(f"{a.mmd.name}: {len(doc.edges)} 条 link  "
          + " ".join(f"{titles.get(k, k)}:{c}" for k, c in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())

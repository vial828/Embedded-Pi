"""Guard the slice overview: style indices, edge taxonomy, rules coverage, artefacts.

Two historical failures are pinned here.

1. The diagram carried 133 hand-written `linkStyle` lines for 82 links. 50 indices
   were assigned twice, the last assignment won, and 37 solid edges rendered
   orange. Nothing failed - the picture just lied.

2. It mixed three relations (development order, data flow, control flow) into two
   line styles, which forced 13 duplicate edges and left a third of the edges
   mis-styled.

Colour semantics come from agent-design/tools/graph-rules.json and parsing from
tools/mermaid_doc.py - the tests reuse them instead of reimplementing, so a rule
change is picked up here automatically. What is asserted is the diagram itself.
"""

import collections

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "agent-design"
TOOLS = DESIGN / "tools"
sys.path.insert(0, str(TOOLS))

import gen_interactive_graph as graph_tool  # noqa: E402
import mermaid_doc  # noqa: E402

MMD = DESIGN / "epi-dev-slices-overview.mmd"
MD = DESIGN / "epi-dev-slices-overview.md"
RULES = TOOLS / "graph-rules.json"
CONFIG = DESIGN / "epi-dev-slices-overview.graph.json"
GENERATOR = TOOLS / "gen_interactive_graph.py"
GRAPH_HTML = DESIGN / "epi-dev-slices-graph.html"

# No data cycle is expected. The agent loop (context -> task sequence -> state
# machine -> current phase back into context) used to be declared here as a legal
# data cycle; it is really control flow driving a loop, and only its content-carrying
# legs (S19 -> S17 phase/task, S17 -> S18 context) are data. Reclassifying S18 -> S19
# as workflow broke the cycle, which is the correct reading: a loop of driving should
# not appear in a data-flow graph at all.
#
# So the invariant got stronger rather than weaker: any data cycle now means someone
# put a decision into a data pipe.
DECLARED_ORDERING_CYCLES: list[frozenset[str]] = []


@pytest.fixture(scope="module")
def rules():
    return graph_tool.load_rules(RULES)


@pytest.fixture(scope="module")
def doc():
    return mermaid_doc.parse(MMD.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def edges(doc, rules):
    """Every non-legend edge with its class, as the generator sees it."""
    return graph_tool.classify(doc, rules)


def test_parse_reports_no_problems(doc):
    assert not doc.problems, f"这些行看起来是边但解析失败：{doc.problems}"


def test_no_duplicate_linkstyle_index(doc):
    raw = re.findall(r"^\s*linkStyle\s+(\d+)\b", MMD.read_text(encoding="utf-8"), re.M)
    dupe = [i for i, n in collections.Counter(raw).items() if n > 1]
    assert not dupe, f"linkStyle 索引被重复赋值，后者覆盖前者：{dupe}"
    assert raw, "一个 linkStyle 都没有，样式块丢了"


def test_every_link_is_styled_explicitly(doc):
    default = doc.link_styles.get("default")
    missing = [i for i, e in enumerate(doc.edges)
               if i not in doc.link_styles
               and (default is None or default.get("stroke") is None)]
    assert not missing, f"{len(missing)} 条 link 没有显式配色，会静默退回 default：{missing}"


def test_colours_are_registered_in_the_rules(doc, rules):
    known = {p["stroke"].lower() for p in rules["palette"]}
    unknown = {s["stroke"] for s in doc.link_styles.values()
               if s.get("stroke") and s["stroke"] not in known}
    assert not unknown, f"配色未登记在 graph-rules.json 的 palette 中：{sorted(unknown)}"


def test_colour_and_arrow_agree(doc, rules):
    """Colour carries the class, so the arrow has to say the same thing.

    Line style used to be the class (solid = 数据流, dashed = 工作流). Both are solid
    now and only 待定 keeps a dashed arrow, so the check is colour against the arrow
    form each palette entry declares. A mismatch is the same class of lie the 133-line
    hand-written style block used to tell: the picture renders something other than
    what its own syntax states.
    """
    bad = []
    for index, edge in enumerate(doc.edges):
        style = mermaid_doc.style_for(doc, index)
        spec = rules["_by_stroke"].get(style.get("stroke", "").lower())
        if spec is None:
            continue                      # 未登记的配色由生成器报错，不在这里重复
        if graph_tool.arrow_form(edge) != spec.get("syntax"):
            bad.append(f"{edge.src}->{edge.dst} 要求 {spec.get('syntax')}")
    assert not bad, f"配色与箭头写法不符：{bad}"


def test_uncertain_edges_are_marked_with_question(edges, rules):
    unmarked = [f"{e['src']}->{e['dst']}:{e['label']}" for e in edges
                if e["kind"] == "open" and not e["label"].startswith("？")]
    assert not unmarked, f"待定边必须以 ？ 开头，否则读者会当成已裁定：{unmarked}"
    mislabelled = [f"{e['src']}->{e['dst']}:{e['label']}" for e in edges
                   if e["label"].startswith("？") and e["kind"] != "open"]
    assert not mislabelled, f"带 ？ 但不是待定类别：{mislabelled}"


def test_no_duplicate_relations(edges):
    seen = collections.defaultdict(list)
    for e in edges:
        seen[(e["src"], e["dst"], e["kind"])].append(e["label"])
    dup = {k: v for k, v in seen.items() if len(v) > 1}
    assert not dup, f"同一关系画了多次：{dup}"


def test_ordering_cycles_are_declared(edges, doc, rules):
    ordering = {p["class"] for p in rules["palette"] if p.get("ordering")}
    assert ordering, "graph-rules.json 里没有任何 ordering:true 类别，开发顺序无从推导"
    _lvl, loop, _members = graph_tool.levels(edges, ordering, doc.no_layout_ids())
    found = [frozenset(sorted(loop))] if loop else []
    assert found == DECLARED_ORDERING_CYCLES, (
        f"排序类别出现未声明的环。已声明 {sorted(map(sorted, DECLARED_ORDERING_CYCLES))}，"
        f"实际 {sorted(map(sorted, found))}。环意味着有人把决策塞进了数据管道，"
        f"或者该边的类别需要重新裁定。")


def test_legend_is_declared_not_hardcoded(doc):
    assert doc.legend_ids(), "图例必须用 `%% @legend <子图id>` 声明，转换工具据此排除"
    legend = doc.legend_nodes()
    assert legend, f"图例子图 {doc.legend_ids()} 里没有节点"
    assert all(n.id.upper().startswith("L") for n in doc.nodes.values() if n.id in legend)


def test_markdown_block_matches_standalone_file():
    r = subprocess.run([sys.executable, str(TOOLS / "sync_diagram_md.py"),
                        MMD.name, MD.name, "--check"],
                       capture_output=True, text=True, cwd=str(DESIGN))
    assert r.returncode == 0, f"{r.stdout}{r.stderr}"


def test_interactive_html_is_up_to_date():
    if not GRAPH_HTML.exists():
        raise AssertionError("交互图未生成，跑 tools/gen_interactive_graph.py")
    r = subprocess.run([sys.executable, str(GENERATOR), "--check"],
                       capture_output=True, text=True, cwd=str(DESIGN))
    assert r.returncode == 0, f"交互图已过期：\n{r.stdout}{r.stderr}"
    assert CONFIG.exists(), f"缺少配置 {CONFIG.name}"

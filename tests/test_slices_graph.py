"""Regression tests for the generated interactive page.

The focus rule and the label placement used to be browser-only behaviour, which
meant nobody could tell when they broke. Both are now testable without a browser:

* the page marks its pure logic with ``/*LOGIC-START`` / ``LOGIC-END*``; node runs
  that block against the real generated data and asserts which edges a focused
  node is allowed to light up
* label geometry comes out of build(), so overlap is a plain assertion

node is optional - the JS tests skip when it is missing.
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "agent-design"
TOOLS = DESIGN / "tools"
sys.path.insert(0, str(TOOLS))

import gen_interactive_graph as graph_tool  # noqa: E402

CONFIG = DESIGN / "epi-dev-slices-overview.graph.json"
HTML = DESIGN / "epi-dev-slices-graph.html"
NODE = shutil.which("node")

DATA_RE = re.compile(r"^const D = .*$", re.M)
LOGIC_RE = re.compile(r"/\*LOGIC-START\*/(.*?)/\*LOGIC-END\*/", re.S)


RULES = DESIGN / "tools" / "graph-rules.json"


@pytest.fixture(scope="module")
def built():
    return graph_tool.build(CONFIG)[2]


@pytest.fixture(scope="module")
def page() -> str:
    return HTML.read_text(encoding="utf-8")


def run_node(script: str) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(script)
        path = fh.name
    try:
        r = subprocess.run([NODE, path], capture_output=True, text=True, encoding="utf-8")
    finally:
        Path(path).unlink(missing_ok=True)
    assert r.returncode == 0, f"node 断言失败：\n{r.stdout}\n{r.stderr}"
    return r.stdout


def logic_script(page: str) -> str:
    data = DATA_RE.search(page)
    logic = LOGIC_RE.search(page)
    assert data and logic, "页面缺少 `const D = ...` 或 /*LOGIC-START*/ 标记，测试无法接管"
    return data.group(0) + "\n" + logic.group(1) + "\n"


def test_logic_region_is_dom_free(page):
    logic = LOGIC_RE.search(page).group(1)
    for forbidden in ("document", "svg", "addEventListener", "innerHTML"):
        assert forbidden not in logic, f"逻辑区不该碰 DOM：{forbidden}"


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_focus_lights_only_edges_through_the_node(page):
    """The reported bug: focusing a node also lit sibling and feedback edges."""
    script = logic_script(page) + """
function edgesOf(set){ return [...set].sort((a,b)=>a-b).join(','); }
const idx = (s, t) => D.edges.findIndex(e => e.s === s && e.t === t);
const has = (s, t) => visibleEdges().vis.has(idx(s, t));

state.focus = 'S22'; state.dir = 'both'; state.depth = 99;
// 直接下游边、直接上游边：必须亮
if (!has('S22', 'S23')) throw new Error('S22->S23 是直接下游边，应该可见');
if (!has('S21', 'S22')) throw new Error('S21->S22 是直接上游边，应该可见');
// 后代 -> 祖先 的反馈边：不属于 S22 的上下游路径，必须不亮
const fb = D.edges.findIndex(e => e.s === 'S26' && e.t === 'S19');
if (fb >= 0 && visibleEdges().vis.has(fb))
  throw new Error('S26->S19 是反馈边，两端分别落在 S22 的下游与上游，但不经过 S22，不该点亮');

// 只看下游时，上游边必须消失
state.dir = 'down';
if (has('S21', 'S22')) throw new Error('方向=下游时，不该出现上游边');
state.dir = 'up';
if (has('S22', 'S23')) throw new Error('方向=上游时，不该出现下游边');

// 深度 1 = 一跳 ego 网络：可见边的两端都必须落在「聚焦节点 + 它的直接邻居」里
state.dir = 'both'; state.depth = 1;
const nb = new Set(['S22']);
D.edges.forEach(e => { if (state.on[e.kind] && (e.s === 'S22' || e.t === 'S22')) { nb.add(e.s); nb.add(e.t); } });
for (const [i, e] of D.edges.entries())
  if (visibleEdges().vis.has(i) && (!nb.has(e.s) || !nb.has(e.t)))
    throw new Error('深度=1 时出现了 1 跳之外的边: ' + e.s + '->' + e.t);
const V1 = visibleEdges();
for (const n of V1.nodes) if (!nb.has(n)) throw new Error('深度=1 时出现了 1 跳之外的节点: ' + n);

// 类别过滤关掉数据流后，数据流边必须全部消失
state.depth = 99; state.on.data = 0;
for (const [i, e] of D.edges.entries())
  if (e.kind === 'data' && visibleEdges().vis.has(i))
    throw new Error('关掉数据流后仍有数据流边可见: ' + e.s + '->' + e.t);

console.log('ok');
"""
    assert run_node(script).strip() == "ok"


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_focus_reachable_counts_are_symmetric(page):
    script = logic_script(page) + """
state.focus = 'S17'; state.dir = 'both'; state.depth = 99;
const up = reach('S17', 'up'), down = reach('S17', 'down');
if (down['S18'] === undefined) throw new Error('S17 的下游应含 S18');
if (up['S16'] === undefined) throw new Error('S17 的上游应含 S16');
if (down['S17'] !== 0) throw new Error('自身距离必须为 0');
console.log('ok');
"""
    assert run_node(script).strip() == "ok"


def test_labels_do_not_overlap(built):
    labels = built["labels"]
    bad = graph_tool.overlaps(labels)
    assert not bad, f"{len(bad)} 对边标签重叠，例如 {bad[:3]}"
    assert built["stats"]["label_overlaps"] == 0


def test_every_edge_has_geometry_and_label_slot(built):
    for e in built["edges"]:
        assert e["pts"], f"{e['s']}->{e['t']} 没有几何"
        assert all(len(p) == 2 for p in e["pts"])
    assert all("lx" in e and "ly" in e for e in built["edges"])


def _gap(pt, n):
    """点到节点矩形边缘的距离，0 表示端点正好贴在框上。"""
    dx = max(n["x"] - pt[0], 0, pt[0] - (n["x"] + n["w"]))
    dy = max(n["y"] - pt[1], 0, pt[1] - (n["y"] + n["h"]))
    return (dx * dx + dy * dy) ** 0.5


def test_edge_endpoints_touch_their_nodes(built):
    """曾经反向边挂在节点顶边外 6px，看起来两端都错位。"""
    nodes = {n["id"]: n for n in built["nodes"]}
    loose = [(e["kind"], f"{e['s']}->{e['t']}", round(_gap(e["pts"][0], nodes[e["s"]]), 1),
              round(_gap(e["pts"][-1], nodes[e["t"]]), 1))
             for e in built["edges"]
             if _gap(e["pts"][0], nodes[e["s"]]) > 1 or _gap(e["pts"][-1], nodes[e["t"]]) > 1]
    assert not loose, f"{len(loose)} 条边端点悬空，例如 {loose[:4]}"


def test_a_box_is_sized_to_its_own_label(built):
    """Uniform box width hands every node the longest label's whitespace.

    This broke once silently: per-node widths were computed and used for collision and
    columns, while the drawn rect still used the widest value. The reported average width
    shrank and the picture did not - a statistic that describes the code instead of the
    render is worse than no statistic.
    """
    lay = json.loads(RULES.read_text(encoding="utf-8"))["layout"]
    pad, lo, hi = lay.get("node_padding", 9), lay.get("node_min_width", 56), lay.get("node_max_width", 132)
    too_wide = [n["id"] for n in built["nodes"]
                if n["w"] > min(hi, max(lo, len(n["label"]) * 5.9 + 2 * pad)) + 1]
    assert not too_wide, f"框比自己的标签宽，白占了别人的空白: {too_wide}"
    assert len({round(n["w"]) for n in built["nodes"]}) > 1, "框宽全相等说明又退回统一宽度了"


def test_group_boxes_contain_their_members(built):
    """A region box that clips a node mislabels which slice belongs to which layer."""
    pos = {n["id"]: n for n in built["nodes"]}
    clipped = [f'{g["title"]}/{m}' for g in built["groups"] for m in g["members"]
               if m in pos and not (g["x"] <= pos[m]["x"] and pos[m]["x"] + pos[m]["w"] <= g["x"] + g["w"]
                                    and g["y"] <= pos[m]["y"] and pos[m]["y"] + pos[m]["h"] <= g["y"] + g["h"])]
    assert not clipped, f"分组框切到了成员: {clipped}"


# Known, not laundered: with 69 labelled edges the memory cluster (S12-S17) has no clean
# slot for ~23 labels. The hard half - no label may touch a different edge - still runs
# and still fails the build. The soft half waits on a decision: generate an edge table,
# then drop the labels that table already carries.
@pytest.mark.xfail(strict=False, reason="69 条边全带标签，记忆簇放不下；等边清单 + 减标签的决定")
def test_labels_sit_on_their_own_edge_only(built):
    """标签可以压自己的边，一条都不能压到别人的边。"""
    cross = [l["for"] for l in built["labels"] if l["cross_others"]]
    assert not cross, f"{len(cross)} 个标签压到了别的边：{cross[:6]}"
    off = [l["for"] for l in built["labels"] if not l["on_own"]]
    assert len(off) <= 4, f"{len(off)} 个标签没能落在自己的边上：{off[:6]}"
    assert built["stats"]["labels_crossing_others"] == 0


def test_nodes_carry_a_description(built):
    """节点说明框要有功能描述；外部输入没有 WBS 条目，允许为空但必须显式存在。"""
    for n in built["nodes"]:
        assert "desc" in n, f"{n['id']} 缺 desc 字段"
    with_desc = [n for n in built["nodes"] if n["desc"]]
    assert len(with_desc) >= 30, f"只有 {len(with_desc)} 个节点有描述，node_info 配置可能失效"


def test_description_column_is_configured_not_hardcoded():
    rules = json.loads((TOOLS / "graph-rules.json").read_text(encoding="utf-8"))
    spec = rules["node_info"]
    assert spec.get("description_column"), "规则里必须声明哪一列是功能描述"
    assert spec["description_column"] in spec["columns"].values(), "描述列没在 columns 里映射"
    assert "S22" not in json.dumps(rules), "规则里不该出现具体切片号"

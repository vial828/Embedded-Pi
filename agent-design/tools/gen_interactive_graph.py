"""Turn any Mermaid flowchart into a self-contained interactive HTML graph.

Nothing in here knows about slices, S-numbers or one particular colour scheme.
The pipeline is:

    mermaid_doc.parse()   standard Mermaid -> nodes / edges / linkStyle
    graph-rules.json      visual features (stroke, dash) -> relation classes
    <name>.graph.json     which .mmd, which output, which rules, which title

Usage:

    python agent-design/tools/gen_interactive_graph.py                 # all configs
    python agent-design/tools/gen_interactive_graph.py --check         # staleness gate
    python agent-design/tools/gen_interactive_graph.py --open          # and view it
    python agent-design/tools/gen_interactive_graph.py foo.graph.json  # one config

Layout is layered (Sugiyama-flavoured): horizontal position comes from the edge
classes marked `"ordering": true` (SCC-condensed, so a genuine feedback loop
collapses into one column), and edges spanning several columns get dummy waypoints
so the row ordering optimises what is actually drawn. Geometry and label positions
are computed here, not in the browser, which is what lets the test suite assert
that no two labels overlap.
"""

import argparse
import collections
import itertools
import json
import os
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mermaid_doc  # noqa: E402

HERE = Path(__file__).resolve().parent
CHAR_W = 5.9          # 仅用于统计/兑底，真正的量宽走 text_width()


def text_width(text, size=13, bold=False):
    """全角按整宽、半角按半宽算，粗体再加 6%。

    以前一律 5.9px/字，13px 字号下中文实际要 ~12.4px，于是每个带中文的框
    都比自己的文字窄——字跑到框外面。量宽和画字必须用同一个函数。
    粗体会比正体宽，不补这个余量就是“字压线”：框刚好等于文字宽。
    """
    w = sum(size if ord(c) > 0x2E80 else size * 0.55 for c in text)
    return w * (1.06 if bold else 1.0)

LABEL_H = 12.0


# --------------------------------------------------------------------------- #
# rules
# --------------------------------------------------------------------------- #
def line_width(text, depth=0):
    """节点标签某一行的真实渲染宽度：第一行 12px 粗体，其余 10px 正体。"""
    return text_width(text, size=12 if depth == 0 else 10, bold=depth == 0)


def box_width(lines, pad, min_w=0, max_w=float("inf")):
    """一个框必须多宽——代码和测试共用这一个定义。

    两边各自算宽度时，测试以为“窄”而图上是“宽”，字压线就漏过了测试。
    """
    return min(max_w, max(min_w, max(line_width(l, k) for k, l in enumerate(lines)) + 2 * pad))


def simplify(pts):
    """合并重复点与共线点。

    源、目标中线齐平时路由仍会吐出 (x,y)->(x2,y)->(x2,y)->(x3,y)：看着是直线，
    数据上却是四个点，也没法拿“这条边是直线”做断言。
    """
    out = [tuple(pts[0])]
    for p in pts[1:]:
        p = tuple(p)
        if abs(p[0] - out[-1][0]) < 0.01 and abs(p[1] - out[-1][1]) < 0.01:
            continue
        out.append(p)
    kept = [out[0]]
    for p, q in zip(out[1:-1], out[2:]):
        collinear = (abs(kept[-1][0] - p[0]) < 0.01 and abs(p[0] - q[0]) < 0.01) or \
                    (abs(kept[-1][1] - p[1]) < 0.01 and abs(p[1] - q[1]) < 0.01)
        if not collinear:
            kept.append(p)
    kept.append(out[-1])
    return kept


def straighten(pts, max_kink=20, span_dst=None):
    """抹掉小折弯：两段横线只差几个像素时，把它们并成一条。

    这种短竖段不是“为了避开什么”，而是端口与通道各自取 y 留下的尾差：消除它对
    绕行长度几乎无损，视觉上却能把一整片图从“每根线都在抽抬”变成直线。
    span_dst 给定时，合并后目标接点仍须落在目标框内——不能为了直线把线头挪出框。
    """
    pts = [tuple(p) for p in pts]
    for _ in range(len(pts)):
        hit = None
        for i in range(1, len(pts) - 1):
            if abs(pts[i - 1][0] - pts[i][0]) < 0.5:      # 竖段
                dy = pts[i][1] - pts[i - 1][1]
                if 0.5 < abs(dy) <= max_kink:
                    hit = (i, -dy)
                    break
        if hit is None:
            break
        i, shift = hit
        cand = pts[:i] + [(p[0], p[1] + shift) for p in pts[i:]]
        if span_dst is not None:
            cy, half = (span_dst[0] + span_dst[1]) / 2, (span_dst[1] - span_dst[0]) / 2 - 2
            if abs(cand[-1][1] - cy) > max(half, 0):
                break          # 会把接点推出目标框，宁留折弯
        pts = simplify(cand)
    return pts


def align_ports(edges, ny, h_of, out_y, in_y, port_pitch=13, max_step=45, sweeps=4):
    """把一条边的两个接点拉同一高度，让它能一条直线走完。

    原则（用户定）：对齐目标是“这条边在两个框上的接点 y 相同”，
    不是对齐框的中线、也不是先挪框——挪框会改变 slot_y 的对端排序，形成反馈震荡
    （试过：align_max_shift 放到 150 后折线反而更大）。

    只动接点就没有这个反馈。两个约束：新 y 必须同时在两个框的高度范围内；
    不得与同一侧的其他接点贴到不足 port_pitch（否则两条线在同一高度重叠）。
    两框高度带交集为空时不强求，保持原样。
    """
    for _ in range(int(sweeps)):
        moved = False
        for i, e in enumerate(edges):
            ya, yb = out_y[i], in_y[i]
            step = abs(ya - yb)
            if not 0.5 < step <= max_step:
                continue
            src, dst = e["src"], e["dst"]
            a = (ny[src] - h_of[src] / 2 + 4, ny[src] + h_of[src] / 2 - 4)
            b = (ny[dst] - h_of[dst] / 2 + 4, ny[dst] + h_of[dst] / 2 - 4)
            lo, hi = max(a[0], b[0]), min(a[1], b[1])
            if lo > hi:
                continue                                  # 两框没有交集，本就该折
            want = (ya + yb) / 2
            y = min(max(want, lo), hi)
            clash = any(abs(out_y[j] - y) < port_pitch for j in range(len(edges))
                        if j != i and edges[j]["src"] == src) or \
                    any(abs(in_y[j] - y) < port_pitch for j in range(len(edges))
                        if j != i and edges[j]["dst"] == dst)
            if clash:
                continue
            out_y[i] = in_y[i] = y
            moved = True
        if not moved:
            break
    return out_y, in_y


def load_rules(path):
    rules = json.loads(Path(path).read_text(encoding="utf-8"))
    # Keyed by colour alone. It used to be (colour, dashed), which worked only while
    # every class had its own line style: once two classes are solid and differ by
    # colour, that key either mis-classifies or rejects valid edges. Colour identifies
    # the class; the arrow is then checked against the class's declared syntax.
    rules["_by_stroke"] = {p["stroke"].lower(): p for p in rules["palette"]}
    return rules


def arrow_form(edge) -> str:
    if not edge.dashed:
        return "solid"
    return "dashed?" if ("？" in (edge.label or "") or "?" in (edge.label or "")) else "dashed"


def classify(doc, rules):
    """Attach a relation class to every edge. Index follows linkStyle numbering."""
    unknown, mismatched, out = [], [], []
    for i, e in enumerate(doc.edges):
        style = mermaid_doc.style_for(doc, i)
        stroke = style.get("stroke", "").lower()
        spec = rules["_by_stroke"].get(stroke)
        if spec is None:
            spec = rules["unknown"]
            if spec.get("reject"):
                unknown.append(f"line {e.line}: {e.src} -> {e.dst} stroke={stroke or '<none>'}")
        elif spec.get("reject") or spec.get("syntax") != arrow_form(e):
            mismatched.append(f"line {e.line}: {e.src} -> {e.dst} 配色 {stroke} 要求箭头 "
                              f"{spec.get('syntax', '?')}，实际是 {arrow_form(e)}")
            spec = rules["unknown"]
        out.append({"src": e.src, "dst": e.dst, "label": e.label, "line": e.line,
                    "index": i, "kind": spec["class"],
                    "stroke": spec.get("stroke") or stroke, "dash": bool(spec.get("dash"))})
    if unknown:
        raise SystemExit("配色未在 graph-rules.json 的 palette 中登记：\n  " + "\n  ".join(unknown))
    if mismatched:
        raise SystemExit("配色与箭头写法矛盾（箭头定类别，配色只是把它画出来）：\n  " + "\n  ".join(mismatched))
    legend = doc.legend_nodes()
    # 副本先归并回原件，且在这里做：分层、环、覆盖、HTML 都必须看到同一个拓扑。
    # 放在调用方做的话，多一个调用点就多一份口径
    alias = doc.aliases()
    for e in out:
        e["src"], e["dst"] = alias.get(e["src"], e["src"]), alias.get(e["dst"], e["dst"])
    return [e for e in out if e["src"] not in legend and e["dst"] not in legend]


# --------------------------------------------------------------------------- #
# levels: longest path over ordering edges, SCC condensed
# --------------------------------------------------------------------------- #
def levels(edges, ordering_classes, skip_nodes, sweeps=6):
    data = [(e["src"], e["dst"]) for e in edges
            if e["kind"] in ordering_classes
            and e["src"] not in skip_nodes and e["dst"] not in skip_nodes]
    adj = collections.defaultdict(set)
    for a, b in data:
        adj[a].add(b)
    nodes = {a for a, _ in data} | {b for _, b in data}

    index, low, stack, onstack, comps = {}, {}, [], set(), []
    for root in sorted(nodes):
        if root in index:
            continue
        work = [(root, iter(adj[root]))]
        index[root] = low[root] = len(index)
        stack.append(root)
        onstack.add(root)
        while work:
            v, it = work[-1]
            moved = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = len(index)
                    stack.append(w)
                    onstack.add(w)
                    work.append((w, iter(adj[w])))
                    moved = True
                    break
                if w in onstack:
                    low[v] = min(low[v], index[w])
            if moved:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    onstack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                comps.append(comp)

    comp_of = {v: i for i, c in enumerate(comps) for v in c}
    dag, indeg = collections.defaultdict(set), collections.Counter()
    for a, b in data:
        u, v = comp_of[a], comp_of[b]
        if u != v and v not in dag[u]:
            dag[u].add(v)
            indeg[v] += 1
    lvl = [0] * len(comps)
    q = [i for i in range(len(comps)) if indeg[i] == 0]
    while q:
        u = q.pop(0)
        for v in sorted(dag[u]):
            lvl[v] = max(lvl[v], lvl[u] + 1)
            indeg[v] -= 1
            if indeg[v] == 0:
                q.append(v)
    # 收紧列位置。最长路径只保证"不违反前后关系"，不保证"挨着放"：一个节点会被它某一条
    # 最长的链推到很远的列上，于是 S31 落在最右列、离它的调用者 S30 隔了半个图，
    # 图上就出现"这两个东西为什么离这么远"。这里在每个节点的可行区间内把它拉到邻居中间。
    preds = collections.defaultdict(set)
    for u, vs in dag.items():
        for v in vs:
            preds[v].add(u)
    top = max(lvl) if lvl else 0
    for _ in range(int(sweeps)):
        moved = False
        for c in sorted(range(len(comps)), key=lambda c: (lvl[c], c)):
            lo = max([lvl[p] + 1 for p in preds[c]], default=0)
            hi = min([lvl[s] - 1 for s in dag[c]], default=top)
            if lo > hi or not (preds[c] or dag[c]):
                continue
            neighbours = [lvl[p] for p in preds[c]] + [lvl[x] for x in dag[c]]
            neighbours.sort()
            want = neighbours[len(neighbours) // 2]
            target = min(max(lo, want), hi)
            if target != lvl[c]:
                lvl[c] = target
                moved = True
        if not moved:
            break
    # 拉拽可能让某条边指回左列；修复到可行分层为止，宁可少收紧也不能画出反向边
    for _ in range(len(comps) + 1):
        broken = False
        for u in dag:
            for v in dag[u]:
                if lvl[v] < lvl[u] + 1:
                    lvl[v] = max(lvl[v], lvl[u] + 1)
                    broken = True
        if not broken:
            break

    size = collections.Counter(comp_of.values())
    return ({v: lvl[comp_of[v]] for v in nodes},
            {v for v, i in comp_of.items() if size[i] > 1},
            {v: comp_of[v] for v in nodes if size[comp_of[v]] > 1})


# --------------------------------------------------------------------------- #
# layering with dummy waypoints, then median + transposition ordering
# --------------------------------------------------------------------------- #
def scc_ids(edges):
    """Directed SCC over every edge: the front end needs it to tell a feedback
    edge from a genuine downstream branch."""
    adj = collections.defaultdict(list)
    nodes = set()
    for e in edges:
        adj[e["src"]].append(e["dst"])
        nodes.add(e["src"])
        nodes.add(e["dst"])
    index, low, stack, onstack, out = {}, {}, [], set(), {}
    for root in sorted(nodes):
        if root in index:
            continue
        work = [(root, iter(adj[root]))]
        index[root] = low[root] = len(index)
        stack.append(root)
        onstack.add(root)
        while work:
            v, it = work[-1]
            moved = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = len(index)
                    stack.append(w)
                    onstack.add(w)
                    work.append((w, iter(adj[w])))
                    moved = True
                    break
                if w in onstack:
                    low[v] = min(low[v], index[w])
            if moved:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == index[v]:
                cid = len(out)
                while True:
                    w = stack.pop()
                    onstack.discard(w)
                    out[w] = cid
                    if w == v:
                        break
    return out


def build_chains(edges, level_of, layers):
    """Split every forward edge into per-column segments (dummy nodes)."""
    chains, dummies = {}, []
    for idx, e in enumerate(edges):
        a, b = e["src"], e["dst"]
        la, lb = level_of.get(a, 0), level_of.get(b, 0)
        if la >= lb:
            continue                                    # backward edge: routed separately
        path = [("n", a)] + [("d", (idx, l)) for l in range(la + 1, lb)] + [("n", b)]
        chains[idx] = path
        for l in range(la + 1, lb):
            dummies.append(((idx, l), l))
    for key, l in dummies:
        layers[l].append(("d", key))
    return chains


def count_crossings(layers, pos, chains):
    """Classic layered crossing count over unit-length chain segments."""
    by_gap = collections.defaultdict(list)
    for path in chains.values():
        for (a, b) in zip(path, path[1:]):
            by_gap[pos[a][0]].append((pos[a][1], pos[b][1]))
    total = 0
    for pairs in by_gap.values():
        for (a1, b1), (a2, b2) in itertools.combinations(pairs, 2):
            if (a1 - a2) * (b1 - b2) < 0:
                total += 1
    return total


def order_layers(layers, chains, sweeps):
    """Median sweeps + adjacent transposition over real nodes and dummies."""
    order = sorted(layers)
    pos = {item: (l, i) for l in order for i, item in enumerate(layers[l])}
    left, right = collections.defaultdict(list), collections.defaultdict(list)
    for path in chains.values():
        for a, b in zip(path, path[1:]):
            right[a].append(b)
            left[b].append(a)

    def median_key(item, neighbours):
        refs = sorted(pos[n][1] for n in neighbours[item] if n in pos)
        if not refs:
            return (pos[item][1], str(item))
        mid = refs[len(refs) // 2] if len(refs) % 2 else (refs[len(refs) // 2 - 1] + refs[len(refs) // 2]) / 2
        return (mid, str(item))

    for _ in range(max(1, int(sweeps))):
        for l in order[1:]:
            layers[l].sort(key=lambda it: median_key(it, left))
            for i, it in enumerate(layers[l]):
                pos[it] = (l, i)
        for l in list(reversed(order))[:-1]:
            layers[l].sort(key=lambda it: median_key(it, right))
            for i, it in enumerate(layers[l]):
                pos[it] = (l, i)

    best = count_crossings(layers, pos, chains)
    for _ in range(10):
        improved = False
        for l in order:
            row = layers[l]
            for i in range(len(row) - 1):
                x, y = row[i], row[i + 1]
                row[i], row[i + 1] = y, x
                pos[x], pos[y] = (l, i + 1), (l, i)
                c = count_crossings(layers, pos, chains)
                if c < best:
                    best, improved = c, True
                else:
                    row[i], row[i + 1] = x, y
                    pos[x], pos[y] = (l, i), (l, i + 1)
        if not improved:
            break
    order_layers.crossings = best
    return pos


def orthogonalize(pts):
    """Turn any polyline into horizontal/vertical segments only.

    Routing produces a few diagonal shortcuts (mostly two-node and back edges). Drawing
    those as curves was the visible '乱七八糟': a diagonal S-curve weaving through a grid
    of orthogonal lines reads as chaos, and the test below now makes that impossible to
    reintroduce silently.
    """
    out = [tuple(pts[0])]
    for a, b in zip(pts, pts[1:]):
        a, b = tuple(a), tuple(b)
        dx, dy = abs(b[0] - a[0]), abs(b[1] - a[1])
        if dx < 0.5 or dy < 0.5:
            out.append(b)
            continue
        mid_x = (a[0] + b[0]) / 2          # LR flow: step across in the middle
        out.append((mid_x, a[1]))
        out.append((mid_x, b[1]))
        out.append(b)
    dedup = [out[0]]
    for p in out[1:]:
        if abs(p[0] - dedup[-1][0]) > 0.01 or abs(p[1] - dedup[-1][1]) > 0.01:
            dedup.append(p)
    return dedup


def _hits_rect(pts, rect, pad):
    """折线是否穿过矩形（含 pad 安全边距）。段都是轴对齐的，判据就是区间相交。"""
    rx1, ry1, rx2, ry2 = rect
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        if (min(ax, bx) < rx2 - pad and max(ax, bx) > rx1 + pad
                and min(ay, by) < ry2 - pad and max(ay, by) > ry1 + pad):
            return True
    return False


def detour_route(edges, geo, nodes_rect, edges_at, gap=16.0, max_step=90.0):
    """声明式绕行：把一条边压在某个框上的横段，改到从该框下方绕过。

    为什么是声明式而不是自动避障：通用避障等于重排整列，代价是把别的边全推歪；而
    "这条线不许穿那个框"本来就是人的判断。键是边（"S10->S15"），值 {"below": ["S11"]}。
    判据沿用同列边的老规则：压住了才绕，没压住不绕。

    只改一处几何：把压在框上的那段横线 y 下移到框下沿 + gap，两端各补一个拐点接回
    原来的进出线 —— 首尾端点不动，所以"端点必须贴框"的约束不会被破坏。超过 max_step
    就告警保持原样：宁可留一条穿框线，也不要静默产出一张把别的边全推歪的图。
    """
    gap = float(edges_at.get("gap", gap))
    max_step = float(edges_at.get("max_step", max_step))
    for key, spec in edges_at.items():
        if "->" not in key or not isinstance(spec, dict):
            continue
        idx = next((i for i, e in enumerate(edges)
                    if f"{e['src']}->{e['dst']}" == key), None)
        if idx is None or idx not in geo:
            print(f"  警告：route_avoid 的 {key} 没匹配到边，检查拼写")
            continue
        pts = [tuple(q) for q in geo[idx]]
        for nid in spec.get("below") or []:
            if nid not in nodes_rect or nid in (edges[idx]["src"], edges[idx]["dst"]):
                print(f"  警告：{key} 要绕的 {nid} 不是节点，或它就是这条边的端点")
                continue
            rect = nodes_rect[nid]
            segs = [(k, a, b) for k, (a, b) in enumerate(zip(pts, pts[1:]))
                    if _hits_rect([a, b], rect, 0.5)]
            if not segs:
                continue                                 # 没压住，不绕
            k, (ax, ay), (bx, _by) = segs[0]
            y_to = rect[3] + gap
            if y_to - ay > max_step:
                print(f"  警告：{key} 绕 {nid} 要把横线从 {ay:.0f} 下移到 {y_to:.0f}，"
                      f"超过 route_avoid.max_step={max_step:.0f}，保持原样")
                continue
            # ax->bx 压在框上：bx 是它离开框右沿的位置，也是重新抬高的位置
            pts = simplify(list(pts[:k + 1]) + [(ax, y_to), (bx, y_to), (bx, ay)]
                           + list(pts[k + 2:]))
        geo[idx] = pts


def lane_route(edges, level_of, x_of, y_of, col_w, w_of, out_y, in_y, nx=None):
    """Route forward edges through per-gap lanes.

    Without lanes every long edge crosses a column gap on the same vertical, so
    six of them stack into one bundle and their labels sit on top of the lines.
    Each gap is divided into as many lanes as there are crossings, ordered by
    height, which spreads the bundle and frees space for the labels.
    """
    # 每条通道在自己的列间隙里排开：列宽不等时，统一 gap 会把车道推到框上去
    gap_at = {g: max(36.0, x_of[g + 1] - x_of[g] - max(col_w.get(g, 0), col_w.get(g + 1, 0)))
              for g in range(min(level_of.values(), default=0), max(level_of.values(), default=0))}
    crossings = collections.defaultdict(list)
    for idx, e in enumerate(edges):
        la, lb = level_of.get(e["src"], 0), level_of.get(e["dst"], 0)
        if la >= lb:
            continue
        for g in range(la, lb):
            y = in_y[idx] if g == lb - 1 else (y_of[("d", (idx, g + 1))]
                                               if (idx, g + 1) in y_of else out_y[idx])
            crossings[g].append((y, idx))
    lane_x = {}
    for g, rows in crossings.items():
        rows.sort()
        n = len(rows)
        for k, (_y, idx) in enumerate(rows):
            lane_x[(g, idx)] = x_of[g] + col_w.get(g, 0) +                 gap_at.get(g, 60.0) * (k + 1) / (n + 1)

    geo = {}
    for idx, e in enumerate(edges):
        la, lb = level_of.get(e["src"], 0), level_of.get(e["dst"], 0)
        if la < lb:
            src_x = (nx[e["src"]] if nx else x_of[la]) + w_of.get(e["src"], col_w.get(la, 0))
            # 高度只在最后一跳改变。逐间隙跟虚拟节点的高度走，一条边会上下折好几次：
            # 实测最绕的那条 20 个折点、绕行比 4.07。平穿 + 末尾下降后折点降到 3 个，
            # 长度正好等于曼哈顿距离。
            y_run = out_y[idx]
            pts = [(src_x, y_run)]
            for g in range(la, lb):
                pts.append((lane_x[(g, idx)], y_run))
            if abs(in_y[idx] - y_run) > 0.5:
                pts.append((lane_x[(lb - 1, idx)], in_y[idx]))
            pts.append(((nx[e["dst"]] if nx else x_of[lb]), in_y[idx]))
            geo[idx] = pts
    return geo


def segments_of(polys):
    segs = []
    for pts in polys.values():
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            segs.append((x1, y1, x2, y2))
    return segs


def _seg(a, b):
    return (a[0], a[1], b[0], b[1])


def _boxed(seg):
    """Append the segment bounding box so overlap tests can reject cheaply."""
    x1, y1, x2, y2 = seg
    return seg + (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))


def _box_covers(x, y, hw, hh, seg, pad=0.0):
    """Does the polyline segment pass through the label box?

    seg may carry a cached bounding box as its last four entries, which is what
    keeps label placement out of quadratic time.
    """
    if len(seg) == 8:
        bx1, by1, bx2, by2 = seg[4:]
        if bx2 < x - hw - pad or bx1 > x + hw + pad or by2 < y - hh - pad or by1 > y + hh + pad:
            return False
    x1, y1, x2, y2 = seg[:4]
    steps = max(2, int((abs(x2 - x1) + abs(y2 - y1)) / 4) + 1)
    for i in range(steps + 1):
        t = i / steps
        if abs(x1 + (x2 - x1) * t - x) <= hw + pad and abs(y1 + (y2 - y1) * t - y) <= hh + pad:
            return True
    return False


def _poly_at(pts, t):
    total = 0.0
    lens = []
    for a, b in zip(pts, pts[1:]):
        length = abs(b[0] - a[0]) + abs(b[1] - a[1])
        lens.append(length)
        total += length
    if total == 0:
        return pts[0]
    want, acc = t * total, 0.0
    for (a, b), length in zip(zip(pts, pts[1:]), lens):
        if acc + length >= want:
            k = (want - acc) / length if length else 0
            return (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k)
        acc += length
    return pts[-1]


def place_labels_on_own_edge(labels, segs, rects):
    """每个标签只许压在自己那条边上，并且不得碰到别的边。

    segs 是 (owner, segment)。代价：压到别人的线 = 重罚；没压到自己的线 = 次重罚；
    压住节点或与别的标签重叠 = 禁止；离自己的边中点越远越差。
    """
    hh = LABEL_H / 2
    placed = []

    def slots(lab):
        """Candidate boxes, centre-out along the edge. Wider than it looks necessary:
        with 69 labels the middle of a long edge is usually already taken."""
        out = []
        for t in (0.5, 0.45, 0.55, 0.4, 0.6, 0.35, 0.65, 0.3, 0.7, 0.25, 0.75, 0.2, 0.8):
            x, y = _poly_at(lab["pts"], t)
            for dx in (0, 16, -16, 32, -32, 48, -48, 64, -64, 80, -80):
                for dy in (0, -7, 7, -14, 14, -22, 22, -30, 30):
                    out.append((x + dx, y + dy, t))
        return out

    def free_slots(lab):
        """How many candidates miss every other edge and every node - the label's
        degree of freedom. Placement runs tightest-first: greedy in declaration order
        let early labels take the only clean slots in a dense region."""
        hw, n = lab["w"] / 2, 0
        for cx, cy, _t in slots(lab):
            if any(_box_covers(cx, cy, hw, hh, seg, pad=1.0) for owner, seg in segs if owner != lab["idx"]):
                continue
            if any(abs(cx - rx) < hw + rw / 2 and abs(cy - ry) < hh + rh / 2 for rx, ry, rw, rh in rects):
                continue
            n += 1
        return n

    for lab in sorted(labels, key=lambda l: (free_slots(l), l["idx"])):
        own = lab["pts"]
        cands = slots(lab)
        scored = []
        for cx, cy, t in cands:
            if scored and scored[0][0] <= abs(t - 0.5) * 6:
                break          # 已经找到按序第一个零冲突位置，后面只会更差
            hw = lab["w"] / 2
            on_own = any(_box_covers(cx, cy, hw, hh, _seg(a, b))
                         for a, b in zip(own, own[1:]))
            cost = 0
            if not on_own:
                cost += 400                      # 必须压住自己的边
            hits_other = 0
            for owner, seg in segs:
                if owner == lab["idx"]:
                    continue
                if _box_covers(cx, cy, hw, hh, seg, pad=1.0):
                    hits_other += 1
                    cost += 1000
                    break                        # 绝不允许压到别人的边
            for rx, ry, rw, rh in rects:
                if abs(cx - rx) < hw + rw / 2 and abs(cy - ry) < hh + rh / 2:
                    cost += 5000
            for q in placed:
                if abs(cx - q["lx"]) < hw + q["w"] / 2 + 4 and abs(cy - q["ly"]) < LABEL_H:
                    cost += 5000
            cost += abs(t - 0.5) * 6
            scored.append((cost, cx, cy, hits_other, on_own))
        scored.sort(key=lambda r: (r[0], r[1], r[2]))
        cost, cx, cy, hits_other, on_own = scored[0]
        lab["lx"], lab["ly"] = cx, cy
        lab["on_own"] = bool(on_own)
        lab["cross_others"] = hits_other
        placed.append(lab)
    return labels


def label_geometry(labels):
    """Push labels apart so no two overlap. Deterministic, and unit-testable."""
    placed = []
    for lab in sorted(labels, key=lambda l: (round(l["lx"] / 40), l["ly"])):
        y = lab["ly"]
        for _ in range(200):
            hit = next((p for p in placed
                        if abs(p["lx"] - lab["lx"]) < (p["w"] + lab["w"]) / 2 + 6
                        and abs(y - p["ly"]) < LABEL_H), None)
            if hit is None:
                break
            y = hit["ly"] + LABEL_H
        lab["ly"] = y
        placed.append(lab)
    return labels


def overlaps(labels, gap=2.0):
    bad = []
    for a, b in itertools.combinations(labels, 2):
        if (abs(a["lx"] - b["lx"]) < (a["w"] + b["w"]) / 2 - gap
                and abs(a["ly"] - b["ly"]) < LABEL_H - gap):
            bad.append((a.get("for"), b.get("for")))
    return bad


# --------------------------------------------------------------------------- #
# node metadata: looked up by table header names, never by id pattern
# --------------------------------------------------------------------------- #
def node_info(md_path, spec):
    if not spec:
        return {}
    path = Path(spec["md"]) if Path(spec["md"]).is_absolute() else Path(md_path) / spec["md"]
    if not path.exists():
        return {}
    info, header, cols = {}, None, {}
    for ln in path.read_text(encoding="utf-8").splitlines():
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if header is None:
            if spec["key_column"] in cells:
                header = cells
                cols = {i: target for name, target in spec["columns"].items()
                        if name in cells for i, c in enumerate(cells) if c == name}
            continue
        if not any(cells) or all(set(c) <= set("-: ") for c in cells):
            continue
        if len(cells) < len(header):
            header = None
            continue
        key = cells[header.index(spec["key_column"])]
        if key:
            info[key] = {target: cells[i] for i, target in cols.items()}
    return info


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #
def build(config_path):
    cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
    base = Path(config_path).parent
    rules = load_rules((base / cfg["rules"]).resolve())
    mmd = (base / cfg["mmd"]).resolve()
    if not mmd.exists():
        raise SystemExit(f"找不到 {mmd}")

    doc = mermaid_doc.parse(mmd.read_text(encoding="utf-8"))
    if doc.problems:
        raise SystemExit("这些行看起来是边但解析失败，改成标准 Mermaid 写法：\n"
                         + "\n".join(f"  line {n}: {t}" for n, t in doc.problems))

    edges = classify(doc, rules)
    layout = dict(rules.get("layout", {}))
    h_gap = layout.get("level_gap", 54)
    sy = layout.get("row_spacing", 66)
    h = layout.get("node_height", 42)

    scc = scc_ids(edges)
    # Layering is a drawing concern: it uses every relation, SCC-condensed. It used
    # to reuse the data-flow class, which silently coupled layout to semantics - and
    # collapsed the whole picture into one column once data flow stopped being the
    # majority relation.
    ordering = set(rules.get("layering", {}).get("classes") or
                   [p["class"] for p in rules["palette"] if p.get("ordering")])
    skip = doc.no_layout_ids()
    level_of, loop, _members = levels(edges, ordering, skip, layout.get("compact_sweeps", 6))

    ids = sorted({e["src"] for e in edges} | {e["dst"] for e in edges})
    layers = collections.defaultdict(list)
    for n in ids:
        layers[level_of.get(n, 0)].append(("n", n))
    chains = build_chains(edges, level_of, layers)
    for l in layers:
        layers[l].sort(key=lambda it: (it[0] == "d", str(it)))
    pos = order_layers(layers, chains, layout.get("sweeps", 4))

    # 框宽按各自标签算，不再全图统一。统一宽度等于按最长的那个标签给 31 个框留白：
    # 中位标签 8 个字，原来 152 的宽度里约一半是空的，整张图因此横向拉宽。
    pad, min_w, max_w = layout.get("node_padding", 9), layout.get("node_min_width", 56), layout.get("node_max_width", 200)

    # 框宽要按“真正画得下的那两行”算，而不是按标签总长算：
    # 节点是 id 一行、名称一行，取两行的较宽者才是需要的宽度。
    spec = rules.get("node_info") or {}
    info = node_info(base, spec)
    name_of, lines_of = {}, {}
    for n in ids:
        label = doc.nodes[n].label if n in doc.nodes else n
        head, _, rest = label.partition(" ")
        name_of[n] = (info.get(n, {}).get("name") or rest or "").strip()
        lines_of[n] = [ln for ln in [head, name_of[n]] if ln]
    w_of = {n: box_width(lines_of[n], pad, min_w, max_w) for n in ids}

    # 高度按端口数算：出入线全部贴在同一侧的框边上，框高不够就是几个端口挤在
    # 21px 里——间距 3.6px，线和标签必然糊成一束。
    deg_in = collections.Counter(e["dst"] for e in edges)
    deg_out = collections.Counter(e["src"] for e in edges)
    port_pitch = layout.get("port_pitch", 13)
    h_of = {n: max(h, 30 if len(lines_of[n]) > 1 else h,
                   max(deg_in.get(n, 0), deg_out.get(n, 0)) * port_pitch + 10)
            for n in ids}
    h = max(h_of.values())
    w = max(w_of.values())      # 绕行通道仍按列内最宽算，保证列间留白一致

    # y coordinate: slot index, centred per column
    height = max(len(v) for v in layers.values())
    y_of = {}
    for l, row in layers.items():
        offset = (height - len(row)) / 2.0
        for i, it in enumerate(row):
            y_of[it] = (offset + i) * sy + sy / 2
    def refine_y(sweeps):
        """把每个节点拉向它邻居的高度，再按最小间隔重排本列。

        每列各自居中，等于假设"同一列的东西在垂直上无偏好"。事实不是：邻居在上方，
        这个节点留在中间就会拖出一条长斜线，并在它原来的高度留下空白。列内顺序按邻居
        中位数重排、再按最小间隔压紧，空白和斜线一起少掉。
        """
        neighbours = collections.defaultdict(list)
        for e in edges:
            neighbours[("n", e["src"])].append(("n", e["dst"]))
            neighbours[("n", e["dst"])].append(("n", e["src"]))
        for _ in range(int(sweeps)):
            moved = False
            for l in sorted(layers):
                row = layers[l]
                want = {}
                for it in row:
                    near = [y_of[n] for n in neighbours.get(it, []) if n in y_of]
                    near.sort()
                    want[it] = near[len(near) // 2] if near else y_of[it]
                order = sorted(row, key=lambda it: (want[it], str(it)))
                if order != row:
                    layers[l] = order
                    moved = True
                # 压紧：保持顺序，逐个推到最小间隔，再整体平移对齐期望中心
                # 压紧：保持顺序，逐个推到最小间隔，再整体平移对齐期望中心。
                # 最小间隔按相邻两个框的实际高度算：统一行距是为了框高一致时省事，
                # 现在框高已经随端口数变化，再拿常数当间隔就会压住。
                gap_v = layout.get("row_gap", 22)
                def _hh(it):
                    return h_of[it[1]] if it[0] == "n" else 8
                for i, it in enumerate(order):
                    floor = (y_of[order[i - 1]] + _hh(order[i - 1]) / 2 + _hh(it) / 2 + gap_v
                             if i else want[it])
                    y_of[it] = max(want[it], floor)
                shift = (sum(want[it] for it in order) / len(order)
                         - sum(y_of[it] for it in order) / len(order))
                for it in order:
                    y_of[it] += shift
            if not moved:
                break

    refine_y(layout.get("row_sweeps", 6))

    # 列位置按"前一列最宽的框 + 固定空隙"推出来。统一列间距是框还宽的时候定的，框缩到
    # 80 上下之后，窄框所在的列之间会空出一整列的宽度 —— 图上那些"距离过长"就是它
    col_w = {l: max([w_of[it[1]] for it in row if it[0] == "n"], default=min_w)
             for l, row in layers.items()}

    # 缝宽按需求分配：这条缝要过几条边，就给几条通道的宽度。
    # 常数缝宽是框还窄的时候定的；框变宽后缝里装不下这些边，它们只能压框或挤成一束。
    lane_pitch = layout.get("lane_pitch", 16)
    demand = collections.Counter()
    for e in edges:
        la, lb = level_of.get(e["src"], 0), level_of.get(e["dst"], 0)
        for g in range(min(la, lb), max(la, lb)):
            demand[g] += 1
    x_of, cursor = {}, 0.0
    for l in sorted(layers):
        x_of[l] = cursor
        cursor += col_w[l] + max(h_gap, demand[l] * lane_pitch)

    # 层框偏移：挪一层 = 挪它的全部节点（边按节点位置连，所以边自动跟着走）。
    # 这是给"把这一层挪到那儿"一个正当出口：Mermaid 里没有这个接口
    boxes_cfg = layout.get("layer_boxes", {})

    def layer_off(nid):
        cfg = boxes_cfg.get(doc.nodes[nid].subgraph if nid in doc.nodes else "", {})
        return float(cfg.get("dx", 0) or 0), float(cfg.get("dy", 0) or 0)

    nx = {n: x_of[level_of.get(n, 0)] + layer_off(n)[0] for n in ids}
    ny = {n: y_of[("n", n)] + layer_off(n)[1] for n in ids}

    # 偏移是给人自由度的，这条是它的边界：框不许互相压住。
    # 越界不报错而是进统计并由测试拦下——布局工具里"生成成功但图不可读"是最坏的失败
    clash = [f"{a}×{b}" for i, a in enumerate(ids) for b in ids[i + 1:]
             if nx[a] < nx[b] + w_of[b] and nx[b] < nx[a] + w_of[a]
             and ny[a] - h_of[a] / 2 < ny[b] + h_of[b] / 2 and ny[b] - h_of[b] / 2 < ny[a] + h_of[a] / 2]
    if clash:
        print(f"  警告：{len(clash)} 对框重叠（检查 layer_boxes 的 dx/dy）：" + ", ".join(clash[:6]))

    # ports: spread edge attach points along the node's left/right edge
    out_slots, in_slots = collections.defaultdict(list), collections.defaultdict(list)
    for idx, e in enumerate(edges):
        out_slots[e["src"]].append(idx)
        in_slots[e["dst"]].append(idx)

    port_order = layout.get("port_order", {})

    def edge_name(i):
        return f"{edges[i]['src']}->{edges[i]['dst']}"

    def slot_y(node_id, idx, slots, back):
        # 默认按"对端 y"排。人工覆盖是声明式的：port_order.<node> = ["S10->S11", ...]，
        # 从上到下的先后由人写，算法不猜 —— 同侧两口的上下关系有时与线长、交叉都无关，
        # 只和读图习惯有关（"进 S11 的那根应该走下面"）。没列出的接在后面按对端 y。
        want = port_order.get(node_id) or []
        if want:
            known = [i for i in slots if edge_name(i) in want]
            rest = sorted((i for i in slots if i not in known),
                          key=lambda i: ny[edges[i]["src" if back else "dst"]])
            order = sorted(known, key=lambda i: want.index(edge_name(i))) + rest
        else:
            order = sorted(slots, key=lambda i: ny[edges[i]["src" if back else "dst"]])
        k = order.index(idx)
        # 端口扇开须跟着端口数走，但不得超过本框高度：超出就会贴在框外，
        # 边看起来像没接上。高度已由 deg 撑开，所以这里两者能同时满足。
        spread = min(h_of.get(node_id, h) - 10, len(order) * port_pitch)
        return ny[node_id] + (k + 0.5) / len(order) * spread - spread / 2

    # 单个框的微调：声明式写在规则里，而不是让算法自己找位置。
    # S02->S09 这类边两框纵向根本不重叠，接点对齐无解，只能把框抬高一点；
    # 不用自动对齐算法是因为它会改变 slot_y 的排序、进而改变接点，形成反馈。
    for nid, dny in layout.get("node_nudge", {}).items():
        if nid in ny:
            ny[nid] += float(dny)

    out_y = {idx: slot_y(e["src"], idx, out_slots[e["src"]], False) for idx, e in enumerate(edges)}
    in_y = {idx: slot_y(e["dst"], idx, in_slots[e["dst"]], True) for idx, e in enumerate(edges)}

    # 圈层排序必须在端口 y 算完之后做。跳距小的圈要排在最内侧：
    # 按纵向中点排的话，短跳也可能拿到 k=15，48px 的相邻跳被甩到 150px 外再绕回来。
    def span(i):
        return abs(out_y[i] - in_y[i])

    same_lanes = {idx: k for k, idx in enumerate(sorted(
        (i for i, e in enumerate(edges) if level_of.get(e["src"], 0) == level_of.get(e["dst"], 0)),
        key=lambda i: (level_of.get(edges[i]["src"], 0), span(i))))}
    back_lanes = {idx: k for k, idx in enumerate(sorted(
        (i for i, e in enumerate(edges) if level_of.get(e["src"], 0) > level_of.get(e["dst"], 0)),
        key=lambda i: (min(level_of.get(edges[i]["src"], 0), level_of.get(edges[i]["dst"], 0)),
                       span(i))))}
    out_y, in_y = align_ports(edges, ny, h_of, out_y, in_y,
                              layout.get("port_pitch", 13),
                              layout.get("align_max_step", 45),
                              layout.get("align_sweeps", 4))

    geo = lane_route(edges, level_of, x_of, y_of, col_w, w_of, out_y, in_y, nx)

    # 声明式绕行（S10->S15 不许平穿 S11）。放在后处理之前：straighten 只并小折弯，
    # 这里绕行的竖段远大于 max_kink，不会被抹掉。
    avoid = layout.get("route_avoid") or {}
    if avoid:
        detour_route(edges, geo,
                     {n: (nx[n], ny[n] - h_of[n] / 2, nx[n] + w_of[n], ny[n] + h_of[n] / 2)
                      for n in ids},
                     avoid)

    # 反向边与同列边：端点必须落在节点框边上，不能悬在顶边外面
    for idx, e in enumerate(edges):
        if idx in geo:
            continue
        la, lb = level_of.get(e["src"], 0), level_of.get(e["dst"], 0)
        ya, yb = out_y[idx], in_y[idx]
        wa, wb = w_of.get(e["src"], w), w_of.get(e["dst"], w)
        # 折点直接给成正交的 4 点折线，不再让 orthogonalize 从斜线里猜折点：
        # 猜出来的折点落在线段中点，一条边白白多出两个转角。
        if la == lb:                       # 同列：能直连就直连，上下相邻的框不该绕到侧面
            cy_a, cy_b = ny[e["src"]], ny[e["dst"]]
            ha, hb = h_of[e["src"]], h_of[e["dst"]]
            gap = (max(cy_a, cy_b) - max(ha, hb) / 2) - (min(cy_a, cy_b) + min(ha, hb) / 2)
            if gap <= 26:                  # 上下相邻：底边→顶边，一条竖线，零折角
                cx = min(nx[e["src"]] + w_of[e["src"]] / 2, nx[e["dst"]] + w_of[e["dst"]] / 2)
                cx += (same_lanes.get(idx, 0) % 5 - 2) * 6
                geo[idx] = [(cx, cy_a + ha / 2 if cy_b > cy_a else cy_a - ha / 2),
                            (cx, cy_b - hb / 2 if cy_b > cy_a else cy_b + hb / 2)]
            else:                          # 不相邻：贴本列右侧走最小圈
                x = nx[e["src"]] + max(wa, wb) + 10 + same_lanes.get(idx, 0) * 7
                geo[idx] = [(nx[e["src"]] + wa, ya), (x, ya), (x, yb), (nx[e["dst"]] + wb, yb)]
        else:                              # 真反向：源左出、目标右入，竖段落在列间空档
            n = max(1, len(back_lanes))
            lo, hi = x_of[lb] + wb, x_of[la]
            x = lo + (hi - lo) * (back_lanes.get(idx, 0) + 1) / (n + 1)
            geo[idx] = [(nx[e["src"]], ya), (x, ya), (x, yb), (nx[e["dst"]] + wb, yb)]

    segs = [(owner, _boxed(_seg(a, b))) for owner, pts in geo.items()
            for a, b in zip(pts, pts[1:])]
    rects = [(nx[n] + w_of[n] / 2, ny[n] - h_of[n] / 2, w_of[n], h_of[n]) for n in ids]

    # 分组框：成员按各自的列散布，框就按成员实际位置包一圈。以前交互图不画分组，
    # 于是它比 Mermaid 版难读，谁都不看它 —— 布局做得再好也没人看得见
    pad_g = layout.get("group_padding", 22)
    boxes = {}
    for n in ids:
        sub = doc.nodes.get(n).subgraph if n in doc.nodes else ""
        if not sub or sub in doc.legend_ids():
            continue
        left, top = nx[n], ny[n] - h_of[n] / 2
        box = boxes.setdefault(sub, [left, top, left + w_of[n], top + h, []])
        box[0], box[1] = min(box[0], left), min(box[1], top)
        box[2], box[3] = max(box[2], left + w_of[n]), max(box[3], top + h_of[n])
        box[4].append(n)
    groups = []
    for k, b in sorted(boxes.items()):
        bcfg = boxes_cfg.get(k, {})        # 别叫 cfg：会遮蔽 build() 自己的配置并返回错的东西
        gw = max(b[2] - b[0] + pad_g * 2, float(bcfg.get("w") or 0))
        gh = max(b[3] - b[1] + pad_g * 2 + 14, float(bcfg.get("h") or 0))
        groups.append({"id": k, "title": doc.subgraphs.get(k, k),
                       "x": round(b[0] - pad_g, 1), "y": round(b[1] - pad_g - 14, 1),
                       "w": round(gw, 1), "h": round(gh, 1), "members": sorted(b[4])})
    # 三步必须按这个顺序：先保证只有横平竖直（正交化的测试在断言它），再合共线点，
    # 最后抹小折弯——顺序反了会把斜线当成横线合并。
    geo = {idx: straighten(simplify(orthogonalize(p)), layout.get("max_kink", 20),
                           (ny[edges[idx]["dst"]] - h_of[edges[idx]["dst"]] / 2,
                            ny[edges[idx]["dst"]] + h_of[edges[idx]["dst"]] / 2))
           for idx, p in geo.items()}
    segs = [(idx, _seg(a, b)) for idx, p in geo.items() for a, b in zip(p, p[1:])]

    labels = []
    for idx, e in enumerate(edges):
        labels.append({"for": f"{e['src']}->{e['dst']}", "idx": idx, "pts": geo[idx],
                       "w": max(24.0, len(e["label"]) * CHAR_W),
                       "ax": _poly_at(geo[idx], 0.5)[0], "ay": _poly_at(geo[idx], 0.5)[1],
                       "lx": 0.0, "ly": 0.0})
    labels = place_labels_on_own_edge(labels, segs, rects)
    label_of = {lab["for"]: lab for lab in labels}

    spec = rules.get("node_info") or {}
    desc_col = spec.get("description_column", "output")
    panel_labels = spec.get("panel_labels", {})
    nodes = []
    for n in ids:
        meta = dict(info.get(n, {}))
        desc = meta.pop(desc_col, "")
        nodes.append({"id": n, "x": nx[n], "y": ny[n] - h_of[n] / 2, "pad": pad,
                      "level": level_of.get(n, 0), "w": w_of[n], "h": h_of[n],
                      "label": doc.nodes[n].label if n in doc.nodes else n,
                      "lines": lines_of[n],
                      "name": meta.pop("name", "") or (doc.nodes[n].label if n in doc.nodes else ""),
                      "desc": desc,
                      "extra": [[panel_labels.get(k, k), v] for k, v in meta.items() if v],
                      "loop": n in loop, "scc": scc.get(n, -1)})

    out_edges = []
    for idx, e in enumerate(edges):
        lab = label_of[f"{e['src']}->{e['dst']}"]
        out_edges.append({"s": e["src"], "t": e["dst"], "label": e["label"], "kind": e["kind"],
                          "pts": [[round(x, 1), round(y, 1)] for x, y in geo[idx]],
                          "lx": round(lab["lx"], 1), "ly": round(lab["ly"], 1),
                          "back": level_of.get(e["src"], 0) >= level_of.get(e["dst"], 0)})

    present = [{"kind": p["class"], "title": p["title"], "desc": p["desc"],
                "stroke": p["stroke"], "dash": bool(p["dash"])}
               for p in rules["palette"] if any(e["kind"] == p["class"] for e in edges)]

    return cfg, rules, {
        "title": cfg.get("title", mmd.stem),
        "nodes": nodes,
        "edges": out_edges,
        "legend": present,
        # Focus walks the semantic primary relation (data flow), not the layering set:
        # "what flows through this node" is a question about content, and lighting up
        # every control edge too would make focus the same picture as no focus.
        "primary": sorted(p["class"] for p in rules["palette"] if p.get("ordering")),
        "colours": {p["class"]: p["stroke"] for p in rules["palette"]},
        "dashed": {p["class"]: bool(p["dash"]) for p in rules["palette"]},
        "box": {"w": w, "h": h},
        "level_x": {str(l): round(x, 1) for l, x in x_of.items()},
        "groups": groups,
        "canvas": {"w": (x_of[max(x_of, default=0)] + col_w.get(max(x_of, default=0), 0) + 120),
                   "h": (height + 1) * sy + 160},
        "labels": [{"for": l["for"], "idx": l["idx"], "lx": round(l["lx"], 1),
                    "ly": round(l["ly"], 1), "w": round(l["w"], 1),
                    "on_own": l["on_own"], "cross_others": l["cross_others"]} for l in labels],
        "stats": {"crossings": getattr(order_layers, "crossings", -1),
                  "labels": len(labels),
                  "label_overlaps": len(overlaps(labels)),
                  "labels_off_own_edge": sum(1 for l in labels if not l["on_own"]),
                  "labels_crossing_others": sum(1 for l in labels if l["cross_others"]),
                  # 调紧凑度要有数可看，不然只能凭眼睛判断"这次是不是变小了"
                  "avg_box_w": round(sum(w_of.values()) / len(w_of), 1) if w_of else 0,
                  "box_overlaps": len(clash)},
    }


# --------------------------------------------------------------------------- #
# render
# --------------------------------------------------------------------------- #
TEMPLATE = HERE / "graph_template.html"


def render(config_path):
    """Returns (html, data). Handing data back avoids re-parsing the page."""
    cfg, _rules, data = build(config_path)
    page = Path(TEMPLATE).read_text(encoding="utf-8")
    src_text = (Path(config_path).parent / cfg["mmd"]).read_text(encoding="utf-8")
    html = (page.replace("__DATA__", json.dumps(data, ensure_ascii=False))
                .replace("__TITLE__", data["title"])
                .replace("__SOURCE__", cfg["mmd"])
                .replace("__MMD_SOURCE__", src_text))
    return html, data


def outputs(configs):
    for c in configs:
        cfg = json.loads(Path(c).read_text(encoding="utf-8"))
        html, data = render(Path(c))
        yield Path(c).parent / cfg["out"], html, data


def main() -> int:
    ap = argparse.ArgumentParser(description="Mermaid -> 可交互 HTML 图")
    ap.add_argument("configs", nargs="*", help="*.graph.json，缺省则自动发现")
    ap.add_argument("--check", action="store_true", help="只检查产物是否过期，非 0 退出即过期")
    ap.add_argument("--open", dest="open_it", action="store_true", help="生成后用默认程序打开")
    args = ap.parse_args()

    configs = [Path(c) for c in args.configs] or sorted(HERE.parent.rglob("*.graph.json"))
    if not configs:
        print("没有找到 *.graph.json 配置")
        return 1

    stale = 0
    for cfg_path, html, data in outputs(configs):
        if args.check:
            ok = cfg_path.exists() and cfg_path.read_text(encoding="utf-8") == html
            print(("up to date   " if ok else "STALE  ") + cfg_path.name)
            stale |= 0 if ok else 1
            continue
        cfg_path.write_text(html, encoding="utf-8")
        print(f"{cfg_path.name}: {len(data['nodes'])} 节点 / {len(data['edges'])} 边 "
              f"交叉 {data['stats']['crossings']} / 标签 {data['stats']['labels']} / "
              f"画布 {data['canvas']['w']:.0f}x{data['canvas']['h']:.0f} "
              f"/ 平均框宽 {data['stats']['avg_box_w']}")
        if args.open_it:
            os.startfile(str(cfg_path)) if hasattr(os, "startfile") else os.system(f'xdg-open "{cfg_path}"')
    return stale


if __name__ == "__main__":
    sys.exit(main())

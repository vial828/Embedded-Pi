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
CHAR_W = 5.9          # rough glyph width for label collision maths
LABEL_H = 12.0


# --------------------------------------------------------------------------- #
# rules
# --------------------------------------------------------------------------- #
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
    return [e for e in out if e["src"] not in legend and e["dst"] not in legend]


# --------------------------------------------------------------------------- #
# levels: longest path over ordering edges, SCC condensed
# --------------------------------------------------------------------------- #
def levels(edges, ordering_classes, skip_nodes):
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


def lane_route(edges, level_of, x_of, y_of, w, sx, out_y, in_y):
    """Route forward edges through per-gap lanes.

    Without lanes every long edge crosses a column gap on the same vertical, so
    six of them stack into one bundle and their labels sit on top of the lines.
    Each gap is divided into as many lanes as there are crossings, ordered by
    height, which spreads the bundle and frees space for the labels.
    """
    gap_w = max(40.0, sx - w)
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
            lane_x[(g, idx)] = x_of[g] + w + gap_w * (k + 1) / (n + 1)

    geo = {}
    for idx, e in enumerate(edges):
        la, lb = level_of.get(e["src"], 0), level_of.get(e["dst"], 0)
        if la < lb:
            pts = [(x_of[la] + w, out_y[idx])]
            for g in range(la, lb):
                y = in_y[idx] if g == lb - 1 else y_of.get(("d", (idx, g + 1)), in_y[idx])
                pts.append((lane_x[(g, idx)], y))
            pts.append((x_of[lb], in_y[idx]))
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
    sx = layout.get("level_spacing", 250)
    sy = layout.get("row_spacing", 66)
    w = layout.get("node_width", 152)
    h = layout.get("node_height", 42)

    scc = scc_ids(edges)
    # Layering is a drawing concern: it uses every relation, SCC-condensed. It used
    # to reuse the data-flow class, which silently coupled layout to semantics - and
    # collapsed the whole picture into one column once data flow stopped being the
    # majority relation.
    ordering = set(rules.get("layering", {}).get("classes") or
                   [p["class"] for p in rules["palette"] if p.get("ordering")])
    skip = doc.no_layout_ids()
    level_of, loop, _members = levels(edges, ordering, skip)

    ids = sorted({e["src"] for e in edges} | {e["dst"] for e in edges})
    layers = collections.defaultdict(list)
    for n in ids:
        layers[level_of.get(n, 0)].append(("n", n))
    chains = build_chains(edges, level_of, layers)
    for l in layers:
        layers[l].sort(key=lambda it: (it[0] == "d", str(it)))
    pos = order_layers(layers, chains, layout.get("sweeps", 4))

    # y coordinate: slot index, centred per column
    height = max(len(v) for v in layers.values())
    y_of = {}
    for l, row in layers.items():
        offset = (height - len(row)) / 2.0
        for i, it in enumerate(row):
            y_of[it] = (offset + i) * sy + sy / 2
    x_of = {l: l * sx for l in layers}

    # ports: spread edge attach points along the node's left/right edge
    out_slots, in_slots = collections.defaultdict(list), collections.defaultdict(list)
    for idx, e in enumerate(edges):
        out_slots[e["src"]].append(idx)
        in_slots[e["dst"]].append(idx)

    def slot_y(node_id, idx, slots, back):
        order = sorted(slots, key=lambda i: y_of.get(("n", edges[i]["src" if back else "dst"]), 0))
        k = order.index(idx)
        spread = h * 0.72
        return y_of[("n", node_id)] + (k + 0.5) / len(order) * spread - spread / 2

    back_lanes = {}
    for idx, e in enumerate(edges):
        if level_of.get(e["src"], 0) >= level_of.get(e["dst"], 0):
            back_lanes[idx] = len(back_lanes)

    out_y = {idx: slot_y(e["src"], idx, out_slots[e["src"]], False) for idx, e in enumerate(edges)}
    in_y = {idx: slot_y(e["dst"], idx, in_slots[e["dst"]], True) for idx, e in enumerate(edges)}
    geo = lane_route(edges, level_of, x_of, y_of, w, sx, out_y, in_y)

    # 反向边与同列边：端点必须落在节点框边上，不能悬在顶边外面
    for idx, e in enumerate(edges):
        if idx in geo:
            continue
        la, lb = level_of.get(e["src"], 0), level_of.get(e["dst"], 0)
        ya, yb = out_y[idx], in_y[idx]
        lane = back_lanes[idx] % 6
        if la == lb:                       # 同列：从右侧绕出去再回来
            x = x_of[la] + w + 22 + lane * 11
            geo[idx] = [(x_of[la] + w, ya), (x, (ya + yb) / 2), (x_of[lb] + w, yb)]
        else:                              # 真反向：源左出、目标右入，走列间通道
            lo, hi = x_of[lb] + w, x_of[la]
            geo[idx] = [(x_of[la], ya),
                        (lo + (hi - lo) * (lane + 1) / 7.0, (ya + yb) / 2),
                        (x_of[lb] + w, yb)]

    segs = [(owner, _boxed(_seg(a, b))) for owner, pts in geo.items()
            for a, b in zip(pts, pts[1:])]
    rects = [(x_of[level_of.get(n, 0)] + w / 2, y_of[("n", n)] - h / 2, w, h) for n in ids]
    labels = []
    for idx, e in enumerate(edges):
        labels.append({"for": f"{e['src']}->{e['dst']}", "idx": idx, "pts": geo[idx],
                       "w": max(24.0, len(e["label"]) * CHAR_W),
                       "ax": _poly_at(geo[idx], 0.5)[0], "ay": _poly_at(geo[idx], 0.5)[1],
                       "lx": 0.0, "ly": 0.0})
    labels = place_labels_on_own_edge(labels, segs, rects)
    label_of = {lab["for"]: lab for lab in labels}

    spec = rules.get("node_info") or {}
    info = node_info(base, spec)
    desc_col = spec.get("description_column", "output")
    panel_labels = spec.get("panel_labels", {})
    nodes = []
    for n in ids:
        meta = dict(info.get(n, {}))
        desc = meta.pop(desc_col, "")
        nodes.append({"id": n, "x": x_of[level_of.get(n, 0)], "y": y_of[("n", n)] - h / 2,
                      "level": level_of.get(n, 0), "w": w, "h": h,
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
        "sx": sx,
        "canvas": {"w": (max(level_of.values(), default=0) + 1) * sx + 120,
                   "h": (height + 1) * sy + 160},
        "labels": [{"for": l["for"], "idx": l["idx"], "lx": round(l["lx"], 1),
                    "ly": round(l["ly"], 1), "w": round(l["w"], 1),
                    "on_own": l["on_own"], "cross_others": l["cross_others"]} for l in labels],
        "stats": {"crossings": getattr(order_layers, "crossings", -1),
                  "labels": len(labels),
                  "label_overlaps": len(overlaps(labels)),
                  "labels_off_own_edge": sum(1 for l in labels if not l["on_own"]),
                  "labels_crossing_others": sum(1 for l in labels if l["cross_others"])},
    }


# --------------------------------------------------------------------------- #
# render
# --------------------------------------------------------------------------- #
TEMPLATE = HERE / "graph_template.html"


def render(config_path):
    """Returns (html, data). Handing data back avoids re-parsing the page."""
    cfg, _rules, data = build(config_path)
    page = Path(TEMPLATE).read_text(encoding="utf-8")
    html = (page.replace("__DATA__", json.dumps(data, ensure_ascii=False))
                .replace("__TITLE__", data["title"])
                .replace("__SOURCE__", cfg["mmd"]))
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
              f"交叉 {data['stats']['crossings']} / 标签 {data['stats']['labels']}")
        if args.open_it:
            os.startfile(str(cfg_path)) if hasattr(os, "startfile") else os.system(f'xdg-open "{cfg_path}"')
    return stale


if __name__ == "__main__":
    sys.exit(main())

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
CHAR_W = 6.2          # rough glyph width for label collision maths
LABEL_H = 12.0


# --------------------------------------------------------------------------- #
# rules
# --------------------------------------------------------------------------- #
def load_rules(path):
    rules = json.loads(Path(path).read_text(encoding="utf-8"))
    rules["_by_style"] = {(p["stroke"].lower(), bool(p["dash"])): p for p in rules["palette"]}
    return rules


def classify(doc, rules):
    """Attach a relation class to every edge. Index follows linkStyle numbering."""
    unknown, out = [], []
    for i, e in enumerate(doc.edges):
        style = mermaid_doc.style_for(doc, i)
        key = (style.get("stroke", "").lower(), e.dashed)
        spec = rules["_by_style"].get(key)
        if spec is None:
            spec = rules["unknown"]
            if spec.get("reject"):
                unknown.append(f"line {e.line}: {e.src} -> {e.dst} "
                               f"stroke={key[0] or '<none>'} 箭头={'虚' if key[1] else '实'}")
        out.append({"src": e.src, "dst": e.dst, "label": e.label, "line": e.line,
                    "index": i, "kind": spec["class"],
                    "stroke": spec.get("stroke") or key[0], "dash": key[1]})
    if unknown:
        raise SystemExit("配色未在 graph-rules.json 的 palette 中登记：\n  " + "\n  ".join(unknown))
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
    ordering = {p["class"] for p in rules["palette"] if p.get("ordering")}
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

    geo, labels = {}, []
    for idx, e in enumerate(edges):
        a, b = e["src"], e["dst"]
        la, lb = level_of.get(a, 0), level_of.get(b, 0)
        ya = slot_y(a, idx, out_slots[a], False)
        yb = slot_y(b, idx, in_slots[b], True)
        if la < lb:
            pts = [(x_of[la] + w, ya)]
            for l in range(la + 1, lb):
                pts.append((x_of[l] - 16, y_of[("d", (idx, l))]))
            pts.append((x_of[lb], yb))
        else:
            lane = back_lanes[idx] % 5
            bulge = 60 + lane * 16
            midx = (x_of[la] + x_of[lb] + w) / 2
            pts = [(x_of[la] + w / 2, ya - h / 2 - 6),
                   (midx, min(ya, yb) - bulge), (x_of[lb] + w / 2, yb - h / 2 - 6)]
        geo[idx] = pts
        # label anchor: midpoint of the longest segment
        best_seg, best_len = pts[:2], -1
        for p, q in zip(pts, pts[1:]):
            length = abs(q[0] - p[0]) + abs(q[1] - p[1])
            if length > best_len:
                best_len, best_seg = length, (p, q)
        labels.append({"for": f"{a}->{b}", "lx": (best_seg[0][0] + best_seg[1][0]) / 2,
                       "ly": (best_seg[0][1] + best_seg[1][1]) / 2,
                       "w": max(24.0, len(e["label"]) * CHAR_W)})

    labels = label_geometry(labels)
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
        "primary": sorted(ordering),
        "colours": {p["class"]: p["stroke"] for p in rules["palette"]},
        "dashed": {p["class"]: bool(p["dash"]) for p in rules["palette"]},
        "box": {"w": w, "h": h},
        "sx": sx,
        "canvas": {"w": (max(level_of.values(), default=0) + 1) * sx + 120,
                   "h": (height + 1) * sy + 160},
        "labels": [{"for": l["for"], "lx": round(l["lx"], 1), "ly": round(l["ly"], 1),
                    "w": round(l["w"], 1)} for l in labels],
        "stats": {"crossings": getattr(order_layers, "crossings", -1),
                  "labels": len(labels),
                  "label_overlaps": len(overlaps(labels))},
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

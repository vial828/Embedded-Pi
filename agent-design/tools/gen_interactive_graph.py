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

A config is a small JSON file sitting next to the diagram it renders:

    {"mmd": "diagram.mmd", "out": "diagram.graph.html",
     "rules": "tools/graph-rules.json", "title": "标题"}

Layout rule: horizontal position = longest path over the edge classes marked
`"ordering": true` in the palette (SCC-condensed, so genuine feedback loops
collapse to one column instead of breaking the ordering). Colours that are not
registered in the palette are a hard error - a silently grey edge is how the old
hand-written style block lied for a month.
"""

import argparse
import collections
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mermaid_doc  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):   # Windows 控制台默认 cp936/cp1252，中文会炸
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent


# --------------------------------------------------------------------------- #
# rules
# --------------------------------------------------------------------------- #
def load_rules(path: Path) -> dict:
    rules = json.loads(Path(path).read_text(encoding="utf-8"))
    rules["_by_style"] = {(p["stroke"].lower(), bool(p["dash"])): p for p in rules["palette"]}
    return rules


def classify(doc, rules):
    """Attach a relation class to every edge. Index follows linkStyle numbering."""
    unknown, out = [], []
    for i, e in enumerate(doc.edges):
        style = mermaid_doc.style_for(doc, i)
        # 语义来源：颜色来自 linkStyle，虚线来自 Mermaid 自己的箭头写法
        key = (style.get("stroke", "").lower(), e.dashed)
        spec = rules["_by_style"].get(key)
        if spec is None:
            spec = rules["unknown"]
            if spec.get("reject"):
                unknown.append(f"line {e.line}: {e.src} -> {e.dst} "
                               f"stroke={key[0] or '<none>'} 箭头={'虚' if key[1] else '实'}")
        out.append({"src": e.src, "dst": e.dst, "label": e.label, "line": e.line,
                    "index": i, "kind": spec["class"],
                    "stroke": spec.get("stroke") or key[0],
                    "dash": key[1]})
    if unknown:
        raise SystemExit("配色未在 graph-rules.json 的 palette 中登记：\n  " + "\n  ".join(unknown))
    legend = doc.legend_nodes()
    return [e for e in out if e["src"] not in legend and e["dst"] not in legend]


# --------------------------------------------------------------------------- #
# layout
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


def order_within_levels(by_level, edges, sweeps):
    """Barycentre sweeps: alphabetical rows tangle the feedback edges."""
    order_of_levels = sorted(by_level)
    pos = {n: i for l in order_of_levels for i, n in enumerate(by_level[l])}
    up, down = collections.defaultdict(list), collections.defaultdict(list)
    for e in edges:
        down[e["src"]].append(e["dst"])
        up[e["dst"]].append(e["src"])

    def sweep(levels_subset, neighbours):
        for l in levels_subset:
            members = set(by_level[l])

            def key(n):
                refs = [pos[m] for m in neighbours[n] if m in pos and m not in members]
                return (sum(refs) / len(refs) if refs else pos[n], n)

            by_level[l].sort(key=key)
            for i, n in enumerate(by_level[l]):
                pos[n] = i

    for _ in range(max(1, int(sweeps))):
        sweep(order_of_levels[1:], up)
        sweep(list(reversed(order_of_levels))[:-1], down)
    return pos


# --------------------------------------------------------------------------- #
# node metadata: looked up by table header names, never by id pattern
# --------------------------------------------------------------------------- #
def node_info(md_path: Path, spec):
    if not spec:
        return {}
    path = md_path / spec["md"] if not Path(spec["md"]).is_absolute() else Path(spec["md"])
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
# build + render
# --------------------------------------------------------------------------- #
def build(config_path: Path):
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
    layout = rules.get("layout", {})
    ordering = {p["class"] for p in rules["palette"] if p.get("ordering")}
    skip = doc.no_layout_ids()
    lvl, loop, _members = levels(edges, ordering, skip)

    ids = sorted({e["src"] for e in edges} | {e["dst"] for e in edges})
    info = node_info(base, rules.get("node_info"))
    by_level = collections.defaultdict(list)
    for n in ids:
        by_level[lvl.get(n, 0)].append(n)
    for l in by_level:
        by_level[l].sort()
    pos = order_within_levels(by_level, edges, layout.get("sweeps", 4))

    present = []
    for p in rules["palette"]:
        if any(e["kind"] == p["class"] for e in edges):
            present.append({"kind": p["class"], "title": p["title"], "desc": p["desc"],
                            "stroke": p["stroke"], "dash": bool(p["dash"])})

    nodes = []
    for n in ids:
        meta = info.get(n, {})
        nodes.append({"id": n, "x": lvl.get(n, 0), "y": pos[n], "level": lvl.get(n, 0),
                      "label": doc.nodes[n].label if n in doc.nodes else "",
                      "name": meta.get("name", "") or (doc.nodes[n].label if n in doc.nodes else ""),
                      "extra": {k: v for k, v in meta.items() if k != "name"},
                      "loop": n in loop})
    return cfg, rules, {
        "title": cfg.get("title", mmd.stem),
        "nodes": nodes,
        "edges": [{"s": e["src"], "t": e["dst"], "label": e["label"], "kind": e["kind"]}
                  for e in edges],
        "legend": present,
        "colours": {p["class"]: p["stroke"] for p in rules["palette"]},
        "dashed": {p["class"]: bool(p["dash"]) for p in rules["palette"]},
        "layout": layout,
    }


HTML = r"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__（交互）</title>
<!-- 由 tools/gen_interactive_graph.py 从 __SOURCE__ 生成，勿手改 -->
<style>
 body{margin:0;font:13px/1.5 system-ui,'Segoe UI',sans-serif;background:#F8FAFC;color:#0F172A}
 #bar{position:fixed;top:0;left:0;right:0;background:#fff;border-bottom:1px solid #E2E8F0
      padding:8px 12px;display:flex;gap:12px;align-items:center;flex-wrap:wrap;z-index:2}
 #bar label{cursor:pointer;user-select:none}
 button{border:1px solid #CBD5E1;background:#fff;border-radius:6px;padding:3px 9px;cursor:pointer}
 button.on{background:#0F172A;color:#fff;border-color:#0F172A}
 .sw{display:inline-block;width:22px;border-top-width:3px;vertical-align:middle;margin-right:4px}
 #hint{color:#64748B}
 #info{position:fixed;right:12px;top:56px;width:300px;background:#fff;border:1px solid #E2E8F0
      border-radius:8px;padding:10px 12px;display:none;z-index:2;box-shadow:0 2px 8px #0F172A14}
 #info h3{margin:0 0 6px;font-size:14px} #info table{width:100%;border-collapse:collapse;font-size:12px}
 #info td{padding:2px 0;vertical-align:top;word-break:break-all}
 #info td.k{color:#64748B;width:66px;white-space:nowrap}
 #warn{margin-top:6px;color:#B45309}
 #lg{margin-top:8px;color:#94A3B8;font-size:11px}
 svg{display:block;cursor:grab} .dim{opacity:.07} .lbl{font-size:10px;fill:#475569}
 .node text{font-size:12px;font-weight:600;fill:#0F172A;pointer-events:none}
 .node{cursor:pointer} .lv{fill:#94A3B8;font-size:11px;font-weight:700}
</style></head><body>
<div id=bar>
  <b>__TITLE__</b>
  <span>方向</span>
  <button data-d=both class=on>上下游</button><button data-d=down>下游</button><button data-d=up>上游</button>
  <span>深度</span>
  <button data-k=1>1</button><button data-k=2>2</button><button data-k=99 class=on>全部</button>
  <span>类别</span><span id=filters></span>
  <button id=reset>重置</button>
  <span id=hint>点节点聚焦 · 拖拽平移 · 滚轮缩放 · Esc 取消</span>
</div>
<div id=info></div>
<svg id=svg></svg>
<script>
const D = __DATA__;
const L = D.layout, SX=L.level_spacing||250, SY=L.row_spacing||66, W=L.node_width||152, H=L.node_height||42;
const COL=D.colours, DASH=D.dashed;
let dir='both', depth=99, on={}, focus=null, tx=70, ty=80, sc=1;
D.legend.forEach(l=>on[l.kind]=1);
const svg=document.getElementById('svg'), NS='http://www.w3.org/2000/svg';
const byId=Object.fromEntries(D.nodes.map(n=>[n.id,n]));
const out={}, inn={};
D.edges.forEach(e=>{(out[e.s]=out[e.s]||[]).push(e);(inn[e.t]=inn[e.t]||[]).push(e);});
const esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

document.getElementById('filters').innerHTML = D.legend.map(l=>
  `<label><input type=checkbox data-c=${l.kind} checked>
   <span class=sw style="border-top:3px ${l.dash?'dashed':'solid'} ${l.stroke}"></span>${esc(l.title)}</label>`).join(' ');
document.querySelectorAll('[data-c]').forEach(b=>b.onchange=()=>{on[b.dataset.c]=b.checked?1:0;draw();});

// 'both' walks the graph undirected: a feedback edge still means a real relation.
function reach(start, direction, limit){
  const seen={[start]:0}, q=[[start,0]];
  limit = limit===undefined ? depth : limit;
  while(q.length){
    const [n,d]=q.shift(); if(d>=limit) continue;
    const cand=[];
    if(direction!=='up')   for(const e of (out[n]||[])) cand.push([e.t,e]);
    if(direction!=='down') for(const e of (inn[n]||[])) cand.push([e.s,e]);
    for(const [m,e] of cand){
      if(!on[e.kind]) continue;
      if(seen[m]===undefined){seen[m]=d+1;q.push([m,d+1]);}
    }
  }
  return seen;
}
const el=(t,a)=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);return e;};
const hop=(set,f)=>Object.keys(set).filter(x=>set[x]===f&&x!==focus).sort().join(' ')||'—';

function draw(){
  svg.innerHTML='';
  const g=el('g',{transform:`translate(${tx},${ty}) scale(${sc})`}); svg.appendChild(g);
  const keep = focus ? reach(focus, dir) : null;
  const maxLv=Math.max(...D.nodes.map(n=>n.level));
  for(let l=0;l<=maxLv;l++)
    g.appendChild(el('text',{x:l*SX,y:-20,class:'lv'})).textContent='L'+l;

  D.edges.forEach(e=>{
    if(!on[e.kind]) return;
    const a=byId[e.s], b=byId[e.t]; if(!a||!b) return;
    const vis = !keep || (keep[e.s]!==undefined && keep[e.t]!==undefined);
    const x1=a.x*SX+W, y1=a.y*SY+H/2, x2=b.x*SX, y2=b.y*SY+H/2;
    const mx=(x1+x2)/2 + (b.x<=a.x ? 70 : 0);
    g.appendChild(el('path',{class:'edge'+(vis?'':' dim'),
      d:`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`,fill:'none',
      stroke:COL[e.kind],'stroke-width':e.kind==='open'?3:1.8,
      'marker-end':`url(#a${e.kind})`,'stroke-dasharray':DASH[e.kind]?'7 4':''}));
    const t=el('text',{class:'lbl'+(vis?'':' dim'),x:mx,y:(y1+y2)/2-4,'text-anchor':'middle'});
    t.textContent=e.label; g.appendChild(t);
  });

  D.nodes.forEach(n=>{
    const dim = keep && keep[n.id]===undefined;
    const gg=el('g',{class:'node'+(dim?' dim':''),transform:`translate(${n.x*SX},${n.y*SY})`});
    gg.appendChild(el('rect',{width:W,height:H,rx:7,fill:focus===n.id?'#DBEAFE':'#fff',
      stroke:n.loop?'#DC2626':'#334155','stroke-width':1.6}));
    const t=el('text',{x:10,y:17}); t.textContent=n.id+(n.loop?' ⟳':''); gg.appendChild(t);
    const t2=el('text',{x:10,y:31,'font-size':10,'font-weight':400,fill:'#64748B'});
    t2.textContent=(n.name||'').slice(0,13); gg.appendChild(t2);
    gg.onclick=ev=>{ev.stopPropagation();focus=focus===n.id?null:n.id;info();draw();};
    g.appendChild(gg);
  });

  const defs=el('defs',{}); g.appendChild(defs);
  for(const k in COL){
    const m=el('marker',{id:'a'+k,viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:6,markerHeight:6,orient:'auto'});
    m.appendChild(el('path',{d:'M0,0 L10,5 L0,10 z',fill:COL[k]})); defs.appendChild(m);
  }
  svg.setAttribute('width',innerWidth);
  svg.setAttribute('height',Math.max(innerHeight-10,(Math.max(...D.nodes.map(n=>n.y))+2)*SY+140));
}

function info(){
  const box=document.getElementById('info');
  if(!focus){box.style.display='none';return;}
  const n=byId[focus];
  const up=reach(focus,'up',2), down=reach(focus,'down',2), all=reach(focus,dir);
  const cnt={}; D.edges.forEach(e=>{if(e.s===focus||e.t===focus)cnt[e.kind]=(cnt[e.kind]||0)+1;});
  const extras=Object.entries(n.extra||{}).map(([k,v])=>
    `<tr><td class=k>${esc(k)}</td><td>${esc(v)}</td></tr>`).join('');
  box.style.display='block';
  box.innerHTML=`<h3>${esc(focus)} ${esc(n.name||'')}</h3><table>
   ${extras}
   <tr><td class=k>开发层级</td><td>L${n.level}</td></tr>
   <tr><td class=k>直连边</td><td>${D.legend.map(l=>`${esc(l.title)} ${cnt[l.kind]||0}`).join(' · ')}</td></tr>
   <tr><td class=k>上游 1 跳</td><td>${hop(up,1)}</td></tr>
   <tr><td class=k>上游 2 跳</td><td>${hop(up,2)}</td></tr>
   <tr><td class=k>下游 1 跳</td><td>${hop(down,1)}</td></tr>
   <tr><td class=k>下游 2 跳</td><td>${hop(down,2)}</td></tr>
   <tr><td class=k>聚焦合计</td><td>${Object.keys(all).length-1} 个节点</td></tr>
   </table>
   ${n.loop?'<div id=warn>⟳ 在数据环内，须与同环节点一起设计或先钉接口</div>':''}
   <div id=lg>${D.legend.map(l=>`<span class=sw style="border-top:3px ${l.dash?'dashed':'solid'} ${l.stroke}"></span>${esc(l.desc)}`).join('<br>')}</div>`;
}

document.querySelectorAll('[data-d]').forEach(b=>b.onclick=()=>{dir=b.dataset.d;
  document.querySelectorAll('[data-d]').forEach(x=>x.classList.toggle('on',x===b));draw();});
document.querySelectorAll('[data-k]').forEach(b=>b.onclick=()=>{depth=+b.dataset.k;
  document.querySelectorAll('[data-k]').forEach(x=>x.classList.toggle('on',x===b));draw();});
document.getElementById('reset').onclick=()=>{focus=null;tx=70;ty=80;sc=1;info();draw();};
svg.addEventListener('click',()=>{if(focus){focus=null;info();draw();}});
addEventListener('keydown',e=>{if(e.key==='Escape'&&focus){focus=null;info();draw();}});
let drag=null;
svg.onmousedown=e=>{drag=[e.clientX-tx,e.clientY-ty];svg.style.cursor='grabbing';};
addEventListener('mouseup',()=>{drag=null;svg.style.cursor='grab';});
addEventListener('mousemove',e=>{if(drag){tx=e.clientX-drag[0];ty=e.clientY-drag[1];draw();}});
svg.addEventListener('wheel',e=>{e.preventDefault();sc=Math.min(2.5,Math.max(.3,sc*(e.deltaY<0?1.12:.9)));draw();},{passive:false});
addEventListener('resize',draw);
draw();
</script></body></html>
"""


def render(config_path: Path) -> str:
    cfg, _rules, data = build(config_path)
    return (HTML.replace("__DATA__", json.dumps(data, ensure_ascii=False))
                .replace("__TITLE__", data["title"])
                .replace("__SOURCE__", cfg["mmd"]))


def outputs(configs):
    for c in configs:
        cfg = json.loads(Path(c).read_text(encoding="utf-8"))
        yield Path(c).parent / cfg["out"], render(Path(c))


def main() -> int:
    ap = argparse.ArgumentParser(description="Mermaid -> 可交互 HTML 图")
    ap.add_argument("configs", nargs="*", help="*.graph.json，缺省则自动发现")
    ap.add_argument("--check", action="store_true", help="只检查产物是否过期，非 0 退出即过期")
    ap.add_argument("--open", dest="open_it", action="store_true", help="生成后用默认程序打开")
    args = ap.parse_args()

    configs = [Path(c) for c in args.configs]
    if not configs:
        root = HERE.parent
        configs = sorted(root.rglob("*.graph.json"))
    if not configs:
        print("没有找到 *.graph.json 配置")
        return 1

    stale = 0
    for cfg_path, html in outputs(configs):
        data = json.loads(re.search(r"const D = (\{.*?\});\n", html, re.S).group(1))
        kinds = collections.Counter(e["kind"] for e in data["edges"])
        if args.check:
            ok = cfg_path.exists() and cfg_path.read_text(encoding="utf-8") == html
            print(("up to date   " if ok else "STALE  ") + cfg_path.name)
            stale |= 0 if ok else 1
            continue
        cfg_path.write_text(html, encoding="utf-8")
        print(f"{cfg_path.name}: {len(data['nodes'])} 节点 / {len(data['edges'])} 边 "
              + " ".join(f"{k}:{v}" for k, v in sorted(kinds.items())))
        if args.open_it:
            os.startfile(str(cfg_path)) if hasattr(os, "startfile") else os.system(f'xdg-open "{cfg_path}"')
    return stale


if __name__ == "__main__":
    sys.exit(main())

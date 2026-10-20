"""Standard-Mermaid parser: no knowledge of any particular diagram.

Recognises the elements that are part of Mermaid's own syntax - flowchart
declarations, node definitions with labels, subgraphs, edges with optional
labels, `linkStyle` / `classDef` / `style` statements, `%%` comments - and turns
them into plain data. Semantics (what a colour means, which edges drive layout)
live in a rules file, not here.

Two directives are understood, both written as ordinary Mermaid comments so the
file still renders unchanged:

    %% @legend <subgraphId>      exclude that subgraph and its edges from the graph
    %% @no-layout <nodeId>       keep the node, but never use it to derive levels

Anything that looks like an edge but cannot be parsed is reported, never skipped
silently.
"""

import re
from dataclasses import dataclass, field

COMMENT = re.compile(r"^\s*%%(?P<text>.*)$")
DIRECTIVE = re.compile(r"^\s*%%\s*@(?P<name>[\w-]+)(?P<args>.*)$")
ARROW = re.compile(r"(-\.->|-\.->|-->|---|==>|===|<->|<=>|-\.-|-{2,}|={2,})")
NODE_DEF = re.compile(r"^(?P<id>[A-Za-z0-9_][\w-]*)"
                      r"(?P<label>\[[^\]]*\]|\([^)]*\)|\{[^}]*\})?$")
SUBGRAPH = re.compile(r"^\s*subgraph\s+(?P<id>[\w-]+)(?:\[(?P<title>[^\]]*)\]|\s+(?P<title2>.+?))?\s*$")
STYLE_STMT = re.compile(r"^\s*(classDef|style|click|class|direction|accTitle|accDescr|callback)\s+")
DECL = re.compile(r"^\s*(flowchart|graph)\s+")


@dataclass
class Node:
    id: str
    label: str = ""
    subgraph: str = ""


@dataclass
class Edge:
    src: str
    dst: str
    arrow: str
    label: str = ""
    line: int = 0
    src_label: str = ""
    dst_label: str = ""

    @property
    def dashed(self) -> bool:
        """Mermaid's own notation: `-.->` is a dotted/dashed link, `-->` is not."""
        return "." in self.arrow

    @property
    def thick(self) -> bool:
        return "=" in self.arrow


@dataclass
class MermaidDoc:
    nodes: dict = field(default_factory=dict)
    edges: list = field(default_factory=list)          # declaration order == linkStyle index
    link_styles: dict = field(default_factory=dict)    # index -> {stroke, dash, width}
    subgraphs: dict = field(default_factory=dict)
    directives: list = field(default_factory=list)
    problems: list = field(default_factory=list)

    def legend_ids(self):
        return {t for _n, args, _l in self.directives if _n == "legend" for t in args.split()[:1]}

    def no_layout_ids(self):
        return {t for _n, args, _l in self.directives if _n == "no-layout" for t in args.split()}

    def aliases(self):
        """`%% @alias <copyId> = <targetId>` - a rendering copy of one node.

        A node gets one position. A source feeding consumers at both ends of the picture
        can therefore sit next to one of them, or next to neither - never next to all.
        Copies let the picture say "the same input is used over there too" without lying
        about the topology: every consumer collapses copies through `canonical()` before
        computing anything, so ordering, cycles and coverage still see one node.
        """
        out = {}
        for name, args, _line in self.directives:
            if name != "alias":
                continue
            left, _, right = args.partition("=")
            if left.strip() and right.strip():
                out[left.strip()] = right.strip()
        return out

    def canonical(self, node_id):
        target, seen = self.aliases().get(node_id, node_id), {node_id}
        while target in self.aliases() and target not in seen:
            seen.add(target)
            target = self.aliases()[target]
        return target

    def alias_problems(self):
        """A copy that drifts from its original is worse than no copy: it reads as a
        different input. So the label must match, the target must exist, and an unused
        copy is noise that belongs in the bin."""
        out = []
        for copy, target in sorted(self.aliases().items()):
            if target not in self.nodes:
                out.append(f"别名 {copy} 指向不存在的节点 {target}")
            elif copy in self.nodes and target in self.nodes                     and self.nodes[copy].label != self.nodes[target].label:
                out.append(f"别名 {copy} 的文字是 {self.nodes[copy].label!r}，原件是 {self.nodes[target].label!r}")
            elif copy not in self.nodes:
                out.append(f"别名 {copy} 没有节点定义")
            used = {e.src for e in self.edges} | {e.dst for e in self.edges}
            if copy not in used:
                out.append(f"别名 {copy} 一条边都没连，是噪音")
        return out

    def legend_nodes(self):
        """Node ids declared inside a subgraph named by `%% @legend <id>`."""
        ids = self.legend_ids()
        drop = {n.id for n in self.nodes.values() if n.subgraph in ids}
        return drop | {n for n in self.nodes if n in ids}

    def graph_edges(self):
        drop = self.legend_nodes()
        return [e for e in self.edges if e.src not in drop and e.dst not in drop]


def _split_node(token):
    m = NODE_DEF.match(token.strip())
    if not m:
        return None, None
    raw = m.group("label") or ""
    return m.group("id"), raw[1:-1].strip() if raw else ""


def _props(text):
    out = {}
    for part in text.split(","):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out


def parse(text: str) -> MermaidDoc:
    doc = MermaidDoc()
    stack = []
    for no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        d = DIRECTIVE.match(line)
        if d:
            doc.directives.append((d.group("name"), d.group("args"), no))
            continue
        if COMMENT.match(line):
            continue
        if DECL.match(line):
            continue
        if line == "end":
            if stack:
                stack.pop()
            continue
        sg = SUBGRAPH.match(line)
        if sg:
            title = sg.group("title") or sg.group("title2") or sg.group("id")
            doc.subgraphs[sg.group("id")] = title.strip()
            stack.append(sg.group("id"))
            continue
        if STYLE_STMT.match(line):
            continue

        m = re.match(r"^\s*linkStyle\s+(?:(\d+)|default)\b(.*)$", line)
        if m:
            key = int(m.group(1)) if m.group(1) is not None else "default"
            p = _props(m.group(2))
            doc.link_styles[key] = {
                "stroke": (p.get("stroke") or "").lower(),
                "dash": "dasharray" in p,
                "width": p.get("stroke-width", ""),
            }
            continue

        if ARROW.search(line) is None:
            node_id, label = _split_node(line)
            if node_id:
                doc.nodes.setdefault(node_id, Node(node_id, label, stack[-1] if stack else ""))
                if label and not doc.nodes[node_id].label:
                    doc.nodes[node_id].label = label
            else:
                doc.problems.append((no, raw))
            continue

        parts = list(ARROW.finditer(line))
        if len(parts) != 1:
            doc.problems.append((no, raw))
            continue
        arrow = parts[0]
        left, right = line[:arrow.start()].strip(), line[arrow.end():].strip()
        label = ""
        m = re.match(r"^\|\s*(.*?)\s*\|\s*(.*)$", right)
        if m:
            label, right = m.group(1), m.group(2)
        else:
            m = re.match(r"^--\s*(.*?)\s*-->\s*(.*)$", line[arrow.start():])
            if m:
                label, right = m.group(1), m.group(2)
        src, src_label = _split_node(left)
        dst, dst_label = _split_node(right)
        if not src or not dst:
            doc.problems.append((no, raw))
            continue
        for nid, nlabel in ((src, src_label), (dst, dst_label)):
            n = doc.nodes.setdefault(nid, Node(nid, nlabel, stack[-1] if stack else ""))
            if nlabel and not n.label:
                n.label = nlabel
        doc.edges.append(Edge(src, dst, arrow.group(1), label, no, src_label, dst_label))
    return doc


def style_for(doc: MermaidDoc, index: int):
    """linkStyle for the i-th link, falling back to `linkStyle default`."""
    return doc.link_styles.get(index) or doc.link_styles.get("default") or {}

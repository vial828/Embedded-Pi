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
import math
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


def spread_side(keys, y_of, pitch, lo, hi, anchors=(), x_of=None):
    """把同一侧接点的最小间距抬到 pitch —— 钉住的（anchors）不动，其余让开。

    为什么需要它：slot_y() 只在框高里按对端 y 扇开，align_ports() 又会把几条边拉到同一
    高度，两者都没保证"最终间距"，实测 S11 入侧挤到 2.3px（两条线看着像一根）。

    四条规矩都是试出来的，每条对应一次回退：
    - 保持原有上下先后，只加间距不换位置 —— 否则会把 port_order 人工交换过的线换回去。
    - 每轮只解"最挤的一对"，往下补、顶到框底才往上补。整组等距重排会把对齐成直线的边
      白白拉折（直线边 18 -> 10、折点 +16）；上下各挪一半会把接点抬进上方别的边的横段
      里（IN_PRD->S18 就叠上去了）。
    - x_of：同一根出口竖线上的接脚不算密集。同一个通道里的几条横线本来就要在同一点
      汇合，那是汇聚不是重叠；把它们拉开反而多出折角（S22 出侧三条同通道的边 +2 折点）。
      真正要分开的是贴同一根框边、却走不同通道的接口（S11 入侧就是）。
    - 只在"这一侧最终能完全拉开"时才动手。半拉比不拉更差：实测折点 +8、直线边 -1。
    """
    if len(keys) < 2:
        return {}

    def same_lane(a, b):
        return bool(x_of) and x_of[a] == x_of[b]

    pitch = min(float(pitch), (hi - lo) / (len(keys) - 1))
    if pitch <= 0 or hi - lo < (len(keys) - 1) * pitch - 0.01:
        return {}                                        # 这一侧装不下：整侧不动
    got = {k: float(y_of[k]) for k in keys}
    order = sorted(keys, key=lambda k: (got[k], k))
    for _ in range(len(keys) * len(keys) + 4):
        tight = [(got[b] - got[a], a, b) for a, b in zip(order, order[1:])
                 if not same_lane(a, b) and got[b] - got[a] < pitch - 0.01]
        if not tight:
            break
        _gap, a, b = min(tight, key=lambda t: t[0])       # 最挤的一对先解
        need = pitch - (got[b] - got[a])
        if b not in anchors and got[b] + need <= hi + 0.01:
            got[b] += need                                # 下面还有地方
        elif a not in anchors:
            got[a] = max(got[a] - need, lo)               # 顶到框底，往上让
        else:
            break                                         # 两端都钉住：宁可维持原样
    if any(not same_lane(a, b) and got[b] - got[a] < pitch - 0.01
           for a, b in zip(order, order[1:])):
        return {}                                         # 拉不开：保持原样
    return {k: v for k, v in got.items()
            if k not in anchors and abs(v - y_of[k]) > 0.01}


def spread_sides(geo, edges, level_of, pitch, ny, h_of, port_order, avoid):
    """按"同一个框的同一根边"分组拉开接点，再把新 y 写回折线。返回没拉开的接点对数。

    为什么不能用 out_slots / in_slots：它们只按 src、dst 分。S10 出侧看着"已经拉开"，
    其实那两条线一条是 IN_HW->S10（右入）、一条是 S10->S11（右出），贴的是同一根边；
    分成两组就永远查不出来。反向边的接口贴在框的左边，同理要单独一组。

    写回只沿"和该接口在同一根竖段"的点接回去，别的拐点不碰 —— 端点一挪接不上去的话
    第一条横线就被拉斜（正交化的测试会拦下斜线，所以这里必须自己接好）。

    返回的对数是给人的信号：这一侧的框高装不下这么多接口，只能靠加高节点或改布局解决，
    不是这里能猜的。
    """
    groups = collections.defaultdict(list)
    for i, e in enumerate(edges):
        back = level_of.get(e["src"], 0) >= level_of.get(e["dst"], 0)
        # (框, 左/右)：正边 右出→左入；反向边 左出→右入（和路由的写法一致）
        groups[(e["src"], "left" if back else "right")].append((i, 0))
        groups[(e["dst"], "right" if back else "left")].append((i, -1))

    def pinned(i):
        name = f"{edges[i]['src']}->{edges[i]['dst']}"
        return name in avoid or \
            name in (port_order.get(edges[i]["src"]) or []) or \
            name in (port_order.get(edges[i]["dst"]) or [])

    tight = 0
    for (nid, _side), ports in groups.items():
        if len(ports) < 2:
            continue
        tag = lambda p_: f"{p_[0]}:{p_[1]}"              # noqa: E731
        moved = spread_side([tag(p_) for p_ in ports],
                            {tag(p_): geo[p_[0]][p_[1]][1] for p_ in ports},
                            pitch, ny[nid] - h_of[nid] / 2 + 4,
                            ny[nid] + h_of[nid] / 2 - 4,
                            [tag(p_) for p_ in ports if pinned(p_[0])],
                            {tag(p_): geo[p_[0]][p_[1]][0] for p_ in ports})
        for k, y in moved.items():
            i, j = (int(v) for v in k.split(":"))
            pts = list(geo[i])
            step = 1 if j == 0 else -1
            out = list(pts)
            out[j] = (pts[j][0], y)
            m = j + step
            while 0 < m < len(out) and abs(out[m][0] - out[m - step][0]) < 0.5:
                out[m] = (out[m][0], y)
                m += step
            geo[i] = simplify(out)
        ys = sorted(geo[i][j][1] for i, j in ports)
        tight += sum(1 for a, b in zip(ys, ys[1:]) if b - a < pitch - 0.01)
    return tight





def layer_rank(group_ids, edges_between, tie_break=None):
    """层与层的上下次序：按依赖排，被依赖的在上（和"左出右入"同一个方向感）。

    为什么不能"谁面积大谁当主轴、小的贴过去"：那只是把重叠消掉，层序会变成随机的 ——
    实测外部输入层被推到基础层下面，读图的人第一句就是"输入怎么在中间"。
    边的方向本身就是语义（S02 -> S08 -> S15），层的纵向次序必须由它定。

    三步，每步都对应一次回退：
    1. 传递闭包（a 能走到 b，a 就在 b 上面）。不能用"最长路径 + 丢掉环里的边"：Memory ->
       AgentCore 正好在记忆簇那个大环里，一丢就把"记忆先于核心"这条真实次序也丢了。
    2. 互相可达的层折成一个点（SCC）—— 它们本来就在来回，属于同一层，名次并列。给它们排
       出先后的话，同一列会串成一条长队（L4 那列排到 1673px）。并排摊开是 spread_layers 的事。
    3. 折完才是 DAG：堆的名次 = 它上面还有几个堆。注意"上面有几个"要按堆去重 —— 直接数
       层数的话，一堆里三个并列的层会被重复计入，名次全部挤在一起（实测全图只排出 0/1/2）。

    tie_break：并列时给个起点（一般给当前顶边），只影响同堆内的展开次序，不影响名次。
    """
    key = tie_break or (lambda gid: 0.0)
    ids = sorted(group_ids, key=key)
    down = collections.defaultdict(set)
    for a, b in edges_between:
        if a in group_ids and b in group_ids and a != b:
            down[a].add(b)

    def reach(src):
        seen, queue = set(), [src]
        while queue:
            cur = queue.pop()
            for nxt in down[cur]:
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        return seen

    below = {i: reach(i) & set(ids) for i in ids}         # 能走到的都在它下面

    comp_of, comp = {}, []                                # 互相可达归一堆，堆内并列
    for i in ids:
        if i in comp_of:
            continue
        c = [j for j in ids if j not in comp_of and (i in below[j] or j == i)
             and (j in below[i] or i == j)]
        for j in c:
            comp_of[j] = len(comp)
        comp.append(c)

    above, under = collections.defaultdict(set), collections.defaultdict(set)
    for a in ids:
        ca = comp_of[a]
        for b in below[a]:
            cb = comp_of[b]
            if ca != cb:
                above[cb].add(ca)                          # 按堆去重，一条边数一次
                under[ca].add(cb)
    rank = {ci: len(above[ci]) for ci in range(len(comp))}
    return {gid: rank[comp_of[gid]] for gid in group_ids}



def stack_layers(members_of, y_of, nx, w_of, h_of, pad, rank, layer_off, locked=(),
                 clear=18.0, min_move=24.0):
    """把纵向叠住的层按依赖次序整层下移。返回是否全部解开。

    两条规矩，每条对应一次回退：
    - 只往下挪，绝不把已经在下面的层提上来。否则会变成"躲开一个又压住下一个"的来回跳，
      拓扑序也会被打乱（Memory 被抬到画布顶、Foundation 掉到底）。
    - 改的是 y_of[("n", 成员)] —— 节点坐标的唯一来源。改换算值 ny 是没用的：端口高度由它
      推出来，第一次那么写就留下 34 条端点悬空的边（框动了、线留在原地）。

    locked = 不许搬也不参与推挤的层（layer_lock）：横跨多列的长条层和谁都叠得上，拿它当
    参照别人就得一路让到底。剩下的重叠由调用方报出来 —— 要人调 col_gap / layer_boxes。

    min_move：小于这个数就不动 —— 搬一整层会牵动它所有边的走线，为几个像素不值得；
    真差得多的（Memory / AgentCore 差 36px）才会被搬。返回 False = 还有压住的。
    """
    def top(m):
        return y_of[("n", m)] + layer_off(m)[1] - h_of[m] / 2

    def rect(gid):
        ms = members_of[gid]
        x1 = min(nx[m] for m in ms) - pad
        x2 = max(nx[m] + w_of[m] for m in ms) + pad
        y1 = min(top(m) for m in ms) - pad
        y2 = max(top(m) + h_of[m] for m in ms) + pad
        return (x1, y1, x2 - x1, y2 - y1)

    ids = [g for g in sorted(members_of) if g not in set(locked)]
    for _ in range(len(ids) * len(ids) + 4):
        hits = []
        for x, y in itertools.combinations(ids, 2):
            a, b = rect(x), rect(y)
            ox = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
            oy = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
            if ox > clear and oy > clear:
                hits.append((ox * oy, x, y))
        if not hits:
            return True
        _area, x, y = max(hits, key=lambda t: t[0])
        upper, lower = (x, y) if rank.get(x, 0) <= rank.get(y, 0) else (y, x)
        need = (rect(upper)[1] + rect(upper)[3] + clear) - rect(lower)[1]
        if abs(need) < min_move:
            return False
        for m in members_of[lower]:
            y_of[("n", m)] += need                              # 节点坐标的唯一来源
    return False


def spread_layers(members_of, y_of, nx, w_of, h_of, pad, rank, layer_off, locked=(),
                  clear=18.0):
    """同一依赖层里叠住的几块，绕着主轴往上下摊开。返回是否全部解开。

    为什么不能只靠 stack_layers：它一次只解重叠最大的一对、被压的那个往下走，于是同层的
    Memory / AgentCore / Verify（rank 都是 3）会一路串到底 —— L4 那一列排成 1673px 的长队，
    每条进出边还要多绕几百像素。同一层本来就没有先后关系（它们之间的边来自记忆簇那个环），
    并排摆着才是它的语义：主轴留原位，别人往上下让。

    谁是主轴：这一堆里"跨度 × 成员数"最大的那块（横向铺得越开、框越多，接的边越多）。它
    不动 —— 挪它等于把整层的进出边全部重排。别人按中心落在主轴中心的哪一边，抬到它上沿或
    压到下沿；同一侧挤着好几块时，让得更远的那个先贴边（外圈先定），否则第二块会叠回第一块。

    locked 里的长条层不参与（见 layer_lock）。摊开带来的偏移（主轴一侧挤两块时整堆会被顶偏）
    由 tidy_layers 收尾，这里不掺和 —— 两件事分开写才不会互相把对方的成果抹掉。
    """
    def top(m):
        return y_of[("n", m)] + layer_off(m)[1] - h_of[m] / 2

    def rect(gid):
        ms = members_of[gid]
        x1 = min(nx[m] for m in ms) - pad
        x2 = max(nx[m] + w_of[m] for m in ms) + pad
        y1 = min(top(m) for m in ms) - pad
        y2 = max(top(m) + h_of[m] for m in ms) + pad
        return (x1, y1, x2 - x1, y2 - y1)

    def hits():
        out = []
        for x, y in itertools.combinations(ids, 2):
            a, b = rect(x), rect(y)
            ox = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
            oy = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
            if ox > clear and oy > clear:
                out.append((ox * oy, x, y))
        return out

    def peers(gid):                        # 同一堆（并列）的层
        return [g for g in ids if rank.get(g, 0) == rank.get(gid, 0)]

    def shift(gid, need):
        for m in members_of[gid]:
            y_of[("n", m)] += need                         # 节点坐标的唯一来源

    ids = [g for g in sorted(members_of) if g not in set(locked)]
    done = set()                           # 摊过的那堆：还压着就是别的层挡着，别死循环
    for _ in range(len(ids) * len(ids) + 4):
        now = hits()
        if not now:
            return True
        same = [h for h in now if rank.get(h[1], 0) == rank.get(h[2], 0)]
        if not same:
            return False                                   # 只剩不同层的，交给 stack_layers
        spine = max(peers(same[0][1]), key=lambda g: rect(g)[2] * len(members_of[g]))
        if spine in done:                                  # 主轴不动也解不开：让给别人没用
            return False
        done.add(spine)
        s = rect(spine)
        mid = s[1] + s[3] / 2
        group = [g for g in peers(spine) if g != spine]
        below_l = sorted((g for g in group if rect(g)[1] + rect(g)[3] / 2 >= mid),
                         key=lambda g: -(rect(g)[1] + rect(g)[3] / 2))
        above_l = sorted((g for g in group if g not in below_l),
                         key=lambda g: rect(g)[1] + rect(g)[3] / 2)
        edge = s[1] + s[3] + clear                         # 下侧：由外向内贴边
        for gid in below_l:
            shift(gid, edge - rect(gid)[1])
            edge = rect(gid)[1] + rect(gid)[3] + clear
        edge = s[1] - clear                                # 上侧：由外向内贴边
        for gid in above_l:
            shift(gid, edge - (rect(gid)[1] + rect(gid)[3]))
            edge = rect(gid)[1] - clear
    return False


def tidy_layers(members_of, y_of, nx, w_of, h_of, pad, rank, layer_off, locked=(),
                clear=18.0):
    """摊开同层之后收尾两件事：不许悬在画布外、把"下面空着一大片"的整堆提上去。

    为什么单独一步：spread_layers 的规矩是主轴不动、别人绕它贴边。当主轴上方挤着两块时，
    整堆会被整个顶到画布外（实测 AgentCore 上沿 -561）。这里不做二次推挤 —— 试过"回中 +
    推挤"多轮迭代，两者互相抹掉对方的成果，画布从 1960 涨到 3127 —— 只做两件不引入新次序的事：

    1. 悬出去的整堆按差值整体下移。基准取锁住的长条层（layer_lock）的上沿：它们不参与推挤，
       位置就当画布的顶边用。不能拿"最高那块"当基准 —— 它自己就是被挪出去的那块，差值恒为 0。
    2. 头顶空着的整堆往上贴到它上面最近那块的下沿。空隙不表示任何东西（上下次序由 rank 定），
       留着只会让图比必要的长一半 —— 实测 L4 那一列和编译层之间空了 275px。

    第 2 步的两条护栏，都对应一次回退：
    - 只能提"自己头顶确实空着、而且提起来不会撞住任何别层"的那一堆：判据是提起来之后重算
      一遍压住对数，变多了就放弃（试过 Foundation 提上去正好盖住 Schema）。
    - 一轮只提最靠上的那一堆。同时提两堆的话，下面那堆会跟着上面那堆的空位走，实测会把
      Delivery 拉到 Schema 同一行去。
    """
    def rect(gid):
        ms = members_of[gid]
        x1 = min(nx[m] for m in ms) - pad
        x2 = max(nx[m] + w_of[m] for m in ms) + pad
        y1 = min(y_of[("n", m)] + layer_off(m)[1] - h_of[m] / 2 for m in ms) - pad
        y2 = max(y_of[("n", m)] + layer_off(m)[1] + h_of[m] / 2 for m in ms) + pad
        return (x1, y1, x2 - x1, y2 - y1)

    def clash_count():
        n = 0
        for a, b in itertools.combinations(list(members_of), 2):
            ra, rb = rect(a), rect(b)
            if (min(ra[0] + ra[2], rb[0] + rb[2]) - max(ra[0], rb[0]) > clear and
                    min(ra[1] + ra[3], rb[1] + rb[3]) - max(ra[1], rb[1]) > clear):
                n += 1
        return n

    ids = [g for g in sorted(members_of) if g not in set(locked)]
    anchors = [g for g in sorted(members_of) if g in set(locked)]
    moved = False

    def shift(gids, need):
        nonlocal moved
        for gid in gids:
            for m in members_of[gid]:
                y_of[("n", m)] += need                     # 节点坐标的唯一来源
        moved = True

    if anchors and ids:                                    # 1) 悬在画布外的整堆拉回来
        top = min(rect(g)[1] for g in anchors)             # 画布上边界（锁住层最高的上沿）
        out = [g for g in ids if rect(g)[1] < top - clear]
        if out:
            worst = min(out, key=lambda g: rect(g)[1])
            shift([g for g in ids if rank.get(g, 0) == rank.get(worst, 0)],
                  top - rect(worst)[1])

    for _ in range(len(ids) + 2):                          # 2) 头顶空着的整堆往上贴
        best = None                                        # (上沿, 堆, 天花板)
        for gid in ids:
            peers = [g for g in ids if rank.get(g, 0) == rank.get(gid, 0)]
            y1 = min(rect(g)[1] for g in peers)
            ceil = None
            for g in members_of:
                if rank.get(g, 0) >= rank.get(gid, 0):
                    continue                               # 只看真正在它上面的那些层
                o, r = rect(g), rect(gid)
                if min(r[0] + r[2], o[0] + o[2]) - max(r[0], o[0]) <= clear:
                    continue                               # 横向不相干：不算天花板
                bottom = o[1] + o[3]
                if bottom >= y1 - clear:
                    continue                               # 在下方或已经贴着
                ceil = bottom if ceil is None else min(ceil, bottom)
            if ceil is None or y1 - ceil <= clear:
                continue
            cand = (y1, peers, ceil)
            if best is None or cand[0] < best[0]:
                best = cand
        if best is None:
            break
        _y1, peers, ceil = best
        was = clash_count()
        want = ceil + clear - min(rect(g)[1] for g in peers)
        shift(peers, want)
        if clash_count() > was:                            # 提上去会压住别层：退回来
            shift(peers, -want)
            break
    return moved



def group_clashes(members_of, y_of, nx, w_of, h_of, pad, layer_off, clear=18.0):
    """还压在一起的层框对（含跨竖带的）：推挤解不掉的那部分，报给人看。"""
    def top(m):
        return y_of[("n", m)] + layer_off(m)[1] - h_of[m] / 2

    def rect(gid):
        ms = members_of[gid]
        x1 = min(nx[m] for m in ms) - pad
        x2 = max(nx[m] + w_of[m] for m in ms) + pad
        y1 = min(top(m) for m in ms) - pad
        y2 = max(top(m) + h_of[m] for m in ms) + pad
        return (x1, y1, x2 - x1, y2 - y1)

    out = []
    for x, y in itertools.combinations(sorted(members_of), 2):
        a, b = rect(x), rect(y)
        ox = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
        oy = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
        if ox > clear and oy > clear:
            out.append(f"{x}/{y}")
    return out



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

    正边的横线已经按 y 排开（每根至少隔 lane_pitch），所以缝内等分就是对的通道分配；
    改成"按占用分配"反而会把不同缝的竖段推到同一个 x 上（实测密集对从 17 涨到 78）。
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
            lane_x[(g, idx)] = x_of[g] + col_w.get(g, 0) + \
                gap_at.get(g, 60.0) * (k + 1) / (n + 1)

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
    # 某条缝可以额外加宽（col_gap_extra.<列号>）：绕行带和列间隙叠在同一竖带上时，只有把
    # 缝拉开才能让开 —— 自动推开解决不了"两个东西抢同一条带子"，那是布局问题。
    col_extra = {int(k): float(v) for k, v in (layout.get("col_gap_extra") or {}).items()}
    x_of, cursor = {}, 0.0
    for l in sorted(layers):
        x_of[l] = cursor
        cursor += col_w[l] + max(h_gap, demand[l] * lane_pitch) + col_extra.get(l, 0.0)

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

    pad_g = layout.get("group_padding", 22)
    gclear = float(layout.get("group_clear", 18.0))
    grp_of = {n: (doc.nodes[n].subgraph if n in doc.nodes else "") for n in ids}
    between = [(grp_of[e["src"]], grp_of[e["dst"]]) for e in edges
               if grp_of.get(e["src"]) and grp_of.get(e["src"]) != grp_of.get(e["dst"])]

    members_of = collections.defaultdict(list)
    for n in ids:
        if grp_of[n] and grp_of[n] not in doc.legend_ids():
            members_of[grp_of[n]].append(n)
    members_of = dict(members_of)

    def build_groups():
        out = []
        for k, ms in sorted(members_of.items()):
            bcfg = boxes_cfg.get(k, {})    # 别叫 cfg：会遮蔽 build() 自己的配置
            x1 = min(nx[m] for m in ms) - pad_g
            x2 = max(nx[m] + w_of[m] for m in ms) + pad_g
            y1 = min(ny[m] - h_of[m] / 2 for m in ms) - pad_g
            y2 = max(ny[m] + h_of[m] / 2 for m in ms) + pad_g
            out.append({"id": k, "title": doc.subgraphs.get(k, k),
                        "x": round(x1, 1), "y": round(y1 - 14, 1),
                        "w": round(max(x2 - x1, float(bcfg.get("w") or 0)), 1),
                        "h": round(max(y2 - y1 + 14, float(bcfg.get("h") or 0)), 1),
                        "members": sorted(ms)})
        return out

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
            # 落到 y_of：下面层框推挤会按 y_of 重算 ny，只改 ny 会被冲掉
            y_of[("n", nid)] += float(dny)
            ny[nid] += float(dny)

    # 层框不许互相压住。分组成员散落在多个列里，只能按层框的实际外框判 —— 按列判是错的
    # （Memory / AgentCore / Verify 全在同一列 L4）。必须在端口高度算出来之前做：端口和
    # 走线都由节点坐标推出来，框后动、线不动，测试就会报端点悬空。
    if members_of:
        locked = layout.get("layer_lock") or []
        rank = layer_rank(set(members_of), between,
                          lambda gid: min(y_of[("n", m)] + layer_off(m)[1]
                                          for m in members_of[gid]))
        args = (members_of, y_of, nx, w_of, h_of, pad_g, rank, layer_off, locked, gclear)
        # 先摊同层（并排的绕主轴贴边），再解不同层（被压的整层下移）。反过来会白搬一次：
        # stack_layers 先把同层的三块串成一列长队，spread_layers 再摊回原样。
        spread_layers(*args)
        tidy_layers(*args)          # 摊开把整堆顶出画布了，拉回来（只平移，不改次序）
        if not stack_layers(members_of, y_of, nx, w_of, h_of, pad_g, rank, layer_off,
                            locked, gclear, float(layout.get("group_min_move", 24.0))):
            print("  警告：层框推挤没收敛，仍压住 —— "
                  + "、".join(group_clashes(members_of, y_of, nx, w_of, h_of, pad_g,
                                            layer_off, gclear)))
        for n in ids:                       # 换算值跟着新坐标走
            ny[n] = y_of[("n", n)] + layer_off(n)[1]
        left = group_clashes(members_of, y_of, nx, w_of, h_of, pad_g, layer_off, gclear)
        if left:
            print(f"  提示：还剩 {len(left)} 对层框压住（{'、'.join(left)}）—— "
                  "跨列的长条层不参与推挤，要解开就调 col_gap 或 layer_boxes")

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
    gap_lanes = {}                         # (目标列, 源列) -> 这条缝里已用掉几条通道

    # 层框不许互相压住。分组成员散落在多个列里，所以只能按层框的实际外框判 ——
    # 按列判是错的（Memory / AgentCore / Verify 全在同一列 L4）。
    # 分组框由成员包围盒算出，所以"整层下移"改的是成员坐标；改完要重算包围盒再判一次。
    out_y, in_y = align_ports(edges, ny, h_of, out_y, in_y,
                              layout.get("port_pitch", 13),
                              layout.get("align_max_step", 45),
                              layout.get("align_sweeps", 4))

    geo = lane_route(edges, level_of, x_of, y_of, col_w, w_of, out_y, in_y, nx)
    rects = [(nx[n] + w_of[n] / 2, ny[n] - h_of[n] / 2, w_of[n], h_of[n]) for n in ids]
    groups = build_groups()      # 成员可能动过，层框按新包围盒算

    # 声明式绕行（S10->S15 不许平穿 S11）。放在后处理之前：straighten 只并小折弯，
    # 这里绕行的竖段远大于 max_kink，不会被抹掉。
    avoid = layout.get("route_avoid") or {}
    if avoid:
        detour_route(edges, geo,
                     {n: (nx[n], ny[n] - h_of[n] / 2, nx[n] + w_of[n], ny[n] + h_of[n] / 2)
                      for n in ids},
                     avoid)

    # 反向边与同列边：端点必须落在节点框边上，不能悬在顶边外面。
    #
    # 绕行 x 按"纵向占用"分配（第一次适应）：两条边的竖段在 y 上不重叠就可以共用同一根通道，
    # 重叠了才往外让一条。以前是按跨度大小排号、每条固定 +7px —— 那条带子里挤了二十来条边，
    # 于是相邻两条只差几个像素却要并排走几百 px（实测 x=1251 / 1255 的 S17->S18 与 S20->S14
    # 并排 375px）。按占用分配之后，互不相干的边自然叠回同一根线上，图也窄了。
    # 绕行边（同列不相邻 + 真反向）共用一套竖线：按"纵向占用"分配，两条边的竖段在 y 上
    # 不重叠就共用一根线，重叠了才往外让一条 lane_pitch。
    #
    # 三条踩过的坑，都写在判据里：
    #   1. 判据必须是区间重叠，不是端点距离 —— 两条竖段完全重合时端点差为 0，
    #      用"端点差 < pitch"算冲突会把真正重合的两条漏掉（实测 S13->S28 与 S20->S14 并排 286px）。
    #   2. x 必须对齐到同一张网格。同列边和反向边各自取起点，差 1px 就错开一格，
    #      看着像两条线、其实只是平移了一像素（实测 1045 / 1046）。
    #   3. 处理顺序：先同列绕行、再反向边。反过来时反向边会先占掉本列右侧那根线，
    #      把同列绕行推到更外面（多绕 60px 且仍然重叠）。
    lanes = []                              # [(x, (y1, y2)), ...] 已占用的绕行竖段

    def lane_for(x_lo, span_y, min_gap):
        """从 x_lo 起找第一根"要么纵向不重叠、要么横向隔得开"的通道，返回 (x, 缝是否够用)。

        判据是区间重叠而不是端点距离：两条竖段完全重合时端点差为 0。
        min_gap 由调用方按这条边要跨多远给（并排走得越远，肉眼越能看出贴在一起）。
        """
        lo, hi = span_y
        x = math.ceil((x_lo - x_pad) / detour_pitch) * detour_pitch + x_pad
        far = True                             # 整段扫描里"最近的那条"离得多远
        while True:
            clash = [abs(x - xx) for xx, (a, b) in lanes
                     if abs(x - xx) < min_gap and min(hi, b) - max(lo, a) > 2]
            if not clash:
                break
            far = False
            x += detour_pitch
        lanes.append((x, span_y))
        return x, far

    def detour(idx, e, la, lb):
        nonlocal detour_tight
        ya, yb = out_y[idx], in_y[idx]
        wa, wb = w_of.get(e["src"], w), w_of.get(e["dst"], w)
        # 并排走多远才算"贴在一起"：跨得越远越明显，取纵向跨度的一半（下限一个通道宽）。
        gap = max(detour_pitch, abs(yb - ya) / 2)
        if la == lb:                       # 同列：贴本列右侧走最小圈
            x, ok = lane_for(nx[e["src"]] + max(wa, wb) + 10,
                             (min(ya, yb), max(ya, yb)), gap)
            geo[idx] = [(nx[e["src"]] + wa, ya), (x, ya), (x, yb), (nx[e["dst"]] + wa, yb)]
        else:                              # 真反向：源左出、目标右入，竖段落在列间空档
            # 起点要越过沿途各列节点框的右侧：同列绕行带就贴在那一排 x 上（实测 L4 列右边
            # 挤了七八条），反向边压上去就是"两条并排走几百 px"。
            lo = max(nx[l] + col_w.get(l, w) for l in range(lb, la + 1)) + 10
            x, ok = lane_for(lo, (min(ya, yb), max(ya, yb)), gap)
            geo[idx] = [(nx[e["src"]], ya), (x, ya), (x, yb), (nx[e["dst"]] + wb, yb)]
        if not ok:
            detour_tight += 1

    x_pad = 10.0                           # 网格原点：所有绕行竖线都对齐到这里
    detour_pitch = max(float(lane_pitch), 16.0)   # 绕行通道宽：列缝里的 lane_pitch 可以更小
    detour_tight = 0                       # 挤不下的绕行边数（要加宽就调 col_gap_extra）

    for idx, e in enumerate(edges):        # 第一轮：同列绕行先占位
        if idx in geo or level_of.get(e["src"], 0) != level_of.get(e["dst"], 0):
            continue
        ya, yb = out_y[idx], in_y[idx]
        wa, wb = w_of.get(e["src"], w), w_of.get(e["dst"], w)
        cy_a, cy_b = ny[e["src"]], ny[e["dst"]]
        ha, hb = h_of[e["src"]], h_of[e["dst"]]
        gap = (max(cy_a, cy_b) - max(ha, hb) / 2) - (min(cy_a, cy_b) + min(ha, hb) / 2)
        if gap > 26:                       # 上下相邻的走底边→顶边一条竖线，不占绕行通道
            detour(idx, e, level_of[e["src"]], level_of[e["dst"]])

    for idx, e in enumerate(edges):        # 第二轮：真反向 + 剩下的同列边
        if idx in geo:
            continue
        la, lb = level_of.get(e["src"], 0), level_of.get(e["dst"], 0)
        ya, yb = out_y[idx], in_y[idx]
        wa, wb = w_of.get(e["src"], w), w_of.get(e["dst"], w)
        if la == lb:
            cy_a, cy_b = ny[e["src"]], ny[e["dst"]]
            ha, hb = h_of[e["src"]], h_of[e["dst"]]
            cx = min(nx[e["src"]] + w_of[e["src"]] / 2, nx[e["dst"]] + w_of[e["dst"]] / 2)
            cx += (same_lanes.get(idx, 0) % 5 - 2) * 6
            geo[idx] = [(cx, cy_a + ha / 2 if cy_b > cy_a else cy_a - ha / 2),
                        (cx, cy_b - hb / 2 if cy_b > cy_a else cy_b + hb / 2)]
        else:
            detour(idx, e, la, lb)

    if detour_tight:
        print(f"  提示：{detour_tight} 条绕行边挤在一起（这一带要并排走的边太多，"
              f"加宽 col_gap_extra 或减少同列反向边）", file=sys.stderr)

    segs = [(owner, _boxed(_seg(a, b))) for owner, pts in geo.items()
            for a, b in zip(pts, pts[1:])]

    # 接点最小间距（横向密集的主因）。放在最后、按最终几何拉开：align_ports 与绕行都会
    # 把接点拉到同一高度，先拉开再对齐等于白拉；而反向边/同列边的折线在上面那段才建好。
    tight = spread_sides(geo, edges, level_of, layout.get("port_pitch", 13), ny, h_of,
                         port_order, layout.get("route_avoid") or {})
    if tight:
        print(f"  提示：{tight} 个接点仍挤在 {layout.get('port_pitch', 13)}px 以内"
              "（这一侧的框高装不下那么多接口，要解就加 node_min_height 或 row_gap）")

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
        # 画布要包住推完之后的层框，否则节点在画布里、层框在外面，页面上直接被裁掉
        # 画布要包住推完之后的层框和边，否则节点在画布里、层框在外面，页面上直接被裁掉
        "canvas": {"w": max(x_of[max(x_of, default=0)] + col_w.get(max(x_of, default=0), 0) + 120,
                            max((b["x"] + b["w"] for b in groups), default=0) + 40),
                   "h": max((height + 1) * sy + 160,
                            max((b["y"] + b["h"] for b in groups), default=0) + 40,
                            max((max(p_[1] for p_ in g_) for g_ in geo.values()),
                                default=0) + 40)},
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
                  "box_overlaps": len(clash),
                  # 层框重叠单独计一项：它是"推完还剩几对"，和框重叠不是一回事
                  "group_overlaps": len(group_clashes(members_of, y_of, nx, w_of,
                                                      h_of, pad_g, layer_off, gclear))},
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

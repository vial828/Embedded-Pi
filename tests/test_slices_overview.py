"""Guard the slice-overview diagram against style-index drift.

The diagram used to carry 133 hand-written `linkStyle` lines for 82 links: 50
indices were assigned twice, the later assignment won, and 37 solid edges
rendered orange. Nothing failed - the picture just lied. These tests make that
class of mistake loud.
"""

import re
from pathlib import Path

import pytest

DESIGN = Path(__file__).resolve().parents[1] / "agent-design"
MMD = DESIGN / "epi-dev-slices-overview.mmd"
MD = DESIGN / "epi-dev-slices-overview.md"

BLUE = "#2563EB"    # solid  -> development dependency
ORANGE = "#F97316"  # dashed -> runtime dependency

LINK = re.compile(r"^\s*(?!\)\s*$)(\S.*?)\s*(-->|-\.->)\s*(?:\|[^|]*\|)?\s*(\S.*?)\s*$")
STYLE = re.compile(r"^\s*linkStyle\s+(\d+)\s+stroke:(#[0-9A-Fa-f]{6})")


@pytest.fixture(scope="module")
def lines() -> list[str]:
    return MMD.read_text(encoding="utf-8").splitlines()


def link_kinds(lines: list[str]) -> list[str]:
    kinds = []
    for line in lines:
        if line.strip().startswith("%%"):
            continue
        match = LINK.match(line)
        if match:
            kinds.append(match.group(2))
    return kinds


def style_map(lines: list[str]) -> dict[str, str]:
    styles: dict[str, str] = {}
    for line in lines:
        match = STYLE.match(line.strip())
        if match:
            styles[match.group(1)] = match.group(2)
    return styles


def test_no_duplicate_linkstyle_index(lines):
    seen, dup = set(), []
    for line in lines:
        match = STYLE.match(line.strip())
        if match:
            if match.group(1) in seen:
                dup.append(match.group(1))
            seen.add(match.group(1))
    assert not dup, f"linkStyle 索引被重复赋值，后者覆盖前者：{dup}"


def test_every_link_is_styled(lines):
    kinds = link_kinds(lines)
    styles = style_map(lines)
    unstyled = [i for i in range(len(kinds)) if str(i) not in styles]
    assert not unstyled, f"{len(unstyled)} 条 link 没有显式配色，会退回 default：{unstyled}"


def test_colour_matches_line_style(lines):
    kinds = link_kinds(lines)
    styles = style_map(lines)
    wrong = [
        (i, kinds[i], styles.get(str(i)))
        for i in range(len(kinds))
        if styles.get(str(i)) != (ORANGE if kinds[i] == "-.->" else BLUE)
    ]
    assert not wrong, f"配色与线型不符（索引错位？）：{wrong[:5]}"


def test_legend_present(lines):
    assert any("subgraph Legend" in line for line in lines), "图例缺失"
    legend_links = link_kinds(lines[:20])
    assert legend_links == ["-->", "-.->"], "图例必须同时示范实线与虚线"


def test_markdown_block_matches_standalone_file():
    block = re.search(r"```mermaid\n(.*?)\n```", MD.read_text(encoding="utf-8"), re.S).group(1)
    assert block.strip() == MMD.read_text(encoding="utf-8").strip(), (
        "epi-dev-slices-overview.md 内嵌的图与 .mmd 不一致，改图要同时改两处"
    )

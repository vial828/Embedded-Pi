from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SECTION_RE = re.compile(r"^##\s+([A-Z0-9_]+)\s*$", re.MULTILINE)
KV_RE = re.compile(r"^-\s*([a-zA-Z0-9_\-]+):\s*(.*)$")


@dataclass
class ParsedSection:
    name: str
    content: str


def split_sections(text: str) -> list[ParsedSection]:
    matches = list(SECTION_RE.finditer(text))
    sections: list[ParsedSection] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append(ParsedSection(name=m.group(1), content=text[start:end].strip()))
    return sections


def parse_kv_block(content: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        m = KV_RE.match(line)
        if not m:
            continue
        data[m.group(1)] = m.group(2).strip()
    return data


def _split_row(line: str) -> list[str]:
    raw = line.strip()
    if not raw.startswith("|") or not raw.endswith("|"):
        return []
    return [c.strip() for c in raw[1:-1].split("|")]


def parse_table(content: str) -> tuple[list[str], list[dict[str, str]]]:
    lines = [ln.rstrip() for ln in content.splitlines() if ln.strip()]
    table_lines = [ln for ln in lines if ln.strip().startswith("|")]
    if len(table_lines) < 2:
        return [], []

    headers = _split_row(table_lines[0])
    rows: list[dict[str, str]] = []
    for line in table_lines[2:]:
        cols = _split_row(line)
        if len(cols) != len(headers):
            continue
        rows.append(dict(zip(headers, cols)))
    return headers, rows


def parse_mermaid(content: str) -> str:
    # Preferred non-rendered source block (to avoid unstable preview rendering):
    # <!-- parser-mermaid-begin
    # flowchart TB
    # ...
    # parser-mermaid-end -->
    m2 = re.search(
        r"<!--\s*parser-mermaid-begin\n(.*?)\nparser-mermaid-end\s*-->",
        content,
        flags=re.DOTALL,
    )
    if m2:
        return m2.group(1).strip()

    # Backward compatibility with fenced mermaid blocks
    m = re.search(r"```mermaid\n(.*?)\n```", content, flags=re.DOTALL)
    if not m:
        return ""
    return m.group(1).strip()


def parse_mermaid_source_file(md_path: Path) -> str:
    """Read graph source from a dedicated .mmd file (preferred for stable preview)."""
    mmd_path = md_path.parent / "layer-architecture.mmd"
    if not mmd_path.exists():
        return ""
    return mmd_path.read_text(encoding="utf-8").strip()


def parse_system_design(md_path: Path) -> dict:
    text = md_path.read_text(encoding="utf-8")
    sections = {s.name: s.content for s in split_sections(text)}

    mermaid_src = parse_mermaid_source_file(md_path) or parse_mermaid(sections.get("LAYER_ARCHITECTURE_GRAPH", ""))

    parsed: dict = {
        "sections": list(sections.keys()),
        "SCHEMA": parse_kv_block(sections.get("SCHEMA", "")),
        "AI_USAGE_CONSTRAINTS": parse_kv_block(sections.get("AI_USAGE_CONSTRAINTS", "")),
        "PROJECT_META": parse_kv_block(sections.get("PROJECT_META", "")),
        "LAYER_ARCHITECTURE_GRAPH": {"mermaid": mermaid_src},
    }

    table_sections = [
        "MODULE_DESIGN_TABLE",
        "TASK_TABLE",
        "INTERFACE_TABLE",
        "REGISTER_INIT_TABLE",
        "CLOCK_CONFIG_TABLE",
        "INTERRUPT_TABLE",
        "WATCHDOG_TABLE",
        "DEV_ENVIRONMENT",
        "TRACEABILITY_LINKS",
        "VALIDATION_STATUS",
    ]
    for sec in table_sections:
        headers, rows = parse_table(sections.get(sec, ""))
        parsed[sec] = {"headers": headers, "rows": rows}

    return parsed

"""Keep the mermaid block inside a .md identical to its standalone .mmd.

The diagram exists twice on purpose - the .mmd for tooling, the fenced block for
reading the document - so it needs one owner. Edit the .mmd, then run this.

    python tools/sync_diagram_md.py <file.mmd> <file.md>      # write
    python tools/sync_diagram_md.py <file.mmd> <file.md> --check
"""

import argparse
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):   # Windows 控制台默认 cp936/cp1252，中文会炸
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BLOCK = re.compile(r"```mermaid\n.*?\n```", re.S)


def sync(mmd: Path, md: Path, check: bool = False) -> int:
    text = mmd.read_text(encoding="utf-8").rstrip()
    body = md.read_text(encoding="utf-8")
    hits = list(BLOCK.finditer(body))
    if not hits:
        print(f"{md.name} 里没有 ```mermaid 代码块")
        return 1
    if len(hits) > 1:
        print(f"{md.name} 里有 {len(hits)} 个 mermaid 代码块，无法判断哪个对应 {mmd.name}")
        return 1
    want = "```mermaid\n" + text + "\n```"
    if hits[0].group(0) == want:
        if check:
            print(f"{md.name} 与 {mmd.name} 一致")
        return 0
    if check:
        print(f"STALE  {md.name} 内嵌图与 {mmd.name} 不一致")
        return 1
    md.write_text(body[:hits[0].start()] + want + body[hits[0].end():], encoding="utf-8")
    print(f"{md.name} 已同步自 {mmd.name}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="把 .mmd 同步进 .md 的 mermaid 代码块")
    ap.add_argument("mmd", type=Path)
    ap.add_argument("md", type=Path)
    ap.add_argument("--check", action="store_true", help="只比对，不一致返回非 0")
    a = ap.parse_args()
    return sync(a.mmd, a.md, a.check)


if __name__ == "__main__":
    sys.exit(main())

"""Make tracked pi sessions portable across machines by rewriting header cwd.

Why: pi resolves a session header's ``cwd`` against the *current* working
directory (``resolvePath`` in ``utils/paths.ts``) and hides any session whose
resolved cwd differs from where pi is running. Sessions written on Windows carry
``"C:\\Projects\\Embedded-Pi"``; on Linux that string never resolves to
``/home/vial/projects/Embedded-Pi``, so the picker drops them from the default
(current folder) view. The repo syncs ``.pi/sessions`` between machines, so the
same files keep disappearing depending on which machine opened them last.

Fix: pi treats a relative header cwd as relative to the launch directory, so
``"."`` matches on every machine. This tool rewrites headers to ``"."``.

Scope: only the header line (first line, ``type == "session"``) is touched.
Message bodies keep whatever absolute paths they recorded - those are transcript
content, not lookup keys, and rewriting them would corrupt the record.

    python tools/portable_session_cwd.py                      # report what would change
    python tools/portable_session_cwd.py --apply              # rewrite foreign headers
    python tools/portable_session_cwd.py --apply --keep-legacy # ...and this machine's too
    python tools/portable_session_cwd.py --check              # exit 1 if any needs work

By default only headers that cannot resolve here (another machine's absolute path)
are rewritten; ``--keep-legacy`` also converts this machine's own absolute paths so
both directions are portable. New sessions written by pi still get an absolute
header, so re-run after a session started on a machine whose path differs.

Safe to re-run: headers already at "." are skipped. Rewriting is atomic (temp file
plus rename) and touches only the header line, leaving every other byte - and
therefore the git diff - untouched. pi opens sessions read-only and appends at
end-of-file, so a header swap cannot lose an entry; still, avoid running it while
pi is mid-write on the same file.
"""

import argparse
import io
import json
import os
import re
import sys
from pathlib import Path

# Importable both as a script and from the pi extension in .pi/extensions/.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RELATIVE = "."


def read_header(path: Path):
    """Return (header_dict, raw_first_line) or (None, raw_first_line) if absent."""
    with io.open(path, "r", encoding="utf-8", errors="replace") as handle:
        first = handle.readline()
        if not first:
            return None, first
        try:
            obj = json.loads(first)
        except ValueError:
            return None, first
        return (obj if obj.get("type") == "session" else None), first


def is_foreign(old: str) -> bool:
    """True when the recorded cwd cannot resolve to this checkout on this machine.

    A header holding "." is portable. A header holding an absolute path resolves
    only on the machine that wrote it - which is the case --keep-legacy exists for.
    """
    return bool(old) and Path(old).is_absolute()


def rewrite(path: Path, cwd_value: str, apply: bool, keep_legacy: bool = False) -> str:
    """Returns a status tag: rewritten | would-rewrite | already | local-abs |
    no-header | no-newline | error."""
    try:
        header, first = read_header(path)
    except OSError as exc:
        print(f"  读取失败 {path.name}: {exc}")
        return "error"

    if header is None:
        return "no-header"
    if not first.endswith("\n"):
        # Header is the only line, or the file has no trailing newline: rewriting
        # in place would splice the new header onto the old content.
        return "no-newline"

    old = header.get("cwd")
    if old == cwd_value:
        return "already"
    if not keep_legacy and not is_foreign(old):
        return "local-abs"

    print(f"  {path.name[:52]}")
    print(f"    cwd: {old!r} -> {cwd_value!r}")
    if not apply:
        return "would-rewrite"

    # Replace only the header line; the remainder is copied byte for byte so a
    # rewrite shows up as a one-line change instead of a whole-file diff.
    with io.open(path, "rb") as handle:
        data = handle.read()
    header["cwd"] = cwd_value
    # Rewrite only the cwd value inside the original line, so every other field
    # keeps pi's exact bytes and the diff is the portability change alone.
    updated = re.sub(r'("cwd"\s*:\s*)"(?:[^"\\]|\\.)*"',
                     lambda m: m.group(1) + json.dumps(cwd_value), first, count=1)
    if updated == first.rstrip("\n"):
        return "already"
    new_header = updated.encode("utf-8")
    end = data.index(b"\n") + 1
    tmp = path.with_suffix(path.suffix + ".tmp")
    with io.open(tmp, "wb") as handle:
        handle.write(new_header)
        handle.write(data[end:])
    os.replace(tmp, path)
    return "rewritten"


def main() -> int:
    ap = argparse.ArgumentParser(description="把 pi 会话头部的 cwd 改成项目相对路径")
    ap.add_argument("--src", default=".pi/sessions", help="会话目录（默认 .pi/sessions）")
    ap.add_argument("--cwd", default=RELATIVE,
                    help=f"写入的 cwd 值（默认 {RELATIVE!r}，即当前项目根）")
    ap.add_argument("--apply", action="store_true", help="实际改写（默认只报告）")
    ap.add_argument("--check", action="store_true", help="只检查，有非相对 cwd 则退出码 1")
    ap.add_argument("--keep-legacy", action="store_true",
                    help="连本机绝对路径的头部一起改成相对（默认只改别机器的路径）")
    args = ap.parse_args()

    root = Path(args.src)
    if not root.is_dir():
        print(f"目录不存在：{root}")
        return 1

    files = sorted(root.glob("*.jsonl"))
    if not files:
        print(f"{root}/ 下没有会话文件")
        return 0

    mode = "--check（只报告）" if args.check else ("改写" if args.apply else "dry-run")
    print(f"扫描 {root}/（{len(files)} 个文件）  模式：{mode}")

    tally = {}
    for path in files:
        tag = rewrite(path, args.cwd, args.apply and not args.check, args.keep_legacy)
        tally[tag] = tally.get(tag, 0) + 1

    print("\n小结： " + "  ".join(f"{k}:{v}" for k, v in sorted(tally.items())))
    if args.check:
        pending = tally.get("would-rewrite", 0)
        if tally.get("local-abs"):
            print(f"提示：{tally['local-abs']} 个头部是本机绝对路径，换机器会隐形；"
                  f"加 --keep-legacy 一起改成相对")
        print("检查：" + ("全部已是相对 cwd，跨机可见" if not pending
                          else f"{pending} 个文件仍需改写（跑 --apply）"))
        return 1 if pending else 0

    if args.apply:
        print("\n完成。pi 会把相对 cwd 按启动目录解析，Windows 与 Linux 都能在项目根匹配。")
        print("提示：git add .pi/sessions 把改动同步到另一台机器。")
    else:
        print("\ndry-run：加 --apply 才实际改写。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

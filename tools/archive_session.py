"""Produce a sanitized export of pi sessions (optional).

This repo tracks live sessions under ``.pi/sessions/`` so they sync between the
owner's own machines over a private remote; that is a deliberate choice, not an
oversight. This tool is for the moments that choice does not hold - publishing a
transcript outside those machines, or keeping a shareable copy.

It is not a hand-run scan: the check runs again over the produced bytes and
refuses to write if anything still matches, so "forgot to redact" cannot happen.
The first version of this tool missed ``PI_*`` assignments entirely and reported
"clean" on a transcript that contained ``PI_VSCODE_BRIDGE_TOKEN=<value>`` - an
incomplete pattern set is a false pass, which is why verification is separate
from redaction.

    python tools/archive_session.py --src .pi/sessions --out /tmp/share
    python tools/archive_session.py --lean          # drop bulky tool output
    python tools/archive_session.py --check         # audit existing files, write nothing

Note pi has no pre-write hook, so live sessions cannot be redacted as they are
written; sanitizing after the fact leaves the value in git history. Keep the
raw transcripts private, or rewrite history if they ever leave that scope.
"""

import argparse
import glob
import io
import json
import os
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PLACEHOLDER = "‹redacted-{}›"

# Redaction rules, applied over raw file text. Values live inside JSON strings,
# so the whole match is replaced by a quote-free placeholder, which keeps every
# line valid JSON.
RULES = [
    ("env-pi", re.compile(r"\bPI_[A-Z0-9_]*(?:TOKEN|KEY|SECRET|PASSWORD|CREDENTIAL)[A-Z0-9_]*"
                          r"[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9._\-/+=]{4,}")),
    ("env-assign", re.compile(r"\b[A-Z][A-Z0-9_]{3,}(?:TOKEN|SECRET|PASSWORD|APIKEY|API_KEY)"
                              r"[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9._\-/+=]{8,}")),
    ("github-pat", re.compile(r"\b(?:github_pat|gh[pousr])_[A-Za-z0-9_]{16,}")),
    ("openai", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}")),
    ("aws-akid", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("bearer", re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=\-]{20,}")),
    ("auth-header", re.compile(r"(?i)(?:authorization|x-api-key|x-goog-api-key|access_token)"
                               r"[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9._~+/=\-]{12,}")),
    ("url-creds", re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@\"]{1,64}:[^/\s@\"]{3,}@")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")),
    ("pem-block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
                             re.S)),
]

# Verification-only patterns. These deliberately require an actual secret-shaped
# payload, so prose that merely names a variable ("PI_VSCODE_BRIDGE_TOKEN=<值>")
# or quotes a PEM header still archives - but anything with a value does not.
VERIFY_ONLY = [
    ("any-secret-assignment",
     re.compile(r"\b[A-Za-z][A-Za-z0-9_]{4,}(?:TOKEN|SECRET|PASSWORD|APIKEY|API_KEY|CREDENTIAL)"
                r"[A-Za-z0-9_]*[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9._\-/+=]{12,}")),
    ("pem-with-body",
     re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[^\n]*\n\s*[A-Za-z0-9+/=]{30,}")),
    ("credential-in-url",
     re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@\"]{1,64}:[^/\s@\"]{3,}@", re.IGNORECASE)),
]


def redact(text: str):
    """Apply every rule. Returns (new_text, {rule_name: hit_count})."""
    counts = {}
    for name, pattern in RULES:
        text, n = pattern.subn(PLACEHOLDER.format(name), text)
        if n:
            counts[name] = n
    return text, counts


def verify(text: str):
    """Post-redaction gate. Returns a list of remaining problems (empty = ok)."""
    problems = [name for name, pattern in RULES if pattern.search(text)]
    problems += [name for name, pattern in VERIFY_ONLY if pattern.search(text)]
    return problems


def last_complete_line(data: bytes) -> bytes:
    """A live session is being appended to; never archive a half-written line."""
    cut = data.rfind(b"\n")
    return data[:cut + 1] if cut != -1 and cut + 1 != len(data) else data


def lean(line: str, limit: int = 400) -> str:
    """Shorten bulky toolResult payloads, keeping the entry valid JSON."""
    try:
        obj = json.loads(line)
    except ValueError:
        return line

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, str) and len(v) > limit:
                    node[k] = v[:limit] + f"‹dropped {len(v) - limit} chars›"
                else:
                    walk(v)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                if isinstance(v, str) and len(v) > limit:
                    node[i] = v[:limit] + f"‹dropped {len(v) - limit} chars›"
                else:
                    walk(v)

    walk(obj.get("message", obj))
    return json.dumps(obj, ensure_ascii=False)


def sources(spec: str):
    p = Path(spec).expanduser()
    if p.is_dir():
        return sorted(p.rglob("*.jsonl"))
    if p.is_file():
        return [p]
    return [Path(x) for x in sorted(glob.glob(spec, recursive=True))]


def main() -> int:
    ap = argparse.ArgumentParser(description="脱敏并归档 pi 会话到仓库")
    ap.add_argument("--src", default=".pi/sessions", help="会话文件或目录（默认项目内会话目录）")
    ap.add_argument("--out", default=".pi/sessions-export", help="导出目录（默认不入库）")
    ap.add_argument("--lean", action="store_true", help="截短大块工具输出，只留对话与调用意图")
    ap.add_argument("--check", action="store_true", help="只校验既有归档，不写文件")
    args = ap.parse_args()

    if args.check:
        bad = []
        for f in sorted(Path(args.out).rglob("*.jsonl")):
            problems = verify(io.open(f, encoding="utf-8", errors="replace").read())
            print(f"{f.name[:40]}…  {'干净' if not problems else '★ 仍含凭据: ' + str(problems)}")
            if problems:
                bad.append(f)
        print(f"\n校验 {len(list(Path(args.out).rglob('*.jsonl')))} 个文件，"
              f"{'全部通过' if not bad else str(len(bad)) + ' 个不合格'}")
        return 1 if bad else 0

    files = sources(args.src)
    if not files:
        print(f"没有找到会话：{args.src}")
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for src in files:
        text = last_complete_line(io.open(src, "rb").read()).decode("utf-8", errors="replace")
        before = len(text)
        if args.lean:
            text = "".join(lean(line) + "\n" for line in text.splitlines())
        text, counts = redact(text)
        problems = verify(text)
        if problems:
            print(f"拒绝写入 {src.name}：脱敏后仍检出 {problems}")
            print("  → 补 RULES / VERIFY_ONLY 再跑。宁可不出档，也不能把凭据推上去。")
            return 1
        dst = out_dir / src.name
        io.open(dst, "w", encoding="utf-8", newline="").write(text)
        stats = " ".join(f"{k}:{v}" for k, v in sorted(counts.items())) or "无需脱敏"
        print(f"{dst.name[:34]}…  {before:>9} → {len(text):>9} 字节   脱敏 {stats}")

    print(f"\n归档 {len(files)} 个文件 → {out_dir}/  "
          f"{'(lean：已截短工具输出)' if args.lean else '(全量，已脱敏)'}")
    print("校验：脱敏后二次扫描通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

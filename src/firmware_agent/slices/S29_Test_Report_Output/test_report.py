"""S29 - Test report output (minimal): verdicts + declared requirement links.

Two things happen here and nothing else: the verifiers' verdicts are laid out,
and the requirement links that **test authors declared** are joined to those
verdicts. The join is a lookup, never an inference - `semantic_inference:
forbidden` in the design constitution applies to this file in particular, since
a report is exactly where a guessed link would look like a fact.

## The link declaration

```c
/* requires: R-001, R-004 */
```

A test states which requirements it covers. It lives in the test file so the link
moves with the code, and it is a comment so the compiler ignores it.

Three rules follow from "a report must not invent coverage":

1. **A malformed link is reported, never dropped.** `// requires: R-1` or a typo
   becomes an entry in `malformed_links`; ignoring it would turn a broken trace
   into a clean report.
2. **A link to an unknown requirement is a broken trace**, listed in
   `unknown_ids`. Requirement IDs come from the S09 index, so a renumbered PRD
   shows up here instead of silently pointing at the wrong row.
3. **No requirement index means traceability is `not-evaluated`**, which is not
   the same as `complete`. A missing input must never render as zero problems.

The markdown is rendered from the same dictionary as the JSON, so the two cannot
disagree, and neither carries a wall-clock timestamp: the same inputs produce a
byte-identical report.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

__all__ = ["REQUIREMENTS_INDEX_RELATIVE", "build_report", "extract_requires_links", "write_report"]

REQUIREMENTS_INDEX_RELATIVE = "Docs/ai-generation/knowledge/requirements_index.json"
REPORT_RELATIVE = "Docs/ai-generation/reports"
SCHEMA = "epi.test-report/1"

# A declaration is a comment, so it cannot change what the program does.
_REQUIRES_RE = re.compile(r"(?://|/\*)\s*requires\s*:\s*([^*\n]+?)\s*(?:\*/)?\s*$", re.IGNORECASE | re.MULTILINE)
_REQ_ID_RE = re.compile(r"^R-\d{3,}$")
_TEST_SUFFIX = "_test.c"

# Stages that judge the whole build cannot be attributed to one requirement.
WHOLE_PROJECT = "n/a (whole-project gate)"


def extract_requires_links(project_root: Path) -> list[dict[str, Any]]:
    """Read `requires:` declarations from every test source, in path order."""
    links: list[dict[str, Any]] = []
    tests_dir = project_root / "tests"
    if not tests_dir.exists():
        return links

    for test in sorted(tests_dir.rglob(f"*{_TEST_SUFFIX}")):
        rel = str(test.relative_to(project_root)).replace("\\", "/")
        text = test.read_text(encoding="utf-8", errors="replace")
        for match in _REQUIRES_RE.finditer(text):
            for token in re.split(r"[,\s]+", match.group(1).strip()):
                if not token:
                    continue
                entry = {"file": rel, "declared": token}
                if _REQ_ID_RE.match(token):
                    entry["req_id"] = token
                else:
                    entry["req_id"] = None
                    entry["malformed"] = True
                links.append(entry)
    return links


def _load_requirements(project_root: Path) -> tuple[list[dict[str, Any]], str | None]:
    path = project_root / REQUIREMENTS_INDEX_RELATIVE
    if not path.exists():
        return [], f"{REQUIREMENTS_INDEX_RELATIVE} does not exist - PRD not ingested"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [], f"{REQUIREMENTS_INDEX_RELATIVE} is not valid JSON: {error}"

    requirements = payload.get("requirements", [])
    if not requirements:
        # S02 scaffolds an index with an empty list, so "present" is not "ingested".
        # Reading that as complete coverage of zero requirements would be a vacuous
        # truth, and vacuous truths are how reports lie.
        return [], f"{REQUIREMENTS_INDEX_RELATIVE} lists no requirements - PRD not ingested"
    return requirements, None


def build_report(project_root: Path, verdicts: dict[str, Any]) -> dict[str, Any]:
    """Assemble the report dictionary. Deterministic: same inputs, same bytes."""
    requirements, unavailable_reason = _load_requirements(project_root)
    known_ids = {item.get("req_id") for item in requirements}
    links = extract_requires_links(project_root)

    malformed = [link for link in links if link.get("malformed")]
    unknown = [link for link in links if link.get("req_id") and link["req_id"] not in known_ids]
    by_requirement: dict[str, list[str]] = {}
    for link in links:
        if link.get("req_id") and link["req_id"] in known_ids:
            by_requirement.setdefault(link["req_id"], []).append(link["file"])

    cases = [
        {**case, "requires": sorted({l["req_id"] for l in links if l["file"] == case["file"] and l.get("req_id")})}
        for stage, result in verdicts.items()
        for case in ({"stage": stage, **c} for c in result.cases)
    ]

    failed = sorted(name for name, result in verdicts.items() if not result.passed and not result.stub)
    stubs = sorted(name for name, result in verdicts.items() if result.stub)

    return {
        "schema": SCHEMA,
        "overall": "FAILED" if failed else "PASSED",
        "overall_note": _overall_note(failed, stubs),
        "failed_stages": failed,
        "stub_stages": stubs,
        "stages": [
            {
                "name": name,
                "verdict": "NO_EVIDENCE" if result.stub else ("PASS" if result.passed else "FAIL"),
                "tool": result.tool or "n/a",
                "duration_ms": result.duration_ms,
                "requirements": WHOLE_PROJECT,
                "commands": result.commands,
                "output": result.output,
            }
            for name, result in verdicts.items()
        ],
        "test_cases": cases,
        "requirements": [
            {
                "req_id": item.get("req_id"),
                "title": item.get("title", ""),
                "tests": sorted(set(by_requirement.get(item.get("req_id"), []))),
                "status": "covered" if by_requirement.get(item.get("req_id")) else "untested",
            }
            for item in requirements
        ],
        "traceability": _traceability(links, malformed, unknown, requirements, unavailable_reason),
    }


def _overall_note(failed: list[str], stubs: list[str]) -> str:
    """Say what qualifies the headline, without softening it.

    "Failed (with unverified stages)" would bury the failure under a footnote, so
    a failure names the stages and the stub note only qualifies a pass.
    """
    if failed:
        return f"{len(failed)} stage(s) failed: {', '.join(failed)}"
    if stubs:
        return f"passed with unverified stages: {', '.join(stubs)}"
    return "all stages produced evidence"


def _traceability(
    links: list[dict],
    malformed: list[dict],
    unknown: list[dict],
    requirements: list[dict],
    unavailable_reason: str | None,
) -> dict[str, Any]:
    if unavailable_reason:
        # Not the same as "no problems": nothing could be checked.
        return {"status": "not-evaluated", "reason": unavailable_reason, "declared_links": len(links)}

    untested = sorted(item["req_id"] for item in requirements if not any(l.get("req_id") == item["req_id"] for l in links))
    return {
        "status": "broken" if malformed or unknown else "complete",
        "declared_links": len(links),
        "requirements_total": len(requirements),
        "requirements_untested": untested,
        "malformed_links": [{"file": l["file"], "declared": l["declared"]} for l in malformed],
        "unknown_ids": [{"file": l["file"], "req_id": l["req_id"]} for l in unknown],
    }


def write_report(project_root: Path, report: dict[str, Any]) -> dict[str, Path]:
    directory = project_root / REPORT_RELATIVE
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "test_report.json"
    markdown_path = directory / "test_report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    markdown_path.write_text(render_markdown(report), encoding="utf-8", newline="\n")
    return {"json": json_path, "markdown": markdown_path}


def render_markdown(report: dict[str, Any]) -> str:
    trace = report["traceability"]
    lines = [
        "# Test report",
        "",
        f"**Overall: {report['overall']}** ({report['overall_note']})",
        "",
        f"- Failed stages: {', '.join(report['failed_stages']) or 'none'}",
        f"- No evidence (stub): {', '.join(report['stub_stages']) or 'none'}",
        f"- Traceability: {trace['status']}",
        "",
        "| stage | verdict | tool | requirements |",
        "|---|---|---|---|",
    ]
    for stage in report["stages"]:
        lines.append(f"| {stage['name']} | {stage['verdict']} | {stage['tool']} | {stage['requirements']} |")

    lines += ["", "## Test cases", ""]
    if report["test_cases"]:
        lines += ["| file | verdict | requires |", "|---|---|---|"]
        for case in report["test_cases"]:
            lines.append(f"| {case['file']} | {case['verdict']} | {', '.join(case['requires']) or 'none declared'} |")
    else:
        lines.append("No test case produced a verdict.")

    lines += ["", "## Requirement coverage", ""]
    if report["requirements"]:
        lines += ["| requirement | status | tests |", "|---|---|---|"]
        for item in report["requirements"]:
            lines.append(f"| {item['req_id']} | {item['status']} | {', '.join(item['tests']) or '-'} |")
    else:
        lines.append(f"No requirements: {trace.get('reason', 'index empty')}.")

    lines += ["", "## Traceability detail", ""]
    if trace["status"] == "not-evaluated":
        lines.append(f"- not evaluated: {trace['reason']}")
    else:
        untested = trace["requirements_untested"]
        lines += [
            f"- declared links: {trace['declared_links']}",
            f"- untested requirements: {len(untested)} of {trace['requirements_total']}"
            + (f" ({', '.join(untested)})" if untested else ""),
            f"- malformed links: {len(trace['malformed_links'])}"
            + "".join(f"\n  - {m['file']} declared `{m['declared']}`" for m in trace["malformed_links"]),
            f"- unknown requirement ids: {len(trace['unknown_ids'])}"
            + "".join(f"\n  - {u['file']} declared `{u['req_id']}`" for u in trace["unknown_ids"]),
        ]

    lines += ["", "## Stage output", ""]
    for stage in report["stages"]:
        lines += [f"### {stage['name']} - {stage['verdict']}", ""]
        for command in stage["commands"]:
            lines.append(f"    $ {command}")
        if stage["output"]:
            lines += ["", "```", stage["output"], "```"]
        lines.append("")

    return "\n".join(lines)

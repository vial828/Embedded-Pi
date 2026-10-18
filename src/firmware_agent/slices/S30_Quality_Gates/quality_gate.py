"""S30 - Quality gates: decide certification from the report, not from a new opinion.

The gate consumes the S29 report dictionary. That is deliberate: if the gate
recomputed its own facts it could disagree with the report beside it, and a
reviewer would have no way to tell which one was lying.

## Rules

| Rule | Rejects when |
|---|---|
| `no-stub-participation` | any stage produced no evidence (stub) |
| `no-failed-stage` | any stage failed |
| `traceability-complete` | a trace link is malformed or unknown, **or** traceability was not evaluated |
| `requirement-coverage` | coverage below `gate.min_requirement_coverage` - only when configured |

`no-stub-participation` is the headline rule of this project: a run where a
verifier was a stub cannot be certified, no matter how green the other stages
look. A stub is not a weak pass, it is an absence of evidence, and absences are
what audits exist to catch.

## What rejection does *not* mean

`rejected` means **this run may not be certified**, not **stop the pipeline**.
The distinction matters because S23 is a stub today: if rejection blocked the
workflow, the only way to finish a run would be to remove the gate - which is
exactly the pressure that turns gates into decoration. Instead the verdict is
recorded (`state.json`, `quality_gate.json`) so CI (S31) and humans fail on it,
while work can still proceed and be inspected.

A rule that could not be judged is reported under `not_judged` with the reason.
It is never counted as satisfied: an unjudgeable rule that reads as a pass is the
same failure as a stub that reports success.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["GATE_RESULT_RELATIVE", "GateVerdict", "evaluate", "write_gate_result"]

GATE_RESULT_RELATIVE = "Docs/ai-generation/reports/quality_gate.json"


@dataclass(frozen=True)
class GateVerdict:
    verdict: str  # accepted | rejected
    reasons: list[dict[str, Any]] = field(default_factory=list)
    not_judged: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def accepted(self) -> bool:
        return self.verdict == "accepted"

    @property
    def rule_names(self) -> list[str]:
        return [reason["rule"] for reason in self.reasons]


def evaluate(report: dict[str, Any], *, min_requirement_coverage: float | None = None) -> GateVerdict:
    """Judge a report. Pure: no files, no clock, no environment."""
    reasons: list[dict[str, Any]] = []
    not_judged: list[dict[str, Any]] = []

    stubs = list(report["stub_stages"])
    if stubs:
        reasons.append(
            {
                "rule": "no-stub-participation",
                "detail": f"no evidence from: {', '.join(stubs)} - a stub is an absence of evidence, not a pass",
            }
        )

    failed = list(report["failed_stages"])
    if failed:
        reasons.append({"rule": "no-failed-stage", "detail": f"failed stages: {', '.join(failed)}"})

    trace = report["traceability"]
    if trace["status"] == "not-evaluated":
        reasons.append({"rule": "traceability-complete", "detail": f"traceability not evaluated: {trace['reason']}"})
    elif trace["status"] != "complete":
        reasons.append(
            {
                "rule": "traceability-complete",
                "detail": f"{len(trace['malformed_links'])} malformed link(s), "
                f"{len(trace['unknown_ids'])} unknown requirement id(s)",
            }
        )

    coverage = _coverage(report)
    if min_requirement_coverage is None:
        not_judged.append(
            {
                "rule": "requirement-coverage",
                "reason": "gate.min_requirement_coverage is not set - reported as not-configured, not as satisfied",
            }
        )
    elif coverage is None:
        not_judged.append({"rule": "requirement-coverage", "reason": "no requirements to measure"})
    elif coverage < min_requirement_coverage:
        reasons.append(
            {
                "rule": "requirement-coverage",
                "detail": f"coverage {coverage:.2f} is below the configured {min_requirement_coverage:.2f}",
            }
        )

    return GateVerdict(
        verdict="rejected" if reasons else "accepted",
        reasons=reasons,
        not_judged=not_judged,
        metrics={
            "stages_total": len(report["stages"]),
            "failed_stages": failed,
            "stub_stages": stubs,
            "traceability": trace["status"],
            "requirement_coverage": coverage,
            "min_requirement_coverage": min_requirement_coverage,
        },
    )


def _coverage(report: dict[str, Any]) -> float | None:
    total = len(report["requirements"])
    if not total:
        return None
    covered = sum(1 for item in report["requirements"] if item["status"] == "covered")
    return covered / total


def write_gate_result(project_root: Path, verdict: GateVerdict, report: dict[str, Any]) -> Path:
    """Persist the verdict next to the report it judged, with a pointer to it."""
    path = project_root / GATE_RESULT_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "epi.quality-gate/1",
        "judged_report": "Docs/ai-generation/reports/test_report.json",
        "judged_overall": report["overall"],
        **asdict(verdict),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return path

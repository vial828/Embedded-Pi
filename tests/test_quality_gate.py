"""P0-9: S30 quality gate. The rule under test: a stub in the run means no certification."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from firmware_agent.project_layout import ensure_project_layout
from firmware_agent.slices.S30_Quality_Gates.quality_gate import (
    GATE_RESULT_RELATIVE,
    evaluate,
    write_gate_result,
)

# The gate is a pure judgement over the S29 report, so the honest test input is a
# report dictionary. Building one here keeps the rules readable and the tests
# independent of how a report got made.
CLEAN_REPORT = {
    "overall": "PASSED",
    "overall_note": "all stages produced evidence",
    "failed_stages": [],
    "stub_stages": [],
    "stages": [{"name": "compile", "verdict": "PASS", "requirements": "n/a (whole-project gate)"}],
    "test_cases": [{"file": "tests/crc_test.c", "verdict": "PASS", "requires": ["R-001"]}],
    "requirements": [{"req_id": "R-001", "title": "CRC", "tests": ["tests/crc_test.c"], "status": "covered"}],
    "traceability": {
        "status": "complete",
        "declared_links": 1,
        "requirements_total": 1,
        "requirements_untested": [],
        "malformed_links": [],
        "unknown_ids": [],
    },
    "design_coverage": {
        "status": "complete",
        "reason": "",
        "requirements_total": 1,
        "assigned": {"R-001": ["module:MOD-001"]},
        "unassigned": [],
        "unknown_refs": [],
        "placeholder_rows": 0,
    },
}


def report(**overrides) -> dict:
    built = copy.deepcopy(CLEAN_REPORT)
    built.update(overrides)
    return built


def with_stage(name: str, verdict: str) -> dict:
    built = report()
    built["stages"].append({"name": name, "verdict": verdict, "requirements": "n/a (whole-project gate)"})
    if verdict == "NO_EVIDENCE":
        built["stub_stages"] = [name]
        built["overall"] = "PASSED"
    else:
        built["failed_stages"] = [name]
        built["overall"] = "FAILED"
    return built


# ------------------------------------------------------------------- verdicts


def test_a_stub_in_the_run_denies_certification() -> None:
    verdict = evaluate(with_stage("static-analysis", "NO_EVIDENCE"))

    assert verdict.verdict == "rejected"
    assert verdict.rule_names == ["no-stub-participation"]
    assert "static-analysis" in verdict.reasons[0]["detail"]


def test_a_failed_stage_denies_certification() -> None:
    verdict = evaluate(with_stage("compile", "FAIL"))

    assert verdict.verdict == "rejected"
    assert verdict.rule_names == ["no-failed-stage"]


def test_evidence_without_stubs_is_accepted() -> None:
    verdict = evaluate(report())

    assert verdict.accepted is True
    assert verdict.reasons == []


def test_unevaluated_traceability_is_a_rejection_not_an_absence_of_problem() -> None:
    verdict = evaluate(
        report(traceability={"status": "not-evaluated", "reason": "PRD not ingested", "declared_links": 0})
    )

    assert verdict.verdict == "rejected"
    assert verdict.rule_names == ["traceability-complete"]
    assert "PRD not ingested" in verdict.reasons[0]["detail"]


@pytest.mark.parametrize(
    ("malformed", "unknown"),
    [([{"file": "a.c", "declared": "R-1"}], []), ([], [{"file": "a.c", "req_id": "R-999"}])],
)
def test_a_broken_trace_denies_certification(malformed: list, unknown: list) -> None:
    verdict = evaluate(
        report(
            traceability={
                "status": "broken",
                "declared_links": 1,
                "requirements_total": 1,
                "requirements_untested": [],
                "malformed_links": malformed,
                "unknown_ids": unknown,
            }
        )
    )

    assert verdict.verdict == "rejected"
    assert verdict.rule_names == ["traceability-complete"]


# -------------------------------------------------------- architecture coverage


def test_unmapped_requirements_deny_certification() -> None:
    verdict = evaluate(
        report(
            design_coverage={
                "status": "incomplete",
                "reason": "",
                "requirements_total": 2,
                "assigned": {"R-001": ["module:MOD-001"]},
                "unassigned": ["R-002"],
                "unknown_refs": [],
            }
        )
    )

    assert verdict.verdict == "rejected"
    assert "R-002" in verdict.reasons[0]["detail"]


def test_unevaluated_architecture_coverage_denies_certification() -> None:
    verdict = evaluate(report(design_coverage={"status": "not-evaluated", "reason": "still the generated template"}))

    assert verdict.rule_names == ["architecture-coverage"]
    assert "still the generated template" in verdict.reasons[0]["detail"]


def test_a_report_without_a_coverage_section_is_not_a_pass() -> None:
    built = report()
    del built["design_coverage"]

    verdict = evaluate(built)

    assert verdict.verdict == "rejected"
    assert "no design coverage section" in verdict.reasons[0]["detail"]


def test_broken_design_references_are_named_in_the_reason() -> None:
    verdict = evaluate(
        report(
            design_coverage={
                "status": "incomplete",
                "requirements_total": 1,
                "assigned": {},
                "unassigned": ["R-001"],
                "unknown_refs": [{"section": "MODULE_DESIGN_TABLE", "claimant": "module:MOD-001", "declared": "R-999"}],
            }
        )
    )

    assert "1 broken design reference(s)" in verdict.reasons[0]["detail"]


# ------------------------------------------------------------------- coverage


def test_an_unconfigured_coverage_rule_is_reported_not_satisfied() -> None:
    verdict = evaluate(report(), min_requirement_coverage=None)

    assert [item["rule"] for item in verdict.not_judged] == ["requirement-coverage"]
    assert "not-configured" in verdict.not_judged[0]["reason"]
    assert verdict.accepted is True, "an unjudged rule must not be a rejection either - it is simply not judged"


def test_coverage_below_the_configured_bar_denies_certification() -> None:
    verdict = evaluate(
        report(
            requirements=[
                {"req_id": "R-001", "status": "covered"},
                {"req_id": "R-002", "status": "untested"},
            ]
        ),
        min_requirement_coverage=1.0,
    )

    assert verdict.verdict == "rejected"
    assert "requirement-coverage" in verdict.rule_names
    assert verdict.metrics["requirement_coverage"] == 0.5


def test_coverage_at_the_bar_is_accepted() -> None:
    assert evaluate(report(), min_requirement_coverage=1.0).accepted is True


def test_the_gate_judges_only_the_report_it_was_given() -> None:
    """Purity: no files, no clock - otherwise the gate could disagree with its report."""
    before = json.dumps(CLEAN_REPORT, sort_keys=True)

    evaluate(report())

    assert json.dumps(CLEAN_REPORT, sort_keys=True) == before


# ---------------------------------------------------------------- persistence


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    ensure_project_layout(root)
    return root


def test_the_verdict_points_at_the_report_it_judged(project: Path) -> None:
    built = report()

    path = write_gate_result(project, evaluate(built), built)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path == project / GATE_RESULT_RELATIVE
    assert payload["judged_report"] == "Docs/ai-generation/reports/test_report.json"
    assert payload["judged_overall"] == "PASSED"
    assert payload["verdict"] == "accepted"


def test_a_rejection_is_persisted_with_its_reasons(project: Path) -> None:
    built = with_stage("static-analysis", "NO_EVIDENCE")

    path = write_gate_result(project, evaluate(built), built)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["verdict"] == "rejected"
    assert payload["reasons"][0]["rule"] == "no-stub-participation"


def test_the_same_report_yields_the_same_bytes(project: Path) -> None:
    built = report()

    first = write_gate_result(project, evaluate(built), built).read_bytes()
    second = write_gate_result(project, evaluate(copy.deepcopy(built)), built).read_bytes()

    assert first == second

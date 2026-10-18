"""P0-3 (partial): requirement -> module coverage. Source-agnostic rules, so they survive the A/B/C ruling."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from firmware_agent.project_layout import ensure_project_layout
from firmware_agent.slices.S04_System_Design_Generation.requirement_coverage import (
    SYSTEM_DESIGN_RELATIVE,
    check_project,
    evaluate_coverage,
)

REQUIREMENTS = [{"req_id": "R-001"}, {"req_id": "R-002"}]


# `parse_table` yields one dict per row keyed by header, so the fixtures do too.
MODULE_HEADERS = ["module_id", "layer", "name", "responsibility", "input_if", "output_if", "depends_on", "req_ids"]
TASK_HEADERS = ["task_id", "name", "period_ms", "priority", "stack_bytes", "core_affinity", "entry_fn", "req_ids"]
INTERFACE_HEADERS = ["if_id", "provider", "consumer", "type", "name", "direction", "payload", "timing", "req_ids"]


def design(modules: list[dict], tasks: list[dict] | None = None) -> dict:
    return {
        "MODULE_DESIGN_TABLE": {"headers": MODULE_HEADERS, "rows": modules},
        "TASK_TABLE": {"headers": TASK_HEADERS, "rows": tasks or []},
        "INTERFACE_TABLE": {"headers": INTERFACE_HEADERS, "rows": []},
    }


def module(mid: str, name: str, req_ids: str) -> dict:
    return dict(zip(MODULE_HEADERS, [mid, "app", name, "does work", "in", "out", "none", req_ids]))


def task(tid: str, name: str, req_ids: str) -> dict:
    return dict(zip(TASK_HEADERS, [tid, name, "10", "1", "512", "core0", "task_main", req_ids]))


# ------------------------------------------------------------------- the join


def test_every_claimed_requirement_is_complete() -> None:
    coverage = evaluate_coverage(REQUIREMENTS, design([module("MOD-001", "crc", "R-001"), module("MOD-002", "uart", "R-002")]))

    assert coverage.status == "complete"
    assert coverage.unassigned == []


def test_an_unclaimed_requirement_is_listed_not_quietly_dropped() -> None:
    coverage = evaluate_coverage(REQUIREMENTS, design([module("MOD-001", "crc", "R-001")]))

    assert coverage.status == "incomplete"
    assert coverage.unassigned == ["R-002"]


def test_a_requirement_may_be_claimed_by_several_artifacts() -> None:
    coverage = evaluate_coverage(
        REQUIREMENTS,
        design([module("MOD-001", "crc", "R-001")], tasks=[task("TSK-001", "main", "R-001, R-002")]),
    )

    assert coverage.assigned["R-001"] == ["module:MOD-001", "task:TSK-001"]
    assert coverage.status == "complete"


# ------------------------------------------------------- scaffold and N/A rules


def test_a_scaffold_row_is_not_an_assignment() -> None:
    """The generated template row says `name = N/A` and cites a sample requirement."""
    coverage = evaluate_coverage(REQUIREMENTS, design([module("MOD-001", "N/A", "R-001")]))

    assert coverage.placeholder_rows == 1
    assert coverage.unassigned == ["R-001", "R-002"], "a design nobody reviewed cannot cover anything"
    assert "scaffold" in coverage.reason


def test_na_in_a_req_ids_cell_claims_nothing() -> None:
    coverage = evaluate_coverage(REQUIREMENTS, design([module("MOD-001", "crc", "N/A")]))

    assert coverage.assigned == {}
    assert coverage.unknown_refs == [], "N/A is the constitution's value for unknown, not a bad reference"


def test_no_requirements_is_not_full_coverage() -> None:
    coverage = evaluate_coverage([], design([module("MOD-001", "crc", "R-001")]))

    assert coverage.status == "not-evaluated"
    assert "PRD not ingested" in coverage.reason


# --------------------------------------------------------------- broken traces


def test_an_unknown_requirement_id_is_a_broken_trace() -> None:
    coverage = evaluate_coverage(REQUIREMENTS, design([module("MOD-001", "crc", "R-001"), module("MOD-002", "uart", "R-999")]))

    assert coverage.status == "incomplete"
    assert coverage.unknown_refs == [
        {"section": "MODULE_DESIGN_TABLE", "claimant": "module:MOD-002", "declared": "R-999", "problem": "unknown requirement id"}
    ]


def test_a_malformed_requirement_id_is_reported_not_normalized() -> None:
    coverage = evaluate_coverage(REQUIREMENTS, design([module("MOD-001", "crc", "R-1")]))

    assert coverage.unknown_refs[0]["problem"] == "malformed requirement id"
    assert coverage.unknown_refs[0]["declared"] == "R-1"


def test_a_table_without_the_req_ids_column_is_itself_a_finding() -> None:
    broken = design([module("MOD-001", "crc", "R-001")])
    broken["MODULE_DESIGN_TABLE"]["headers"] = ["module_id", "name"]

    coverage = evaluate_coverage(REQUIREMENTS, broken)

    assert {"section": "MODULE_DESIGN_TABLE", "problem": "table has no req_ids column"} in coverage.unknown_refs


# ------------------------------------------------------------------ the adapter


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    ensure_project_layout(root)
    return root


def test_the_adapter_refuses_to_judge_before_the_prd_is_ingested(project: Path) -> None:
    coverage = check_project(project)

    assert coverage.status == "not-evaluated"
    assert "requirements_index.json" in coverage.reason


def test_an_untouched_design_template_is_not_judged(project: Path) -> None:
    """The template's example rows look real (IF-001 / sensor_q), so only byte-identity
    against the generated template can tell a scaffold from a design."""
    index = project / "Docs/ai-generation/knowledge/requirements_index.json"
    index.write_text(json.dumps({"requirements": [{"req_id": "R-001", "title": "CRC"}]}), encoding="utf-8")

    coverage = check_project(project)

    assert coverage.status == "not-evaluated"
    assert "still the generated template" in coverage.reason


def test_a_partially_filled_design_still_reports_scaffold_rows(project: Path) -> None:
    index = project / "Docs/ai-generation/knowledge/requirements_index.json"
    index.write_text(json.dumps({"requirements": [{"req_id": "R-001"}, {"req_id": "R-002"}]}), encoding="utf-8")
    design_path = project / SYSTEM_DESIGN_RELATIVE
    design_path.write_text(
        design_path.read_text(encoding="utf-8").replace(
            "| IF-001 | MOD-001 | TASK-001 | queue | sensor_q | in | N/A | 10ms | R-001 |",
            "| IF-001 | MOD-001 | TASK-001 | queue | sensor_q | in | crc_t | 10ms | R-001 |",
        ),
        encoding="utf-8",
    )

    coverage = check_project(project)

    assert coverage.status == "incomplete"
    assert coverage.unassigned == ["R-002"]
    assert coverage.placeholder_rows >= 1, "the untouched MOD row must claim nothing"
    assert coverage.assigned == {"R-001": ["interface:IF-001"]}


def test_a_reviewed_design_closes_the_trace(project: Path) -> None:
    index = project / "Docs/ai-generation/knowledge/requirements_index.json"
    index.write_text(json.dumps({"requirements": [{"req_id": "R-001", "title": "CRC"}]}), encoding="utf-8")
    design_path = project / SYSTEM_DESIGN_RELATIVE
    design_path.write_text(
        design_path.read_text(encoding="utf-8").replace("| MOD-001 | module | N/A | N/A | N/A | N/A | N/A | R-001 |",
                                                          "| MOD-001 | module | crc | checksum | spi_in | crc_out | none | R-001 |"),
        encoding="utf-8",
    )

    assert check_project(project).status == "complete"


def test_the_adapter_reports_a_missing_design_document(project: Path) -> None:
    index = project / "Docs/ai-generation/knowledge/requirements_index.json"
    index.write_text(json.dumps({"requirements": [{"req_id": "R-001"}]}), encoding="utf-8")
    (project / SYSTEM_DESIGN_RELATIVE).unlink()

    coverage = check_project(project)

    assert coverage.status == "not-evaluated"
    assert SYSTEM_DESIGN_RELATIVE in coverage.reason


def test_the_output_is_serialisable_and_stable() -> None:
    built = evaluate_coverage(REQUIREMENTS, design([module("MOD-002", "uart", "R-002"), module("MOD-001", "crc", "R-001")]))

    assert json.dumps(built.as_dict(), sort_keys=True) == json.dumps(
        evaluate_coverage(REQUIREMENTS, design([module("MOD-001", "crc", "R-001"), module("MOD-002", "uart", "R-002")])).as_dict(),
        sort_keys=True,
    )
    assert built.as_dict()["schema"] == "epi.requirement-coverage/1"

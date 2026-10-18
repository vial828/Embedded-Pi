"""P0-8: S29 report. The rule under test: a report may not invent coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from firmware_agent.project_layout import ensure_project_layout
from firmware_agent.slices.S22_Compiler_Verifier.compiler_verifier import VerifyResult
from firmware_agent.slices.S29_Test_Report_Output.test_report import (
    REQUIREMENTS_INDEX_RELATIVE,
    WHOLE_PROJECT,
    build_report,
    render_markdown,
    write_report,
)

REQUIREMENTS = {
    "version": "0.1",
    "requirements": [
        {"req_id": "R-001", "title": "Bootloader verifies CRC"},
        {"req_id": "R-002", "title": "Watchdog resets on starvation"},
    ],
}


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    ensure_project_layout(root)
    return root


def index(root: Path, payload: object = REQUIREMENTS) -> None:
    path = root / REQUIREMENTS_INDEX_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def add_test(root: Path, name: str, body: str) -> None:
    path = root / "tests" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def verdicts(cases: list[dict] | None = None, passed: bool = True) -> dict:
    return {
        "compile": VerifyResult(passed=passed, tool="arm-none-eabi-gcc"),
        "host-tests": VerifyResult(passed=passed, tool="gcc", cases=cases or []),
    }


def report(root: Path, cases: list[dict] | None = None) -> dict:
    return build_report(root, verdicts(cases))


# ------------------------------------------------------------------- joining


def test_a_declared_link_joins_the_case_to_its_requirement(project: Path) -> None:
    index(project)
    add_test(project, "crc_test.c", "/* requires: R-001 */\nint main(void){return 0;}\n")

    built = report(project, [{"file": "tests/crc_test.c", "verdict": "PASS"}])

    assert built["test_cases"][0]["requires"] == ["R-001"]
    crc = next(r for r in built["requirements"] if r["req_id"] == "R-001")
    assert crc == {"req_id": "R-001", "title": "Bootloader verifies CRC", "tests": ["tests/crc_test.c"], "status": "covered"}
    assert built["traceability"]["status"] == "complete"


def test_an_undecorated_requirement_is_untested_not_invisibly_covered(project: Path) -> None:
    index(project)
    add_test(project, "crc_test.c", "/* requires: R-001 */\n")

    built = report(project)

    watchdog = next(r for r in built["requirements"] if r["req_id"] == "R-002")
    assert watchdog["status"] == "untested"
    assert built["traceability"]["requirements_untested"] == ["R-002"]


def test_a_case_without_a_declaration_covers_nothing(project: Path) -> None:
    index(project)
    add_test(project, "crc_test.c", "int main(void){return 0;}\n")

    built = report(project, [{"file": "tests/crc_test.c", "verdict": "PASS"}])

    assert built["test_cases"][0]["requires"] == []
    assert built["traceability"]["declared_links"] == 0
    assert all(r["status"] == "untested" for r in built["requirements"])


def test_stage_verdicts_are_never_attributed_to_a_requirement(project: Path) -> None:
    index(project)

    built = report(project)

    assert all(stage["requirements"] == WHOLE_PROJECT for stage in built["stages"]), (
        "a whole-build verdict is not evidence about one requirement"
    )


# ------------------------------------------------------- broken traces surface


def test_a_malformed_link_is_reported_not_dropped(project: Path) -> None:
    index(project)
    add_test(project, "crc_test.c", "// requires: R-1\n")

    built = report(project)

    trace = built["traceability"]
    assert trace["status"] == "broken"
    assert trace["malformed_links"] == [{"file": "tests/crc_test.c", "declared": "R-1"}]
    assert trace["declared_links"] == 1, "the link still counts, or the report hides the typo"


def test_a_link_to_an_unknown_requirement_is_broken(project: Path) -> None:
    index(project)
    add_test(project, "crc_test.c", "/* requires: R-999 */\n")

    built = report(project)

    assert built["traceability"]["status"] == "broken"
    assert built["traceability"]["unknown_ids"] == [{"file": "tests/crc_test.c", "req_id": "R-999"}]


def test_a_missing_index_is_not_evaluated_rather_than_complete(project: Path) -> None:
    (project / REQUIREMENTS_INDEX_RELATIVE).unlink()
    add_test(project, "crc_test.c", "/* requires: R-001 */\n")

    built = report(project)

    assert built["traceability"]["status"] == "not-evaluated"
    assert "PRD not ingested" in built["traceability"]["reason"]
    assert "not evaluated" in render_markdown(built)


def test_the_scaffolded_empty_index_is_not_evaluated(project: Path) -> None:
    """S02 ships an index with `requirements: []`; that must not read as complete."""
    add_test(project, "crc_test.c", "/* requires: R-001 */\n")

    built = report(project)

    assert built["traceability"]["status"] == "not-evaluated"
    assert built["traceability"]["reason"].endswith("PRD not ingested")
    assert built["requirements"] == []


def test_a_corrupt_index_names_the_file_and_error(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    ensure_project_layout(root)
    path = root / REQUIREMENTS_INDEX_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    built = build_report(root, verdicts())

    assert built["traceability"]["status"] == "not-evaluated"
    assert REQUIREMENTS_INDEX_RELATIVE in built["traceability"]["reason"]


# ------------------------------------------------------------------ rendering


def test_a_failure_note_names_the_stages_instead_of_softening_them(project: Path) -> None:
    index(project)
    built = build_report(project, {"compile": VerifyResult(passed=False), "static": VerifyResult(passed=False, stub=True)})

    assert built["overall"] == "FAILED"
    assert built["overall_note"] == "1 stage(s) failed: compile", "a stub must not become the headline"


def test_a_pass_with_a_stub_qualifies_itself(project: Path) -> None:
    index(project)
    built = build_report(project, {"compile": VerifyResult(passed=True), "static": VerifyResult(passed=False, stub=True)})

    assert built["overall"] == "PASSED"
    assert built["overall_note"] == "passed with unverified stages: static"


def test_the_two_renderings_cannot_disagree(project: Path) -> None:
    index(project)
    add_test(project, "crc_test.c", "/* requires: R-001 */\n")
    built = report(project, [{"file": "tests/crc_test.c", "verdict": "PASS"}])
    paths = write_report(project, built)

    markdown = paths["markdown"].read_text(encoding="utf-8")
    on_disk = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert on_disk == json.loads(json.dumps(built))
    for stage in built["stages"]:
        assert f"| {stage['name']} | {stage['verdict']} |" in markdown
    assert "| tests/crc_test.c | PASS | R-001 |" in markdown


def test_the_same_inputs_produce_the_same_bytes(project: Path) -> None:
    index(project)
    add_test(project, "crc_test.c", "/* requires: R-001 */\n")

    first = write_report(project, report(project, [{"file": "tests/crc_test.c", "verdict": "PASS"}]))
    second = write_report(project, report(project, [{"file": "tests/crc_test.c", "verdict": "PASS"}]))

    assert first["json"].read_bytes() == second["json"].read_bytes()
    assert first["markdown"].read_bytes() == second["markdown"].read_bytes()


# ------------------------------------------------------- architecture coverage


COVERAGE = {
    "schema": "epi.requirement-coverage/1",
    "status": "incomplete",
    "reason": "",
    "requirements_total": 2,
    "assigned": {"R-001": ["module:MOD-001"]},
    "unassigned": ["R-002"],
    "unknown_refs": [{"section": "MODULE_DESIGN_TABLE", "claimant": "module:MOD-002", "declared": "R-999"}],
    "placeholder_rows": 1,
}


def test_a_report_always_carries_a_coverage_section(project: Path) -> None:
    """Absent is not the same as fine: the section exists and says it was not computed."""
    index(project)

    built = build_report(project, verdicts())

    assert built["design_coverage"]["status"] == "not-evaluated"
    assert "caller did not run" in built["design_coverage"]["reason"]


def test_the_coverage_passed_in_lands_in_json_and_markdown(project: Path) -> None:
    index(project)

    built = build_report(project, verdicts(), COVERAGE)
    markdown = render_markdown(built)

    assert built["design_coverage"]["unassigned"] == ["R-002"]
    assert "## Requirement → architecture" in markdown
    assert "unmapped: 1 (R-002)" in markdown
    assert "module:MOD-002 -> R-999" in markdown
    assert "| R-001 | module:MOD-001 |" in markdown


def test_an_unevaluated_coverage_renders_the_reason(project: Path) -> None:
    index(project)

    built = build_report(project, verdicts(), {"status": "not-evaluated", "reason": "still the generated template"})

    assert "not evaluated: still the generated template" in render_markdown(built)


def test_the_coverage_section_is_written_to_disk(project: Path) -> None:
    index(project)

    paths = write_report(project, build_report(project, verdicts(), COVERAGE))

    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["design_coverage"]["status"] == "incomplete"

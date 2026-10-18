"""The generate and test phases must report what actually ran - P0-6/P0-7 acceptance lives here."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from firmware_agent.project_layout import ensure_project_layout
from firmware_agent.workflow import WorkflowPhase, WorkflowRunner

GCC = shutil.which("gcc")

SOURCE = "int answer(void)\n{\n    return 42;\n}\n"
HEADER = "int answer(void);\n"
PASSING_TEST = '#include <assert.h>\n#include "answer.h"\nint main(void)\n{\n    assert(answer() == 42);\n    return 0;\n}\n'
FAILING_TEST = '#include <assert.h>\n#include "answer.h"\nint main(void)\n{\n    assert(answer() == 41);\n    return 0;\n}\n'


@pytest.fixture()
def runner(tmp_path: Path, host: str | None = "gcc") -> WorkflowRunner:
    root = tmp_path / "proj"
    ensure_project_layout(root)
    (root / "Docs/config.yaml").write_text(
        yaml.safe_dump(
            {
                "project": {"name": "brake-controller"},
                "mcu": {"part": "STM32F407VGT6"},
                "toolchain": {"compiler": "gcc", "host_compiler": host},
                "llm": {"provider": "openai_compatible", "model": "Qwen3.8-27B"},
            }
        ),
        encoding="utf-8",
    )
    instance = WorkflowRunner(root)
    instance.state.phase = WorkflowPhase.TEST.value
    return instance


def at_generate(runner: WorkflowRunner) -> WorkflowRunner:
    runner.state.phase = WorkflowPhase.GENERATE.value
    return runner


def add(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def report(runner: WorkflowRunner) -> str:
    return (runner.project_dir / "Docs/ai-generation/reports/test_report.md").read_text(encoding="utf-8")


def test_generate_compiles_the_design_and_admits_it_writes_no_code(runner: WorkflowRunner, capsys) -> None:
    at_generate(runner)
    assert runner._phase_generate() is True
    assert runner.state.phase == WorkflowPhase.TEST.value

    out = capsys.readouterr().out
    assert "No code generator is implemented yet" in out
    assert (runner.project_dir / "Docs/ai-generation/system-design.compiled.json").exists()


def test_test_phase_fails_when_nothing_was_generated(runner: WorkflowRunner) -> None:
    assert runner._phase_test() is False
    assert runner.state.phase == WorkflowPhase.TEST.value, "a failed phase does not advance"
    assert "nothing was compiled" in report(runner)


def test_report_leads_with_the_stub_list(runner: WorkflowRunner) -> None:
    runner._phase_test()

    head = report(runner).splitlines()[:10]
    assert any("No evidence (stub)" in line and "static-analysis" in line for line in head), (
        "rule 4 of the stub discipline: the stub list is at the top of the report"
    )


@pytest.mark.skipif(GCC is None, reason="needs a host gcc to build and run a test")
def test_a_real_failing_case_fails_the_phase(runner: WorkflowRunner) -> None:
    root = runner.project_dir
    add(root, "include/answer.h", HEADER)
    add(root, "src/answer.c", SOURCE)
    add(root, "tests/answer_test.c", FAILING_TEST)

    assert runner._phase_test() is False
    assert runner.state.phase == WorkflowPhase.TEST.value, "a failed phase does not advance"
    assert "Assertion" in report(runner)


@pytest.mark.skipif(GCC is None, reason="needs a host gcc to build and run a test")
def test_a_stub_denies_certification_without_halting_the_run(runner: WorkflowRunner) -> None:
    """S30 semantics: `rejected` means not certified, not stopped.

    If rejection blocked the workflow while S23 is a stub, the only way to finish
    would be to remove the gate - the exact pressure that turns gates into
    decoration. So the verdict is recorded and CI fails on it.
    """
    root = runner.project_dir
    add(root, "include/answer.h", HEADER)
    add(root, "src/answer.c", SOURCE)
    add(root, "tests/answer_test.c", PASSING_TEST)

    assert runner._phase_test() is True
    assert runner.state.quality_gate == "rejected"

    gate = json.loads((root / "Docs/ai-generation/reports/quality_gate.json").read_text(encoding="utf-8"))
    assert [r["rule"] for r in gate["reasons"]] == ["no-stub-participation", "traceability-complete"], (
        "the stub and the un-ingested PRD are two independent reasons, both listed"
    )
    assert gate["judged_overall"] == "PASSED", "the run passed and is still not certified"


@pytest.mark.skipif(GCC is None, reason="needs a host gcc to build and run a test")
def test_a_real_passing_suite_completes_the_workflow(runner: WorkflowRunner) -> None:
    root = runner.project_dir
    add(root, "include/answer.h", HEADER)
    add(root, "src/answer.c", SOURCE)
    add(root, "tests/answer_test.c", PASSING_TEST)

    at_generate(runner)
    assert runner._phase_generate() is True
    assert runner._phase_test() is True
    assert runner.state.phase == WorkflowPhase.DONE.value
    assert runner.state.test_verdicts == {"compile": "pass", "host-tests": "pass", "static-analysis": "no_evidence"}
    assert "**Overall: PASSED** (passed with unverified stages: static-analysis)" in report(runner)


# ----------------------------------------------------------- status: evidence


def test_status_invents_no_evidence_when_nothing_ran(runner: WorkflowRunner) -> None:
    assert runner._evidence_lines() == [], "an absent record must render as absent, not as a clean bill"


def test_status_shows_a_stub_as_no_evidence_not_as_a_pass(runner: WorkflowRunner) -> None:
    runner.state.test_verdicts = {"compile": "pass", "static-analysis": "no_evidence"}

    lines = runner._evidence_lines()

    body = "\n".join(lines)
    assert "static-analysis: [magenta]no evidence (stub)[/magenta]" in body
    assert "compile: [green]pass[/green]" in body


def test_status_refuses_certification_in_words(runner: WorkflowRunner) -> None:
    runner.state.test_verdicts = {"compile": "pass"}
    runner.state.quality_gate = "rejected"

    assert "NOT CERTIFIED" in "\n".join(runner._evidence_lines())


def test_status_reports_an_unjudged_gate_as_unjudged(runner: WorkflowRunner) -> None:
    runner.state.test_verdicts = {"compile": "pass"}

    assert "quality gate: not judged yet" in "\n".join(runner._evidence_lines())


# --------------------------------------------------- design review: coverage


def at_design_review(runner: WorkflowRunner) -> WorkflowRunner:
    runner.state.phase = WorkflowPhase.WAIT_FOR_DESIGN_REVIEW.value
    return runner


def ingest_requirements(runner: WorkflowRunner, ids: list[str]) -> None:
    index = runner.project_dir / "Docs/ai-generation/knowledge/requirements_index.json"
    index.write_text(json.dumps({"requirements": [{"req_id": i} for i in ids]}), encoding="utf-8")


def test_design_review_reports_coverage_instead_of_assuming_it(runner: WorkflowRunner) -> None:
    at_design_review(runner)

    runner._report_design_coverage()

    assert runner.state.requirement_coverage == "not-evaluated"


def test_an_untouched_design_template_is_not_read_as_coverage(runner: WorkflowRunner) -> None:
    at_design_review(runner)
    ingest_requirements(runner, ["R-001"])

    runner._report_design_coverage()

    assert runner.state.requirement_coverage == "not-evaluated"


def test_unmapped_requirements_are_named_before_approval(runner: WorkflowRunner, capsys) -> None:
    at_design_review(runner)
    ingest_requirements(runner, ["R-001", "R-002"])
    design = runner.project_dir / "Docs/ai-generation/fw-architecture/system-design/system-design.md"
    design.write_text(
        design.read_text(encoding="utf-8").replace(
            "| MOD-001 | module | N/A | N/A | N/A | N/A | N/A | R-001 |",
            "| MOD-001 | module | crc | checksum | spi | out | none | R-001 |",
        ),
        encoding="utf-8",
    )

    runner._report_design_coverage()

    assert runner.state.requirement_coverage == "incomplete"
    assert "R-002" in capsys.readouterr().out


def test_a_mapped_design_shows_complete_coverage(runner: WorkflowRunner) -> None:
    at_design_review(runner)
    ingest_requirements(runner, ["R-001"])
    design = runner.project_dir / "Docs/ai-generation/fw-architecture/system-design/system-design.md"
    design.write_text(
        design.read_text(encoding="utf-8").replace(
            "| MOD-001 | module | N/A | N/A | N/A | N/A | N/A | R-001 |",
            "| MOD-001 | module | crc | checksum | spi | out | none | R-001 |",
        ),
        encoding="utf-8",
    )

    runner._report_design_coverage()

    assert runner.state.requirement_coverage == "complete"
    assert "requirement coverage: [green]complete[/green]" in "\n".join(runner._evidence_lines())

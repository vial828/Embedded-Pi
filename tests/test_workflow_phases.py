"""The generate and test phases must report what actually ran - P0-6/P0-7 acceptance lives here."""

from __future__ import annotations

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

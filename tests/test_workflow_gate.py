"""P0-1: the external input gate can be waived explicitly, and never rolls back silently."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from firmware_agent.project_layout import ensure_project_layout
from firmware_agent.workflow import WorkflowPhase, WorkflowRunner

PRD = "Docs/prd/ (*.pdf OR *.docx OR *.md)"
BSP = "Docs/bsp/ (*.*)"


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    ensure_project_layout(root)
    return root


def state_file(root: Path) -> dict:
    return json.loads((root / "Docs/ai-generation/workflow/state.json").read_text(encoding="utf-8"))


def test_fresh_layout_blocks_every_template_group(project: Path) -> None:
    runner = WorkflowRunner(project)
    missing = runner._missing_required_paths()
    # Templates ship in these directories, so "file exists" must not mean "input ready".
    assert PRD in missing and BSP in missing
    assert runner._detect_prd_ready() == missing
    assert runner.state.waived_missing == []


def test_waiver_is_granted_only_when_asked_and_is_persisted(project: Path) -> None:
    WorkflowRunner(project, allow_missing=True)._apply_missing_waiver()
    stored = state_file(project)
    assert stored["waived_missing"], "waiver must survive in the state file"
    assert PRD in stored["waived_missing"]
    assert "waived" in stored["notes"]

    resumed = WorkflowRunner(project)
    assert resumed._detect_prd_ready() == [], "a waived path must stop blocking"


def test_waiver_expires_when_the_flag_is_not_repeated(project: Path) -> None:
    WorkflowRunner(project, allow_missing=True)._apply_missing_waiver()
    assert state_file(project)["waived_missing"]

    # A later plain run must not inherit the bypass - that would be a silent gate.
    WorkflowRunner(project)._apply_missing_waiver()
    assert state_file(project)["waived_missing"] == []
    assert WorkflowRunner(project)._detect_prd_ready()


def test_waiver_covers_exactly_the_paths_it_listed(project: Path) -> None:
    runner = WorkflowRunner(project)
    runner.state.waived_missing = [BSP]
    blocked = runner._detect_prd_ready()
    assert BSP not in blocked
    assert PRD in blocked, "an unwaived missing input still blocks"


def test_re_arming_the_gate_reports_what_blocks(project: Path, capsys) -> None:
    runner = WorkflowRunner(project)
    runner.state.phase = WorkflowPhase.GENERATE.value
    runner.save_state()

    assert runner._pin_to_external_gate_if_needed() is True
    out = capsys.readouterr().out
    assert "Gate re-armed" in out
    assert "Docs/bsp" in out, "the rollback must name the blocking inputs, not just happen"

    stored = state_file(project)
    assert stored["phase"] == WorkflowPhase.WAIT_FOR_EXTERNAL_FILES.value


def test_waived_run_is_not_pulled_back_to_the_gate(project: Path) -> None:
    runner = WorkflowRunner(project, allow_missing=True)
    runner._apply_missing_waiver()
    runner.state.phase = WorkflowPhase.GENERATE.value
    runner.save_state()
    assert runner._pin_to_external_gate_if_needed() is False


def test_cli_forwards_the_flag(monkeypatch, project: Path) -> None:
    """The flag must exist at the real CLI layer, not just as a keyword argument."""
    import typer
    from typer.testing import CliRunner

    from firmware_agent import cli

    seen: dict = {}
    monkeypatch.setattr(cli, "run_workflow", lambda root, allow_missing=False: seen.__setitem__("allow_missing", allow_missing))

    app = typer.Typer()
    app.command()(cli.entry)

    result = CliRunner().invoke(app, [str(project), "--allow-missing"])
    assert result.exit_code == 0, result.output
    assert seen == {"allow_missing": True}

    seen.clear()
    result = CliRunner().invoke(app, [str(project)])
    assert result.exit_code == 0, result.output
    assert seen == {"allow_missing": False}, "the gate must stay armed by default"

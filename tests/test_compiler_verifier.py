"""P0-6: S22 compiler verifier. The rule under test: a verdict only exists if a compiler ran."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from firmware_agent.project_layout import ensure_project_layout
from firmware_agent.slices.S21_Executor.action_executor import read_action_log
from firmware_agent.slices.S22_Compiler_Verifier.compiler_verifier import (
    CompilerVerifier,
    VerifyResult,
)
from firmware_agent.slices.S23_Static_Verifier.static_verifier import StaticVerifier
from firmware_agent.slices.S24_Simulator_Verifier.simulator_verifier import (
    SimulatorVerifier,
)

GCC = shutil.which("gcc")

GOOD = """
int boot_check(void)
{
    return 0;
}
"""

BROKEN = """
int boot_check(void)
{
    return not_a_real_symbol;
}
"""


@pytest.fixture()
def project(tmp_path: Path, compiler: str = "gcc") -> Path:
    root = tmp_path / "proj"
    ensure_project_layout(root)
    config = {
        "project": {"name": "brake-controller"},
        "mcu": {"part": "STM32F407VGT6"},
        "toolchain": {"compiler": compiler},
        "llm": {"provider": "openai_compatible", "model": "Qwen3.8-27B"},
    }
    (root / "Docs/config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    (root / "src").mkdir(exist_ok=True)
    return root


def write_source(root: Path, name: str, body: str) -> Path:
    path = root / "src" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# ------------------------------------------------------- verdicts with no work


def test_a_stub_can_never_report_success() -> None:
    with pytest.raises(ValueError):
        VerifyResult(passed=True, stub=True, output="[stub] compiled")


def test_remaining_stubs_mark_themselves_so_the_quality_gate_can_reject_them() -> None:
    result = StaticVerifier().verify("anything")
    assert result.stub is True and result.passed is False


def test_s24_is_no_longer_a_stub_but_still_refuses_to_guess() -> None:
    result = SimulatorVerifier().verify("anything")
    assert result.stub is False and result.passed is False
    assert "no project root" in result.output


def test_an_empty_src_is_not_a_clean_build(project: Path) -> None:
    result = CompilerVerifier(project_root=project).verify("Compile generated firmware")

    assert result.passed is False
    assert "nothing was compiled" in result.output


def test_an_unconfigured_verifier_refuses_to_judge() -> None:
    result = CompilerVerifier().verify("Compile generated firmware")
    assert result.passed is False and "no project root" in result.output


@pytest.mark.skipif(GCC is None, reason="needs a host gcc to prove a real verdict")
def test_a_missing_compiler_is_reported_not_swallowed(project: Path) -> None:
    config = yaml.safe_load((project / "Docs/config.yaml").read_text(encoding="utf-8"))
    config["toolchain"]["compiler"] = "definitely-not-a-real-compiler"
    (project / "Docs/config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    write_source(project, "main.c", GOOD)

    result = CompilerVerifier(project_root=project).verify("Compile generated firmware")

    assert result.passed is False
    assert "definitely-not-a-real-compiler" in result.tool


# ----------------------------------------------------------------- real gcc


@pytest.mark.skipif(GCC is None, reason="needs a host gcc to prove a real verdict")
def test_good_source_passes_and_leaves_objects(project: Path) -> None:
    write_source(project, "boot.c", GOOD)

    result = CompilerVerifier(project_root=project).verify("Compile generated firmware")

    assert result.passed is True, result.output
    assert "gcc" in result.tool
    assert (project / "build/objects/src/boot.o").exists()
    assert result.duration_ms >= 0


@pytest.mark.skipif(GCC is None, reason="needs a host gcc to prove a real verdict")
def test_one_broken_file_must_fail_the_run(project: Path) -> None:
    write_source(project, "boot.c", GOOD)
    write_source(project, "driver/uart.c", BROKEN)

    result = CompilerVerifier(project_root=project).verify("Compile generated firmware")

    assert result.passed is False, "the acceptance criterion for P0-6"
    assert "uart.c" in result.output and "FAILED" in result.output
    assert "not_a_real_symbol" in result.output, "the compiler's own diagnostic must reach the report"


@pytest.mark.skipif(GCC is None, reason="needs a host gcc to prove a real verdict")
def test_commands_and_exit_codes_are_recorded(project: Path) -> None:
    write_source(project, "boot.c", GOOD)
    write_source(project, "bad.c", BROKEN)

    CompilerVerifier(project_root=project).verify("Compile generated firmware")

    entries = [e for e in read_action_log(project, "compile-compile-generated-firmware") if e["action"] == "run_command"]
    compile_calls = [e for e in entries if any(arg.endswith(".c") for arg in e["params"]["argv"])]
    assert len(compile_calls) == 2
    assert sorted(e["result"]["exit_code"] for e in compile_calls) == [0, 1]
    assert all(any(arg.endswith(".c") for arg in e["params"]["argv"]) for e in compile_calls)

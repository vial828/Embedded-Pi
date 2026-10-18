"""P0-7: S24 host test runner. The rule under test: a real failing case fails the phase."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from firmware_agent.project_layout import ensure_project_layout
from firmware_agent.slices.S21_Executor.action_executor import read_action_log
from firmware_agent.slices.S24_Simulator_Verifier.simulator_verifier import (
    SimulatorVerifier,
)

GCC = shutil.which("gcc")

UART_H = "int uart_ready(void);\n"
UART_C = "int uart_ready(void)\n{\n    return 1;\n}\n"
PASSING_TEST = """#include <assert.h>
#include "uart.h"

int main(void)
{
    assert(uart_ready() == 1);
    return 0;
}
"""
FAILING_TEST = """#include <assert.h>
#include "uart.h"

int main(void)
{
    assert(uart_ready() == 0);
    return 0;
}
"""
BROKEN_TEST = """#include "uart.h"

int main(void)
{
    return uart_not_declared();
}
"""
HANGING_TEST = """int main(void)
{
    for (;;) { }
    return 0;
}
"""


@pytest.fixture()
def project(tmp_path: Path, host_compiler: str | None = "gcc") -> Path:
    root = tmp_path / "proj"
    ensure_project_layout(root)
    config = {
        "project": {"name": "brake-controller"},
        "mcu": {"part": "STM32F407VGT6"},
        "toolchain": {"compiler": "arm-none-eabi-gcc", "host_compiler": host_compiler},
        "llm": {"provider": "openai_compatible", "model": "Qwen3.8-27B"},
    }
    (root / "Docs/config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    for rel, body in (("include/uart.h", UART_H), ("src/uart.c", UART_C)):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return root


def add_test(root: Path, name: str, body: str) -> Path:
    path = root / "tests" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def run(root: Path, **kwargs) -> object:
    return SimulatorVerifier(project_root=root, **kwargs).verify("Run host tests")


# ------------------------------------------------------- verdicts with no work


def test_no_tests_is_not_a_pass(project: Path) -> None:
    result = run(project)

    assert result.passed is False
    assert "collected nothing" in result.output
    assert result.stub is False, "this verifier is no longer a stub"


def test_host_tests_without_a_host_compiler_are_reported(project: Path) -> None:
    add_test(project, "uart_test.c", PASSING_TEST)
    config = yaml.safe_load((project / "Docs/config.yaml").read_text(encoding="utf-8"))
    config["toolchain"]["host_compiler"] = None
    (project / "Docs/config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")

    result = run(project)

    assert result.passed is False
    assert "toolchain.host_compiler" in result.output, "it must name the setting, not guess a compiler"


# ------------------------------------------------------------------ real gcc


@pytest.mark.skipif(GCC is None, reason="needs a host gcc to build and run a test")
def test_a_passing_suite_passes(project: Path) -> None:
    add_test(project, "uart_test.c", PASSING_TEST)

    result = run(project)

    assert result.passed is True, result.output
    assert "PASS" in result.output and "gcc" in result.tool


@pytest.mark.skipif(GCC is None, reason="needs a host gcc to build and run a test")
def test_a_failing_case_fails_the_phase(project: Path) -> None:
    """The acceptance criterion for P0-7."""
    add_test(project, "uart_test.c", FAILING_TEST)

    result = run(project)

    assert result.passed is False
    assert "FAIL" in result.output
    assert "Assertion" in result.output, "the assertion text is the evidence, keep it"


@pytest.mark.skipif(GCC is None, reason="needs a host gcc to build and run a test")
def test_a_test_that_will_not_build_is_a_failure_not_a_skip(project: Path) -> None:
    add_test(project, "uart_test.c", BROKEN_TEST)

    result = run(project)

    assert result.passed is False
    assert "BUILD FAILED" in result.output
    assert "uart_not_declared" in result.output


@pytest.mark.skipif(GCC is None, reason="needs a host gcc to build and run a test")
def test_a_hanging_test_fails_instead_of_hanging_forever(project: Path) -> None:
    add_test(project, "hang_test.c", HANGING_TEST)

    result = run(project, timeout=2)

    assert result.passed is False
    assert "timed_out" in result.output


@pytest.mark.skipif(GCC is None, reason="needs a host gcc to build and run a test")
def test_one_failing_case_among_passing_ones_fails_the_run(project: Path) -> None:
    add_test(project, "uart_ok_test.c", PASSING_TEST)
    add_test(project, "uart_bad_test.c", FAILING_TEST)

    result = run(project)

    assert result.passed is False
    assert "PASS" in result.output and "FAIL" in result.output


@pytest.mark.skipif(GCC is None, reason="needs a host gcc to build and run a test")
def test_build_and_run_are_recorded(project: Path) -> None:
    add_test(project, "uart_test.c", PASSING_TEST)

    run(project)

    entries = [e for e in read_action_log(project, "hosttest-run-host-tests") if e["action"] == "run_command"]
    builds = [e for e in entries if any(a.endswith(".c") for a in e["params"]["argv"])]
    runs = [e for e in entries if e["params"]["argv"][0].endswith(("uart_test", "uart_test.exe"))]
    assert builds and runs
    assert all(e["result"]["exit_code"] == 0 for e in builds + runs)

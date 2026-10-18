"""S24 - Host-side test runner (the minimal form of the simulator verifier).

P0-7 runs unit tests on the host: compile each `tests/**/*_test.c` with the host
compiler, run the binary, and let its exit code decide. That is enough to make
"the tests pass" a fact rather than a sentence in a report.

Rules that decide the verdict:

1. **No tests is not a pass.** A suite that collected nothing proves nothing.
2. **No host compiler, when tests exist, is not a pass.** Host tests cannot be
   built by a cross compiler, and silently using the target compiler would
   produce a binary that cannot run here.
3. **A test that fails to build is a failure, not a skip.** So is one that
   times out.

The convention for a unit test is deliberately small: include `<assert.h>`, write
`main()`, return 0 on success. No harness, no generated headers - the C standard
library already provides the assertion, and a generated test framework would be
content this project is not supposed to invent.
"""

from __future__ import annotations

import time
from pathlib import Path

from firmware_agent.config import AppConfig, load_project_config
from firmware_agent.slices.S21_Executor.action_executor import ActionExecutor
from firmware_agent.slices.S22_Compiler_Verifier.compiler_verifier import VerifyResult

__all__ = ["SimulatorVerifier"]

TEST_SUFFIX = "_test.c"
RUN_TIMEOUT = 60


class SimulatorVerifier:
    def __init__(
        self,
        config: AppConfig | None = None,
        project_root: str | Path | None = None,
        *,
        executor: ActionExecutor | None = None,
        timeout: int = RUN_TIMEOUT,
    ):
        self._config = config
        self.project_root = Path(project_root) if project_root is not None else None
        self._executor = executor
        self.timeout = timeout

    def verify(self, task_name: str) -> VerifyResult:
        started = time.monotonic()

        if self.project_root is None:
            return VerifyResult(
                passed=False,
                output="SimulatorVerifier has no project root; refusing to report a verdict it did not compute.",
            )
        config = self._config or load_project_config(self.project_root)
        tests = sorted((self.project_root / "tests").rglob(f"*{TEST_SUFFIX}")) if (self.project_root / "tests").exists() else []

        if not tests:
            return VerifyResult(
                passed=False,
                output=f"no *{TEST_SUFFIX} files under tests/ - a suite that collected nothing proves nothing.",
                duration_ms=_elapsed(started),
            )

        host = config.toolchain.host_compiler
        if not host:
            return VerifyResult(
                passed=False,
                output=f"{len(tests)} host test(s) found but toolchain.host_compiler is not set. "
                "A cross compiler cannot produce a binary this machine can run.",
                duration_ms=_elapsed(started),
            )

        allowed = {host}
        executor = self._executor or ActionExecutor(
            self.project_root, _audit_task_id(task_name), allowed_executables=allowed
        )
        tool = self._tool_version(executor, host)
        lines: list[str] = []
        commands: list[str] = []
        cases: list[dict] = []
        failed = False

        for test in tests:
            binary = self._binary_path(test)
            sources = sorted(str(path.relative_to(self.project_root)) for path in (self.project_root / "src").glob("**/*.c"))
            rel_test = str(test.relative_to(self.project_root))
            build = [host, "-std=c11", "-I", "include", rel_test, *sources, "-o", str(binary)]
            commands.append(" ".join(build))
            build_result = executor.run_command(build, cwd=".", timeout=self.timeout)
            if not build_result.ok:
                failed = True
                cases.append({"file": rel_test, "verdict": "BUILD_FAILED", "output": _detail(build_result)})
                lines.append(f"$ {' '.join(build)}\n  BUILD FAILED exit={build_result.exit_code}\n{_detail(build_result)}")
                continue

            executor.allow_executable(str(binary))
            run = executor.run_command([str(binary)], cwd=".", timeout=self.timeout)
            commands.append(f"{binary} (exit {run.exit_code})")
            verdict = "PASS" if run.ok else ("TIMEOUT" if run.timed_out else "FAIL")
            if run.ok or run.timed_out:
                status = verdict
            else:
                status = f"{verdict} exit={run.exit_code}"
            failed = failed or not run.ok
            cases.append({"file": rel_test, "verdict": verdict, "output": _detail(run)})
            lines.append(f"$ {binary}\n  {status}\n{_detail(run)}".rstrip())

        return VerifyResult(
            passed=not failed,
            output="\n".join(lines),
            tool=tool,
            duration_ms=_elapsed(started),
            commands=commands,
            cases=cases,
        )

    # -------------------------------------------------------------- helpers

    def _binary_path(self, test: Path) -> Path:
        rel = test.relative_to(self.project_root / "tests").with_suffix(".exe" if _is_windows() else "")
        binary = self.project_root / "build" / "tests" / rel
        binary.parent.mkdir(parents=True, exist_ok=True)
        return binary

    def _tool_version(self, executor: ActionExecutor, compiler: str) -> str:
        result = executor.run_command([compiler, "--version"], cwd=".", timeout=30)
        if result.exit_code != 0:
            return f"{compiler} (version unavailable: {_detail(result)})"
        return (result.stdout or "").splitlines()[0] if result.stdout else compiler


def _detail(result) -> str:
    return ((result.stderr or "") + (result.stdout or "")).strip()


def _is_windows() -> bool:
    import os

    return os.name == "nt"


def _audit_task_id(task_name: str) -> str:
    slug = "".join(char if char.isalnum() else "-" for char in task_name.strip().lower()).strip("-")
    return f"hosttest-{slug or 'unspecified'}"


def _elapsed(started: float) -> int:
    return int((time.monotonic() - started) * 1000)

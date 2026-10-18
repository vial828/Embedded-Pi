"""S22 - Compiler verifier: run the configured compiler and report what happened.

Replaces the stub that returned `passed=True` unconditionally, which made every
downstream stage look green while nothing had been built.

Three honesty rules:

1. **No sources is not a pass.** An empty `src/` compiles "cleanly" only if you
   agree to count zero work as success.
2. **No compiler is not a pass.** A missing toolchain is reported as a failure
   that says which binary it looked for.
3. **Nothing passes without a command behind it.** Every invocation goes through
   the S21 executor, so the argv and exit code are in
   `Docs/ai-generation/audit/<task-id>/actions.jsonl`. `stub=True` results can
   never carry `passed=True` (asserted, not just documented).

Target-specific flags (cpu/fpu/thumb) are deliberately absent: this is a syntax
and codegen check with the configured compiler, and adding cross flags is a P1
decision that belongs in configuration, not in a verifier.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from firmware_agent.config import AppConfig, load_project_config
from firmware_agent.slices.S21_Executor.action_executor import (
    ActionExecutor,
    CommandResult,
)

__all__ = ["CompilerVerifier", "VerifyResult"]

SOURCE_SUFFIXES = (".c",)


@dataclass
class VerifyResult:
    passed: bool
    output: str = ""
    stub: bool = False
    tool: str = ""
    duration_ms: int = 0
    commands: list[str] = field(default_factory=list)
    # Per-case verdicts where the stage runs cases (S24). The report (S29) joins
    # these to requirement IDs; verifiers must not do that join themselves, so a
    # stage that cannot attribute a result says so by leaving this empty.
    cases: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.stub and self.passed:
            raise ValueError("a stub may not report success")


class CompilerVerifier:
    def __init__(
        self,
        config: AppConfig | None = None,
        project_root: str | Path | None = None,
        *,
        executor: ActionExecutor | None = None,
        timeout: int = 300,
    ):
        self._config = config
        self.project_root = Path(project_root) if project_root is not None else None
        self._executor = executor
        self.timeout = timeout

    # ------------------------------------------------------------------ api

    def verify(self, task_name: str) -> VerifyResult:
        started = time.monotonic()

        if self.project_root is None:
            return VerifyResult(
                passed=False,
                output="CompilerVerifier has no project root; refusing to report a verdict it did not compute.",
            )
        config = self._config or load_project_config(self.project_root)
        compiler = config.toolchain.compiler
        executor = self._executor or ActionExecutor(
            self.project_root, _audit_task_id(task_name), allowed_executables={compiler}
        )

        sources = sorted(
            path for suffix in SOURCE_SUFFIXES for path in self.project_root.glob(f"src/**/*{suffix}")
        )
        if not sources:
            return VerifyResult(
                passed=False,
                output=f"no {', '.join(SOURCE_SUFFIXES)} sources under src/ - nothing was compiled, "
                "so nothing can be claimed.",
                tool=compiler,
                duration_ms=_elapsed(started),
            )

        tool = self._tool_version(executor, compiler)
        lines: list[str] = []
        commands: list[str] = []
        failed = False

        for source in sources:
            obj = self._object_path(source)
            argv = self._command(compiler, source, obj)
            commands.append(" ".join(argv))
            result = executor.run_command(argv, cwd=".", timeout=self.timeout)
            lines.append(self._summarise(source, argv, result))
            failed = failed or not result.ok

        return VerifyResult(
            passed=not failed,
            output="\n".join(lines),
            tool=tool,
            duration_ms=_elapsed(started),
            commands=commands,
        )

    # -------------------------------------------------------------- helpers

    def _command(self, compiler: str, source: Path, obj: Path) -> list[str]:
        root = self.project_root
        return [
            compiler,
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-ffreestanding",
            "-I",
            str((root / "include").relative_to(root)),
            "-c",
            str(source.relative_to(root)),
            "-o",
            str(obj.relative_to(root)),
        ]

    def _object_path(self, source: Path) -> Path:
        rel = source.relative_to(self.project_root).with_suffix(".o")
        obj = self.project_root / "build" / "objects" / rel
        obj.parent.mkdir(parents=True, exist_ok=True)
        return obj

    def _tool_version(self, executor: ActionExecutor, compiler: str) -> str:
        result = executor.run_command([compiler, "--version"], cwd=".", timeout=30)
        if result.exit_code != 0:
            return f"{compiler} (version unavailable: {result.stderr.strip() or result.stdout.strip()})"
        return (result.stdout or "").splitlines()[0] if result.stdout else compiler

    @staticmethod
    def _summarise(source: Path, argv: list[str], result: CommandResult) -> str:
        head = f"$ {' '.join(argv)}"
        status = "ok" if result.ok else f"FAILED exit={result.exit_code}{' timed_out' if result.timed_out else ''}"
        detail = (result.stderr or result.stdout or "").strip()
        body = f"\n{detail}" if detail else ""
        return f"{head}\n  {status}{body}"


def _audit_task_id(task_name: str) -> str:
    slug = "".join(char if char.isalnum() else "-" for char in task_name.strip().lower()).strip("-")
    return f"compile-{slug or 'unspecified'}"


def _elapsed(started: float) -> int:
    return int((time.monotonic() - started) * 1000)

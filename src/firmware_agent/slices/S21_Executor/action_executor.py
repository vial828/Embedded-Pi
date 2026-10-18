"""S21 - Action executor: the only component that touches disk or runs programs.

Everything here is mechanical on purpose. Model output arrives as arguments; this
module decides whether the action is *allowed*, performs it, and records it. It
never decides whether the result is good - that belongs to the verifiers (S22-S24)
and the quality gate (S30) - so `CommandResult` carries an exit code and no
`passed` field.

Three rules:

1. **Default-deny writes.** Only paths under `WRITABLE_PREFIXES` may be written,
   and only inside the project. An executor driven by model output must not be
   able to reach the PRD, the standards, the workflow state, or its own audit
   trail by spelling a path cleverly.
2. **Every action is recorded**, including the ones that fail and the ones that
   are refused. A refusal that leaves no trace is indistinguishable from a bug
   that skipped the check.
3. **Overwrites are visible.** The previous content hash goes into the log, so
   "the generator emptied the artifact" is a lookup, not an archaeology project -
   that incident is in the project log and cost a day.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "AUDIT_RELATIVE_ROOT",
    "WRITABLE_PREFIXES",
    "ActionExecutor",
    "CommandResult",
    "ExecutorError",
    "read_action_log",
]

AUDIT_RELATIVE_ROOT = "Docs/ai-generation/audit"

# Default-deny: firmware sources and host tests. Generated design artifacts are
# produced by their own slices (S04, S07), not by whatever a model asked for.
WRITABLE_PREFIXES = ("src/", "include/", "tests/", "Docs/ai-generation/generated/")


class ExecutorError(Exception):
    """An action was refused before it ran. The refusal is still logged."""


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    cwd: str
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        """Exit code 0 and no timeout. Not a verdict - callers still record it."""
        return self.exit_code == 0 and not self.timed_out


@dataclass
class _PendingAction:
    action: str
    params: dict[str, Any]
    started: float = field(default_factory=time.monotonic)


class ActionExecutor:
    def __init__(
        self,
        project_root: str | Path,
        task_id: str = "unassigned",
        *,
        writable_prefixes: tuple[str, ...] = WRITABLE_PREFIXES,
        allowed_executables: set[str] | None = None,
    ):
        """
        `allowed_executables` is the control surface for callers acting on
        untrusted input: pass the configured toolchain binaries and nothing else.
        `None` means unrestricted, which is only correct for trusted callers.
        """
        self.project_root = Path(project_root).resolve()
        self.task_id = task_id
        self.writable_prefixes = tuple(writable_prefixes)
        self.allowed_executables = set(allowed_executables) if allowed_executables is not None else None
        self.audit_dir = self.project_root / AUDIT_RELATIVE_ROOT / task_id
        self.audit_path = self.audit_dir / "actions.jsonl"
        # Sequence numbers continue across runs: two executors on the same task
        # must not both claim action 1.
        self._seq = sum(1 for _ in read_action_log(self.project_root, task_id))

    # ---------------------------------------------------------------- writes

    def write_text(self, relative_path: str, content: str) -> Path:
        """Write a project-relative file and return its path.

        Raises ExecutorError, after logging, if the path escapes the project or
        sits outside the writable allowlist.
        """
        target, rel = self._resolve(relative_path)
        self._check_writable(rel)
        previous = _sha256_of(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        self._record(
            "write_text",
            {"path": rel, "bytes": len(content.encode("utf-8"))},
            {"sha256": _sha256(content), "previous_sha256": previous},
        )
        return target

    def read_text(self, relative_path: str) -> str:
        target, rel = self._resolve(relative_path)
        try:
            data = target.read_text(encoding="utf-8")
        except OSError as exc:
            self._record("read_text", {"path": rel}, {"error": str(exc)})
            raise
        self._record("read_text", {"path": rel}, {"sha256": _sha256(data), "bytes": len(data.encode("utf-8"))})
        return data

    # -------------------------------------------------------------- commands

    def run_command(self, argv: list[str], cwd: str = ".", timeout: int = 300) -> CommandResult:
        """Run a program without a shell, inside the project, with a deadline.

        No shell means no second, unlogged interpretation layer where a policy
        violation could hide. Output is captured, never streamed to the terminal,
        so it can be recorded and replayed.
        """
        argv = [str(part) for part in argv]
        if not argv:
            self._record("run_command", {"argv": []}, {"refused": "empty argv"})
            raise ExecutorError("run_command needs a non-empty argv")

        resolved_cwd, rel_cwd = self._resolve(cwd, must_exist=True)
        if self.allowed_executables is not None and argv[0] not in self.allowed_executables:
            reason = f"{argv[0]!r} is not in the allowed executables for this task"
            self._record("run_command", {"argv": argv, "cwd": rel_cwd}, {"refused": reason})
            raise ExecutorError(reason)

        started = time.monotonic()
        try:
            completed = subprocess.run(
                argv,
                cwd=resolved_cwd,
                timeout=timeout,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,  # exit codes are data here; the caller decides what fails
            )
            result = CommandResult(
                argv=tuple(argv),
                cwd=rel_cwd,
                exit_code=completed.returncode,
                stdout=completed.stdout or "",
                stderr=completed.stderr or "",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        except subprocess.TimeoutExpired as exc:
            result = CommandResult(
                argv=tuple(argv),
                cwd=rel_cwd,
                exit_code=None,
                stdout=_decode(exc.stdout),
                stderr=_decode(exc.stderr) or f"timed out after {timeout}s",
                duration_ms=int((time.monotonic() - started) * 1000),
                timed_out=True,
            )
        except OSError as exc:
            # Executable missing or not runnable: a result, not an exception. The
            # verifier has to be able to report "compiler not installed" as a
            # failure it understood, not as a traceback.
            result = CommandResult(
                argv=tuple(argv),
                cwd=rel_cwd,
                exit_code=None,
                stdout="",
                stderr=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        self._record(
            "run_command",
            {"argv": argv, "cwd": rel_cwd, "timeout": timeout},
            {
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
                "duration_ms": result.duration_ms,
                "stdout_sha256": _sha256(result.stdout),
                "stderr_sha256": _sha256(result.stderr),
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        )
        return result

    # ----------------------------------------------------------------- audit

    def allow_executable(self, executable: str) -> None:
        """Admit one program to an otherwise restricted task.

        A caller that builds a binary and then runs it has to widen the list
        itself; going through the executor keeps that widening visible instead of
        relying on the caller aliasing the set it passed in.
        """
        if self.allowed_executables is not None:
            self.allowed_executables.add(executable)

    def _resolve(self, relative_path: str, *, must_exist: bool = False) -> tuple[Path, str]:
        candidate = Path(relative_path)
        if candidate.is_absolute():
            self._refuse("path", relative_path, "absolute paths are not allowed; use project-relative paths")
        target = (self.project_root / candidate).resolve()
        if not target.is_relative_to(self.project_root):
            self._refuse("path", relative_path, "path escapes the project root")
        rel = target.relative_to(self.project_root).as_posix()
        if must_exist and not target.exists():
            self._refuse("path", relative_path, "working directory does not exist")
        return target, rel

    def _check_writable(self, rel: str) -> None:
        if not rel.startswith(self.writable_prefixes):
            self._refuse("write", rel, f"not under a writable prefix ({', '.join(self.writable_prefixes)})")

    def _refuse(self, kind: str, target: str, reason: str) -> None:
        self._record(kind, {"path": target}, {"refused": reason})
        raise ExecutorError(f"{kind} {target!r} refused: {reason}")

    def _record(self, action: str, params: dict[str, Any], result: dict[str, Any]) -> None:
        self._seq += 1
        entry = {
            "seq": self._seq,
            "ts_utc": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "task_id": self.task_id,
            "action": action,
            "params": params,
            "result": result,
        }
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_action_log(project_root: str | Path, task_id: str) -> list[dict]:
    path = Path(project_root) / AUDIT_RELATIVE_ROOT / task_id / "actions.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_of(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _decode(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value

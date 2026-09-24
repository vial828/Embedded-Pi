from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Phase(str, Enum):
    REQUIREMENTS_REVIEW = "requirements_review"
    ARCHITECTURE = "architecture"
    IMPLEMENTATION = "implementation"
    VERIFICATION = "verification"
    DOCUMENTATION = "documentation"
    DONE = "done"
    FAILED = "failed"


class TaskType(str, Enum):
    PARSE_PRD = "parse_prd"
    PERIPHERAL_CONFIG = "peripheral_config"
    DRIVER_IMPL = "driver_impl"
    COMPILE = "compile"
    FIX_ERROR = "fix_error"
    DOCUMENT = "document"


@dataclass
class Task:
    type: TaskType
    description: str
    requirement_id: str | None = None
    peripheral: str | None = None
    needs_verification: bool = False


@dataclass
class WorkingState:
    mcu: str = "unknown"
    phase: Phase = Phase.REQUIREMENTS_REVIEW
    current_task: str = ""
    files_done: list[str] = field(default_factory=list)
    file_in_progress: str = ""
    dependencies: str = ""
    last_error: str = ""
    retry_count: int = 0
    decisions: list[str] = field(default_factory=list)

    def snapshot(self) -> str:
        lines = [
            f"MCU: {self.mcu}",
            f"Phase: {self.phase.value}",
            f"Task: {self.current_task or '-'}",
            f"Done: {', '.join(self.files_done) if self.files_done else '-'}",
            f"In progress: {self.file_in_progress or '-'}",
            f"Deps: {self.dependencies or '-'}",
        ]
        if self.last_error:
            lines.append(f"Last error: {self.last_error[:200]}")
        if self.decisions:
            lines.append("Decisions: " + "; ".join(self.decisions[-5:]))
        return "\n".join(lines)

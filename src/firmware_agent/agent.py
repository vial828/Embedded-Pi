from __future__ import annotations

from pathlib import Path

from firmware_agent.config import load_config
from firmware_agent.context.assembler import ContextAssembler
from firmware_agent.llm.client import LLMClient
from firmware_agent.memory.store import ConstraintRecord, DecisionRecord, MemoryStore
from firmware_agent.planner import TaskPlanner
from firmware_agent.state import WorkingState
from firmware_agent.verifier.base import Verifier


class FirmwareAgent:
    def __init__(self, project_dir: str):
        self.project_dir = Path(project_dir)
        self.workspace_dir = self._resolve_workspace_dir(self.project_dir)
        self.config = load_config(self.workspace_dir / "config.yaml")
        self.state = WorkingState(mcu=self.config.project.name)
        self.planner = TaskPlanner()
        self.assembler = ContextAssembler(self.config, str(self.workspace_dir))
        self.llm = LLMClient()
        self.verifier = Verifier()
        self.memory = MemoryStore(self.workspace_dir)
        self._bootstrap_memory_constraints()

    @staticmethod
    def _resolve_workspace_dir(project_dir: Path) -> Path:
        docs_dir = project_dir / "Docs"
        if (docs_dir / "config.yaml").exists():
            return docs_dir
        if (project_dir / "config.yaml").exists():
            return project_dir
        # default to Docs-first layout
        return docs_dir

    def _bootstrap_memory_constraints(self) -> None:
        if self.memory.long_memory.constraints:
            return
        self.memory.add_constraint(
            ConstraintRecord(
                constraint_id="C-001",
                rule="Do not infer missing hardware/register values; use NEED_CLARIFICATION.",
                severity="error",
                source="constitution",
                tags=["safety", "register"],
            )
        )
        self.memory.add_constraint(
            ConstraintRecord(
                constraint_id="C-002",
                rule="Driver initialization values must come from register-init artifacts, not fw-architecture prose.",
                severity="error",
                source="system-design",
                tags=["driver-init", "register-init"],
            )
        )

    def run(self, dry_run: bool = False) -> list[str]:
        logs: list[str] = []
        tasks = self.planner.plan()
        for task in tasks:
            self.state.current_task = task.description
            self.memory.persist_working_memory(self.state)
            long_memory_pack = self.memory.build_memory_pack(task)
            context = self.assembler.assemble(task, self.state, long_memory_pack=long_memory_pack)
            logs.append(f"TASK: {task.description}")
            if dry_run:
                logs.append("  dry-run: skip execution")
                continue

            _ = self.llm.generate(context)
            if task.needs_verification:
                result = self.verifier.verify(task.description)
                logs.append(f"  verify: {'PASS' if result.passed else 'FAIL'}")
                if not result.passed:
                    self.state.last_error = result.output
                    self.memory.persist_working_memory(self.state)
                    self.memory.append_delta("WORKING_ERROR", task.description)
                    break
            self.state.files_done.append(task.description)
            self.state.last_error = ""
            self.memory.persist_working_memory(self.state)
            self.memory.add_decision(
                DecisionRecord(
                    decision_id=f"D-{len(self.state.files_done):03d}",
                    content=f"Completed task: {task.description}",
                    rationale="Task execution finished in current phase",
                    source="agent.run",
                    scope="task",
                    tags=[task.type.value, task.peripheral or "generic"],
                )
            )
        return logs

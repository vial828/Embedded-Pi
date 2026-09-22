from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import json

from firmware_agent.state import Task, WorkingState


@dataclass
class DecisionRecord:
    decision_id: str
    content: str
    rationale: str
    source: str = "N/A"
    scope: str = "global"
    tags: list[str] = field(default_factory=list)


@dataclass
class ConstraintRecord:
    constraint_id: str
    rule: str
    severity: str = "error"
    source: str = "N/A"
    tags: list[str] = field(default_factory=list)


@dataclass
class TraceRecord:
    req_id: str
    artifact_type: str
    artifact_ref: str
    test_ref: str = "N/A"
    status: str = "planned"


@dataclass
class LongMemory:
    decisions: list[DecisionRecord] = field(default_factory=list)
    constraints: list[ConstraintRecord] = field(default_factory=list)
    traceability: list[TraceRecord] = field(default_factory=list)


class MemoryStore:
    """Two-layer memory store.

    - short_memory: working state snapshot
    - long_memory: decisions/constraints/traceability
    """

    def __init__(self, docs_root: Path):
        self.docs_root = docs_root
        self.base_dir = self.docs_root / "ai-generation" / "memory"
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.working_path = self.base_dir / "working_memory.json"
        self.long_path = self.base_dir / "long_memory.json"
        self.delta_path = self.base_dir / "memory_delta.log"

        self.long_memory = LongMemory()
        self.load()

    def load(self) -> None:
        if not self.long_path.exists():
            self.persist_long_memory()
            return
        data = json.loads(self.long_path.read_text(encoding="utf-8") or "{}")
        self.long_memory = LongMemory(
            decisions=[DecisionRecord(**item) for item in data.get("decisions", [])],
            constraints=[ConstraintRecord(**item) for item in data.get("constraints", [])],
            traceability=[TraceRecord(**item) for item in data.get("traceability", [])],
        )

    def persist_long_memory(self) -> None:
        payload = {
            "decisions": [asdict(d) for d in self.long_memory.decisions],
            "constraints": [asdict(c) for c in self.long_memory.constraints],
            "traceability": [asdict(t) for t in self.long_memory.traceability],
        }
        self.long_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def persist_working_memory(self, state: WorkingState) -> None:
        payload = {
            "mcu": state.mcu,
            "phase": state.phase.value,
            "current_task": state.current_task,
            "files_done": state.files_done,
            "file_in_progress": state.file_in_progress,
            "dependencies": state.dependencies,
            "last_error": state.last_error,
            "retry_count": state.retry_count,
        }
        self.working_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def append_delta(self, action: str, detail: str) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        with self.delta_path.open("a", encoding="utf-8") as f:
            f.write(f"{ts}\t{action}\t{detail}\n")

    def add_decision(self, record: DecisionRecord) -> None:
        self.long_memory.decisions.append(record)
        self.persist_long_memory()
        self.append_delta("ADD_DECISION", record.decision_id)

    def add_constraint(self, record: ConstraintRecord) -> None:
        self.long_memory.constraints.append(record)
        self.persist_long_memory()
        self.append_delta("ADD_CONSTRAINT", record.constraint_id)

    def upsert_trace(self, record: TraceRecord) -> None:
        for i, item in enumerate(self.long_memory.traceability):
            if item.req_id == record.req_id and item.artifact_ref == record.artifact_ref:
                self.long_memory.traceability[i] = record
                self.persist_long_memory()
                self.append_delta("UPDATE_TRACE", f"{record.req_id}:{record.artifact_ref}")
                return
        self.long_memory.traceability.append(record)
        self.persist_long_memory()
        self.append_delta("ADD_TRACE", f"{record.req_id}:{record.artifact_ref}")

    def build_memory_pack(self, task: Task, max_items: int = 5) -> str:
        """Return minimal long-memory pack relevant to current task."""
        periph = (task.peripheral or "").lower()
        req = (task.requirement_id or "").strip()

        decision_candidates = self.long_memory.decisions
        if periph:
            decision_candidates = [
                d for d in decision_candidates if any(periph in tag.lower() for tag in d.tags)
            ] or decision_candidates
        if req:
            decision_candidates = [
                d for d in decision_candidates if req in d.content or req in d.rationale
            ] or decision_candidates

        decisions = decision_candidates[-max_items:]
        constraints = self.long_memory.constraints[-max_items:]
        traces = self.long_memory.traceability[-max_items:]

        lines: list[str] = ["LongMemory:"]

        if decisions:
            lines.append("Decisions:")
            for d in decisions:
                lines.append(f"- {d.decision_id}: {d.content} | reason={d.rationale}")

        if constraints:
            lines.append("Constraints:")
            for c in constraints:
                lines.append(f"- {c.constraint_id}: ({c.severity}) {c.rule}")

        if traces:
            lines.append("Traceability:")
            for t in traces:
                lines.append(
                    f"- {t.req_id} -> {t.artifact_type}:{t.artifact_ref} [{t.status}]"
                )

        if len(lines) == 1:
            lines.append("- N/A")

        return "\n".join(lines)

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path


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


class LongMemoryStore:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.long_path = self.base_dir / "long_memory.json"
        self.delta_path = self.base_dir / "memory_delta.log"
        self.long_memory = LongMemory()
        self.load()

    def load(self) -> None:
        if not self.long_path.exists():
            self.persist()
            return
        data = json.loads(self.long_path.read_text(encoding="utf-8") or "{}")
        self.long_memory = LongMemory(
            decisions=[DecisionRecord(**item) for item in data.get("decisions", [])],
            constraints=[ConstraintRecord(**item) for item in data.get("constraints", [])],
            traceability=[TraceRecord(**item) for item in data.get("traceability", [])],
        )

    def persist(self) -> None:
        payload = {
            "decisions": [asdict(d) for d in self.long_memory.decisions],
            "constraints": [asdict(c) for c in self.long_memory.constraints],
            "traceability": [asdict(t) for t in self.long_memory.traceability],
        }
        self.long_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def append_delta(self, action: str, detail: str) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        with self.delta_path.open("a", encoding="utf-8") as f:
            f.write(f"{ts}\t{action}\t{detail}\n")

    def add_decision(self, record: DecisionRecord) -> None:
        self.long_memory.decisions.append(record)
        self.persist()
        self.append_delta("ADD_DECISION", record.decision_id)

    def add_constraint(self, record: ConstraintRecord) -> None:
        self.long_memory.constraints.append(record)
        self.persist()
        self.append_delta("ADD_CONSTRAINT", record.constraint_id)

    def upsert_trace(self, record: TraceRecord) -> None:
        for i, item in enumerate(self.long_memory.traceability):
            if item.req_id == record.req_id and item.artifact_ref == record.artifact_ref:
                self.long_memory.traceability[i] = record
                self.persist()
                self.append_delta("UPDATE_TRACE", f"{record.req_id}:{record.artifact_ref}")
                return
        self.long_memory.traceability.append(record)
        self.persist()
        self.append_delta("ADD_TRACE", f"{record.req_id}:{record.artifact_ref}")

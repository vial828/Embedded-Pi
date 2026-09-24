from __future__ import annotations

from pathlib import Path

from firmware_agent.slices.S12_Working_Memory.working_memory import WorkingMemoryStore
from firmware_agent.slices.S13_Long_Memory.long_memory import (
    ConstraintRecord,
    DecisionRecord,
    LongMemory,
    LongMemoryStore,
    TraceRecord,
)
from firmware_agent.slices.S16_Memory_Recall_Strategy.recall_strategy import build_memory_pack as _build_memory_pack
from firmware_agent.state import Task, WorkingState


class MemoryStore:
    """Two-layer memory store.

    - short_memory: working state snapshot
    - long_memory: decisions/constraints/traceability
    """

    def __init__(self, docs_root: Path):
        self.docs_root = docs_root
        self.base_dir = self.docs_root / "ai-generation" / "memory"
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self._working = WorkingMemoryStore(self.base_dir)
        self._long = LongMemoryStore(self.base_dir)

        self.working_path = self._working.working_path
        self.long_path = self._long.long_path
        self.delta_path = self._long.delta_path

    @property
    def long_memory(self) -> LongMemory:
        return self._long.long_memory

    def load(self) -> None:
        self._long.load()

    def persist_long_memory(self) -> None:
        self._long.persist()

    def persist_working_memory(self, state: WorkingState) -> None:
        self._working.persist(state)

    def append_delta(self, action: str, detail: str) -> None:
        self._long.append_delta(action, detail)

    def add_decision(self, record: DecisionRecord) -> None:
        self._long.add_decision(record)

    def add_constraint(self, record: ConstraintRecord) -> None:
        self._long.add_constraint(record)

    def upsert_trace(self, record: TraceRecord) -> None:
        self._long.upsert_trace(record)

    def build_memory_pack(self, task: Task, max_items: int = 5) -> str:
        return _build_memory_pack(self.long_memory, task, max_items=max_items)

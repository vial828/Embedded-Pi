from pathlib import Path

from firmware_agent.memory.store import ConstraintRecord, MemoryStore
from firmware_agent.project_layout import ensure_project_layout
from firmware_agent.state import Task, TaskType, WorkingState


def test_memory_store_persist_and_pack(tmp_path: Path):
    project = tmp_path / "mem-demo"
    ensure_project_layout(project)
    docs_root = project / "Docs"

    store = MemoryStore(docs_root)
    state = WorkingState(mcu="demo")
    state.current_task = "test"
    store.persist_working_memory(state)

    store.add_constraint(
        ConstraintRecord(
            constraint_id="C-TST",
            rule="No semantic guessing",
            severity="error",
            source="test",
            tags=["safety"],
        )
    )

    task = Task(TaskType.DRIVER_IMPL, "Driver task", peripheral="UART1")
    pack = store.build_memory_pack(task)

    assert "LongMemory:" in pack
    assert "Constraints:" in pack
    assert (docs_root / "ai-generation" / "memory" / "working_memory.json").exists()
    assert (docs_root / "ai-generation" / "memory" / "long_memory.json").exists()

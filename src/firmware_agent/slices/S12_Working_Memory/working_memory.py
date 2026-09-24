from __future__ import annotations

import json
from pathlib import Path

from firmware_agent.state import WorkingState


class WorkingMemoryStore:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.working_path = self.base_dir / "working_memory.json"

    def persist(self, state: WorkingState) -> None:
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

from __future__ import annotations

from pathlib import Path

from firmware_agent.config import AppConfig
from firmware_agent.slices.S17_Context_Assembler.constitution import load_constitution
from firmware_agent.slices.S17_Context_Assembler.token_counter import estimate_tokens
from firmware_agent.state import Task, WorkingState


class ContextAssembler:
    def __init__(self, config: AppConfig, project_root: str):
        self.config = config
        constitution_path = Path(project_root) / config.context.constitution_file
        self.constitution = load_constitution(str(constitution_path.resolve()))
        self.max_tokens = config.context.max_tokens

    def assemble(self, task: Task, state: WorkingState, long_memory_pack: str = "") -> str:
        parts = [
            self.constitution,
            state.snapshot(),
        ]
        if long_memory_pack:
            parts.append(long_memory_pack)
        parts.append(f"Task: {task.description}")
        context = "\n\n".join(parts)
        return self._enforce_limit(context)

    def _enforce_limit(self, context: str) -> str:
        if estimate_tokens(context) <= self.max_tokens:
            return context
        # M0: hard truncate as fallback
        max_chars = self.max_tokens * 4
        return context[:max_chars]

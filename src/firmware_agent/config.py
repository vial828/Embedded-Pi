from __future__ import annotations

from pathlib import Path
import os

import yaml
from pydantic import BaseModel, Field


class ContextConfig(BaseModel):
    max_tokens: int | None = Field(default=None, ge=256)
    constitution_file: str = "./standards/constitution.md"
    reserve_tokens: int = Field(default=8192, ge=1024)


class LLMConfig(BaseModel):
    provider: str = "openai_compatible"
    model: str = "Qwen3.8-27B"
    max_tokens: int = 8192
    temperature: float = 0.1
    base_url: str | None = None
    context_length: int | None = Field(default=None, ge=8192)


class ProjectConfig(BaseModel):
    name: str = "unnamed"


class AppConfig(BaseModel):
    project: ProjectConfig = ProjectConfig()
    context: ContextConfig = ContextConfig()
    llm: LLMConfig = LLMConfig()

    def resolved_context_tokens(self) -> int:
        max_context = self.llm.context_length or _infer_model_context_length(self.llm.model)
        budget = self.context.max_tokens
        if budget is None:
            budget = max_context - self.context.reserve_tokens
        return max(256, min(budget, max_context - 256))


def _infer_model_context_length(model: str) -> int:
    normalized = model.lower()
    if "qwen3.8" in normalized or "qwen3" in normalized:
        return 262144
    if "llama" in normalized:
        return 131072
    if "gpt-4.1" in normalized:
        return 1048576
    return int(os.getenv("PI_MODEL_CONTEXT_LENGTH", "262144"))


def load_config(path: str | Path) -> AppConfig:
    p = Path(path)
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    cfg = AppConfig.model_validate(data)
    env_ctx = os.getenv("PI_CONTEXT_MAX_TOKENS")
    if env_ctx:
        cfg.context.max_tokens = int(env_ctx)
    env_model_ctx = os.getenv("PI_MODEL_CONTEXT_LENGTH")
    if env_model_ctx:
        cfg.llm.context_length = int(env_model_ctx)
    if cfg.context.max_tokens is None:
        cfg.context.max_tokens = cfg.resolved_context_tokens()
    return cfg

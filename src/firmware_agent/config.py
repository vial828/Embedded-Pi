from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ContextConfig(BaseModel):
    max_tokens: int = Field(default=3000, ge=256)
    constitution_file: str = "./standards/constitution.md"


class LLMConfig(BaseModel):
    provider: str = "openai_compatible"
    model: str = "Qwen3.8-27B"
    max_tokens: int = 8192
    temperature: float = 0.1
    base_url: str | None = None


class ProjectConfig(BaseModel):
    name: str = "unnamed"


class AppConfig(BaseModel):
    project: ProjectConfig = ProjectConfig()
    context: ContextConfig = ContextConfig()
    llm: LLMConfig = LLMConfig()


def load_config(path: str | Path) -> AppConfig:
    p = Path(path)
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return AppConfig.model_validate(data)

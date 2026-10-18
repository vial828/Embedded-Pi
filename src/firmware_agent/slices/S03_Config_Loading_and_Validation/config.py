"""S03 - Config loading and validation.

Contract for project configuration. Two rules drive the whole module:

1. No silent defaults for anything that changes *what runs*. A default provider,
   model, compiler or MCU part would make an unconfigured project look healthy
   while it targets hardware and toolchains nobody chose.
2. "Still the generated template" is a recorded fact, not a guess. S02 stamps
   `template: true` into the config it generates; this module reads that stamp
   instead of sniffing values. That is what lets strict validation coexist with
   a scaffolded project: the loader can say "structurally valid, not yet
   configured" without pretending the placeholder is a choice.

Structural paths (registers/, bsp/, standards/) are architecture, owned by the
S02 layout contract, not user configuration. They are accepted here only as
overrides and must stay project-relative so a project directory keeps working
when it moves between machines.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

__all__ = [
    "REQUIRED_KEYS",
    "SUPPORTED_PROVIDERS",
    "AppConfig",
    "ConfigError",
    "ContextConfig",
    "GateConfig",
    "LLMConfig",
    "McuConfig",
    "PathsConfig",
    "ProjectConfig",
    "ToolchainConfig",
    "config_candidates",
    "load_config",
    "load_project_config",
]

# Providers with a real client implementation. Anything else must fail at load
# time: an unknown provider string that quietly fell back would send the project
# to a model nobody picked.
SUPPORTED_PROVIDERS = {"openai_compatible", "stub"}

CONFIG_RELATIVE_PATHS = ("Docs/config.yaml", "config.yaml")


# Values that decide what runs. Each carries the reason a default would be harm-
# ful, so the error tells the reader what they would have been trusting instead
# of just repeating a key name.
REQUIRED_KEYS: dict[str, str] = {
    "project.name": "it names the build artifact and appears in every report",
    "mcu.part": "a default part number generates firmware for a chip nobody chose",
    "toolchain.compiler": "a default compiles with a toolchain nobody selected",
    "llm.provider": "the provider decides which service receives the project's source",
    "llm.model": "the model decides who does the reasoning",
}

# Sections that may be omitted (or left empty) because their defaults change cost
# or budget, not what gets produced.
OPTIONAL_SECTIONS = ("context", "paths", "gate")


class ConfigError(Exception):
    """Configuration cannot be used. Always names the file and the dotted key."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectConfig(_StrictModel):
    name: str = Field(
        ...,
        description="Project identifier. Required: it names the artifact and appears in every report.",
        min_length=1,
    )
    description: str = ""


class McuConfig(_StrictModel):
    part: str = Field(
        ...,
        description="Target part number. Required: a default would generate code for a chip nobody chose.",
        min_length=1,
    )


class ToolchainConfig(_StrictModel):
    compiler: str = Field(
        ...,
        description="Compiler executable or absolute path. Required: a default would compile with an unchosen toolchain.",
        min_length=1,
    )
    objcopy: str | None = None

    def resolved_objcopy(self) -> str:
        """Derive objcopy from the compiler, keeping its directory.

        Derivation, not a guess: objcopy comes from the same toolchain as the
        compiler, so it cannot drift the way a literal default would. When the
        compiler is not gcc-shaped there is nothing honest to derive, so the
        config has to say - a wrong binutils tool is a corrupt image, not a typo.
        """
        if self.objcopy:
            return self.objcopy
        compiler = Path(self.compiler)
        name = compiler.name
        if name.endswith("gcc"):
            return str(compiler.with_name(f"{name[:-3]}objcopy"))
        raise ConfigError(
            f"toolchain.objcopy is not set and cannot be derived from {self.compiler!r}. "
            "Set toolchain.objcopy explicitly."
        )


class PathsConfig(_StrictModel):
    """Overrides for layout-owned directories. Must stay project-relative."""

    registers: str = "./hardware/registers/"
    bsp: str = "./bsp/"
    schematic: str = "./hardware/schematic/"
    coding_standard: str = "./standards/coding_standard.md"
    process_spec: str = "./standards/process_spec.yaml"

    @field_validator("registers", "bsp", "schematic", "coding_standard", "process_spec")
    @classmethod
    def _must_be_project_relative(cls, value: str) -> str:
        """Reject machine-specific paths so the project directory stays portable.

        This project is edited from two machines with different filesystems; an
        absolute path or a parent escape makes the config work on exactly one of
        them and fail somewhere else, far from the cause.
        """
        candidate = PurePosixPath(value.replace("\\", "/"))
        if candidate.is_absolute() or value[1:2] == ":" or ".." in candidate.parts:
            raise ValueError("must be project-relative (no absolute paths, drive letters, or '..')")
        return value

    @property
    def absolute(self) -> dict[str, str]:
        return {name: value for name, value in self.model_dump().items()}


class ContextConfig(_StrictModel):
    max_tokens: int | None = Field(default=None, ge=256)
    constitution_file: str = "./standards/constitution.md"
    reserve_tokens: int = Field(default=8192, ge=1024)


class LLMConfig(_StrictModel):
    provider: str = Field(..., description="Must name a provider with a client implementation.")
    model: str = Field(..., min_length=1, description="Model id. Required: it decides who does the reasoning.")
    max_tokens: int = Field(default=8192, ge=1)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    base_url: str | None = None
    context_length: int | None = Field(default=None, ge=8192)

    @property
    def is_stub(self) -> bool:
        return self.provider == "stub"


class GateConfig(_StrictModel):
    """Quality/input gates. Every default keeps the gate armed."""

    allow_missing_inputs: bool = Field(
        default=False,
        description="Persistent waiver for missing external inputs. Off by default: a gate must never be open by default.",
    )


class AppConfig(_StrictModel):
    # Stamped by S02 when it generates the file. True means "valid shape, values
    # are still placeholders" - reportable, and never to be treated as configured.
    template: bool = False

    project: ProjectConfig = Field(...)
    mcu: McuConfig = Field(...)
    toolchain: ToolchainConfig = Field(...)
    llm: LLMConfig = Field(...)
    context: ContextConfig = ContextConfig()
    paths: PathsConfig = PathsConfig()
    gate: GateConfig = GateConfig()

    # Runtime metadata, never configured: where the config came from and whether
    # it is still the generated template.
    source_path: Path | None = Field(default=None, exclude=True)
    provenance: str = Field(default="user", exclude=True)

    @property
    def is_template(self) -> bool:
        return self.template or self.provenance == "template"

    def resolved_context_tokens(self) -> int:
        max_context = self.llm.context_length or _infer_model_context_length(self.llm.model)
        budget = self.context.max_tokens
        if budget is None:
            budget = max_context - self.context.reserve_tokens
        return max(256, min(budget, max_context - 256))

    def compiler_exists(self) -> bool:
        """Whether the configured compiler is reachable. False is a finding, not an error."""
        from shutil import which

        compiler = Path(self.toolchain.compiler)
        if compiler.is_absolute() or compiler.parent != Path("."):
            return compiler.exists()
        return which(self.toolchain.compiler) is not None


def _infer_model_context_length(model: str) -> int:
    normalized = model.lower()
    if "qwen3" in normalized:
        return 262144
    if "llama" in normalized:
        return 131072
    if "gpt-4.1" in normalized:
        return 1048576
    return int(os.getenv("PI_MODEL_CONTEXT_LENGTH", "262144"))


def config_candidates(root: Path) -> list[Path]:
    return [root / relative for relative in CONFIG_RELATIVE_PATHS]


def load_project_config(root: Path) -> AppConfig:
    """Load the project's configuration, resolving the canonical location.

    A missing config is an error, not a default project: `epi` would otherwise
    run against a project whose target, toolchain and model are all invented.
    """
    candidates = config_candidates(Path(root))
    for candidate in candidates:
        if candidate.exists():
            return load_config(candidate)
    tried = ", ".join(str(path) for path in candidates)
    raise ConfigError(
        f"no project configuration found (looked for: {tried}). "
        f"Run `epi {root}` to scaffold one, then fill in project/mcu/toolchain/llm."
    )


def load_config(path: str | Path) -> AppConfig:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"configuration file not found: {path}")

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level, got {type(data).__name__}")

    template = bool(data.get("template", False))
    _check_required_keys(data, path)
    data = _without_empty_optional_sections(data)
    try:
        cfg = AppConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"{path}:\n" + "\n".join(_describe(err) for err in exc.errors())) from exc

    _apply_env_overrides(cfg)
    if cfg.context.max_tokens is None:
        cfg.context.max_tokens = cfg.resolved_context_tokens()

    cfg.source_path = path
    cfg.provenance = "template" if template else "user"
    if cfg.llm.provider not in SUPPORTED_PROVIDERS:
        raise ConfigError(
            f"{path}: llm.provider = {cfg.llm.provider!r} has no client implementation. "
            f"Supported: {', '.join(sorted(SUPPORTED_PROVIDERS))}."
        )
    return cfg


def _check_required_keys(data: dict, path: Path) -> None:
    """Report every missing required value by dotted key, before type validation.

    Pydantic alone reports an empty section as "input should be a valid
dictionary", which sends the reader looking at the wrong line. This pass names
    the exact key and why it is not allowed to default.
    """
    problems = []
    for dotted, reason in REQUIRED_KEYS.items():
        section, _, key = dotted.partition(".")
        value = data.get(section)
        node = value.get(key) if isinstance(value, dict) else None
        if node is None or (isinstance(node, str) and not node.strip()):
            line = f"  {dotted}: required value missing - {reason}"
            near = _near_miss(key, value) if isinstance(value, dict) else []
            if near:
                line += f"\n      {section}.{near[0]} looks like a typo for {dotted} - fix the key name"
            problems.append(line)
    if problems:
        raise ConfigError(f"{path}:\n" + "\n".join(problems))


def _near_miss(key: str, section: dict) -> list[str]:
    """Spot a misspelled sibling so the reader sees the cause, not just the rule."""
    import difflib

    return difflib.get_close_matches(key, [k for k in section if k != key], n=1, cutoff=0.8)


def _without_empty_optional_sections(data: dict) -> dict:
    """Treat an empty optional section as omitted, so its defaults apply."""
    return {k: v for k, v in data.items() if not (k in OPTIONAL_SECTIONS and v is None)}


def _describe(err: dict) -> str:
    key = ".".join(str(part) for part in err["loc"]) or "<root>"
    kind = err["type"]
    if kind == "missing":
        return f"  {key}: required value missing - refusing to default it"
    if kind == "extra_forbidden":
        return f"  {key}: unknown setting (typo, or a feature this version does not have)"
    return f"  {key}: {err['msg']}"


def _apply_env_overrides(cfg: AppConfig) -> None:
    env_ctx = os.getenv("PI_CONTEXT_MAX_TOKENS")
    if env_ctx:
        cfg.context.max_tokens = int(env_ctx)
    env_model_ctx = os.getenv("PI_MODEL_CONTEXT_LENGTH")
    if env_model_ctx:
        cfg.llm.context_length = int(env_model_ctx)

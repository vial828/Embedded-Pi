"""P0-2: S03 configuration loading. The rule under test is "no silent defaults"."""

from __future__ import annotations

from pathlib import Path

import pytest

from firmware_agent.config import (
    SUPPORTED_PROVIDERS,
    ConfigError,
    load_config,
    load_project_config,
)
from firmware_agent.project_layout import ensure_project_layout

# A configured project: no `template: true`, every value chosen on purpose.
VALID = """
project:
  name: "brake-controller"
mcu:
  part: "STM32F407VGT6"
toolchain:
  compiler: "arm-none-eabi-gcc"
llm:
  provider: "openai_compatible"
  model: "Qwen3.8-27B"
"""


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    ensure_project_layout(root)
    return root


def write_config(root: Path, text: str) -> Path:
    path = root / "Docs" / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_generated_template_loads_and_admits_being_a_template(project: Path) -> None:
    cfg = load_project_config(project)
    assert cfg.is_template is True, "S02 stamps `template: true`; S03 must read it, not guess"
    assert cfg.gate.allow_missing_inputs is False, "a gate that is open by default is not a gate"
    assert cfg.provenance == "template"


def test_configured_project_is_not_a_template(project: Path) -> None:
    write_config(project, VALID)
    cfg = load_project_config(project)
    assert cfg.is_template is False
    assert cfg.project.name == "brake-controller"
    assert cfg.toolchain.compiler == "arm-none-eabi-gcc"
    assert cfg.llm.provider == "openai_compatible"


def test_missing_file_names_every_candidate(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as err:
        load_project_config(tmp_path)
    # Separator-agnostic on purpose: the assertion is about *which candidates were
    # searched*, and on Windows Path renders them with backslashes.
    message = str(err.value).replace("\\", "/")
    assert "Docs/config.yaml" in message and "config.yaml" in message


def test_missing_required_value_is_refused_not_defaulted(project: Path) -> None:
    write_config(project, VALID.replace('  compiler: "arm-none-eabi-gcc"\n', ""))
    with pytest.raises(ConfigError) as err:
        load_project_config(project)
    assert "toolchain.compiler" in str(err.value)


def test_missing_mcu_is_refused(project: Path) -> None:
    # A default part number would generate firmware for a chip nobody chose.
    write_config(project, VALID.replace('mcu:\n  part: "STM32F407VGT6"\n', ""))
    with pytest.raises(ConfigError) as err:
        load_project_config(project)
    assert "mcu" in str(err.value)


def test_project_name_never_defaults_to_unnamed(project: Path) -> None:
    write_config(project, VALID.replace('  name: "brake-controller"\n', ""))
    with pytest.raises(ConfigError) as err:
        load_project_config(project)
    assert "project.name" in str(err.value)


def test_typo_is_rejected_instead_of_ignored(project: Path) -> None:
    write_config(project, VALID.replace("provider:", "provder:"))
    with pytest.raises(ConfigError) as err:
        load_project_config(project)
    assert "llm.provder" in str(err.value)


def test_unknown_provider_fails_at_load_time(project: Path) -> None:
    write_config(project, VALID.replace("openai_compatible", "claude_happy"))
    with pytest.raises(ConfigError) as err:
        load_project_config(project)
    message = str(err.value)
    assert "claude_happy" in message
    for provider in SUPPORTED_PROVIDERS:
        assert provider in message


def test_broken_yaml_is_a_config_error(project: Path) -> None:
    write_config(project, "project: [unclosed\n")
    with pytest.raises(ConfigError) as err:
        load_project_config(project)
    assert "invalid YAML" in str(err.value)


def test_paths_must_stay_project_relative(project: Path) -> None:
    # Two machines, different filesystems: an absolute path works on exactly one.
    write_config(project, VALID + '\npaths:\n  bsp: "C:/Users/viarl/bsp/"\n')
    with pytest.raises(ConfigError) as err:
        load_project_config(project)
    assert "paths.bsp" in str(err.value)

    write_config(project, VALID + '\npaths:\n  bsp: "../shared-bsp/"\n')
    with pytest.raises(ConfigError):
        load_project_config(project)


def test_objcopy_is_derived_from_the_compiler_not_guessed(project: Path) -> None:
    cfg = load_config(write_config(project, VALID))
    assert cfg.toolchain.resolved_objcopy() == "arm-none-eabi-objcopy"

    # Derivation keeps the directory: objcopy must come from the same toolchain.
    write_config(project, VALID.replace("arm-none-eabi-gcc", "/opt/ti/bin/arm-none-eabi-gcc"))
    assert load_config(project / "Docs/config.yaml").toolchain.resolved_objcopy() == \
        "/opt/ti/bin/arm-none-eabi-objcopy"


def test_objcopy_cannot_be_invented_from_a_non_gcc_compiler(project: Path) -> None:
    write_config(project, VALID.replace("arm-none-eabi-gcc", "armclang"))
    with pytest.raises(ConfigError) as err:
        load_config(project / "Docs/config.yaml").toolchain.resolved_objcopy()
    assert "toolchain.objcopy" in str(err.value)

    explicit = VALID.replace('  compiler: "arm-none-eabi-gcc"',
                             '  compiler: "armclang"\n  objcopy: "/opt/arm/bin/llvm-objcopy"')
    write_config(project, explicit)
    assert load_config(project / "Docs/config.yaml").toolchain.resolved_objcopy() == "/opt/arm/bin/llvm-objcopy"


def test_environment_overrides_still_apply(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PI_CONTEXT_MAX_TOKENS", "4096")
    assert load_config(write_config(project, VALID)).context.max_tokens == 4096


def test_context_budget_is_computed_not_assumed(project: Path) -> None:
    cfg = load_config(write_config(project, VALID))
    assert cfg.context.max_tokens == cfg.resolved_context_tokens()
    assert cfg.context.max_tokens > 0


def test_config_gate_waives_the_input_gate(project: Path) -> None:
    from firmware_agent.workflow import WorkflowRunner

    write_config(project, VALID + "\ngate:\n  allow_missing_inputs: true\n")
    runner = WorkflowRunner(project)
    assert runner._missing_required_paths(), "fixture must still be missing real inputs"
    runner._apply_missing_waiver()
    assert runner._detect_prd_ready() == []
    assert runner.state.waived_by == "config", "the state file must say who waived"

    # Turning it back off in the file re-arms the gate on the next run.
    write_config(project, VALID)
    reloaded = WorkflowRunner(project)
    reloaded._apply_missing_waiver()
    assert reloaded.state.waived_missing == []
    assert reloaded._detect_prd_ready()

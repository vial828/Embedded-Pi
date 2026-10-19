"""S17 must write the prompt down as it builds it - the journal is not opt-in."""

from __future__ import annotations

from pathlib import Path

import pytest

from firmware_agent.config import load_config
from firmware_agent.project_layout import ensure_project_layout
from firmware_agent.slices.S17_Context_Assembler.assembler import ContextAssembler
from firmware_agent.slices.S17_Context_Assembler.prompt_journal import (
    JOURNAL_DIR_RELATIVE,
)
from firmware_agent.state import Phase, Task, TaskType, WorkingState

CONFIG = """
project:
  name: "heater"
mcu:
  part: "CY8C6245FNI-S3D41"
toolchain:
  compiler: "arm-none-eabi-gcc"
llm:
  provider: "openai_compatible"
  model: "Qwen3.8-27B"
context:
  max_tokens: {max_tokens}
"""


def build(tmp_path: Path, max_tokens: int = 8192) -> ContextAssembler:
    root = tmp_path / "proj"
    ensure_project_layout(root)
    (root / "Docs" / "config.yaml").write_text(CONFIG.format(max_tokens=max_tokens), encoding="utf-8")
    config = load_config(root / "Docs" / "config.yaml")
    return ContextAssembler(config, str(root / "Docs"), journal_root=root)


def task(description: str = "实现 BQ25622 的 init") -> Task:
    return Task(type=TaskType.DRIVER_IMPL, description=description, requirement_id="R-013")


def state() -> WorkingState:
    return WorkingState(mcu="CY8C6245FNI-S3D41", phase=Phase.IMPLEMENTATION, current_task="driver")


def test_every_assembly_is_written_down_without_being_asked(tmp_path: Path) -> None:
    assembler = build(tmp_path)

    prompt = assembler.assemble(task(), state())

    records = assembler.journal.records()
    assert len(records) == 1
    assert assembler.journal.restore(records[0]["seq"]) == prompt
    assert assembler.journal.verify(records[0]["seq"]).ok is True


def test_a_task_switch_keeps_its_own_full_view(tmp_path: Path) -> None:
    assembler = build(tmp_path)
    assembler.assemble(task("第一个任务"), state())
    assembler.assemble(task("第二个任务"), state())

    first, second = (assembler.journal.restore(r["seq"]) for r in assembler.journal.records())
    assert "第一个任务" in first and "第二个任务" not in first
    assert "第二个任务" in second


def test_each_fragment_states_where_it_came_from(tmp_path: Path) -> None:
    assembler = build(tmp_path)
    assembler.assemble(task(), state())
    record = assembler.journal.records()[0]
    sections = {entry["section"]: entry for entry in record["fragments"]}

    constitution = sections["constitution"]["provenance"]
    assert constitution["origin"] == "source" and constitution["doc"].endswith(".md")
    assert sections["task"]["provenance"]["origin"] == "generated"
    assert sections["task"]["provenance"]["ref"] == "task:driver_impl:R-013"


def test_recalled_memory_is_marked_generated_not_source(tmp_path: Path) -> None:
    """Recalled memory can be previous model output; unmarked, it re-enters as fact."""
    assembler = build(tmp_path)

    assembler.assemble(task(), state(), long_memory_pack="上次结论：BQ25622 用 I2C1")

    record = assembler.journal.records()[0]
    memory = next(e for e in record["fragments"] if e["section"] == "long memory")
    assert memory["provenance"]["origin"] == "generated"


def test_over_budget_drops_an_optional_fragment_and_records_it(tmp_path: Path) -> None:
    assembler = build(tmp_path, max_tokens=256)

    prompt = assembler.assemble(task(), state(), long_memory_pack="回忆内容" * 4000)

    record = assembler.journal.records()[0]
    assert [d["section"] for d in record["dropped"]] == ["long memory"]
    assert "回忆内容" not in prompt
    assert "BQ25622" in prompt, "the task must never be what gets cut"


def test_a_prompt_is_never_clipped_to_fit(tmp_path: Path) -> None:
    """Half a memory pack reads exactly like a whole one, so it is dropped, not cut."""
    assembler = build(tmp_path, max_tokens=256)

    assembler.assemble(task(), WorkingState(mcu="m", dependencies="依赖" * 200))

    record = assembler.journal.records()[-1]
    assert all("transform" not in entry for entry in record["fragments"])
    assert record["fragments"], "the prompt still went out with its required fragments"


def test_a_failed_assembly_is_still_written_down(tmp_path: Path) -> None:
    """Otherwise 'what was it about to send?' is unanswerable after the only clue is an exception."""
    assembler = build(tmp_path, max_tokens=256)
    assembler.constitution_path.write_text("宪法" * 40000, encoding="utf-8")
    assembler.constitution = assembler.constitution_path.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="does not fit"):
        assembler.assemble(task(), state(), long_memory_pack="回忆内容" * 4000)

    record = assembler.journal.records()[-1]
    assert record["event"].startswith("assemble:failed")
    assert {d["section"] for d in record["dropped"]} == {"constitution", "working state", "long memory", "task"}


def test_a_prompt_that_cannot_fit_fails_instead_of_losing_its_task(tmp_path: Path) -> None:
    assembler = build(tmp_path, max_tokens=256)
    assembler.constitution_path.write_text("宪法" * 40000, encoding="utf-8")
    assembler.constitution = assembler.constitution_path.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="does not fit"):
        assembler.assemble(task(), state())


def test_the_journal_lives_at_the_project_root_not_the_docs_dir(tmp_path: Path) -> None:
    assembler = build(tmp_path)

    assembler.assemble(task(), state())

    assert (assembler.journal.directory / "journal.jsonl").exists()
    assert assembler.journal.directory == assembler.project_root.parent / JOURNAL_DIR_RELATIVE
    assert not (assembler.project_root / ".epi").exists()

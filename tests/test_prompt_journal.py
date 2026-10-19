"""The prompt journal must reproduce the exact bytes, or say so. Everything here defends that."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from firmware_agent.slices.S17_Context_Assembler.prompt_journal import (
    DEFAULT_RECIPE,
    JOURNAL_DIR_RELATIVE,
    Fragment,
    PromptJournal,
    Provenance,
    RestoreMismatch,
    Transform,
)

ROOT = "test://unit"


def frag(section: str, text: str, origin: str = "source", transform=None, **kw) -> Fragment:
    return Fragment(role=kw.pop("role", "user"), section=section, text=text, transform=transform,
                    provenance=Provenance(origin=origin, ref=kw.pop("ref", f"{ROOT}#{section}"), **kw))


@pytest.fixture()
def journal(tmp_path: Path) -> PromptJournal:
    return PromptJournal(tmp_path)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def blobs(journal: PromptJournal) -> list[Path]:
    root = journal.directory / "store"
    return sorted(root.rglob("*.txt")) if root.exists() else []


# ------------------------------------------------------------------ exactness


def test_restored_bytes_match_what_was_assembled(journal: PromptJournal) -> None:
    fragments = [frag("宪法", "semantic_inference: forbidden"), frag("任务", "为 MOD-004 生成 init")]

    record = journal.record(task_id="S18/plan-1", event="assemble", fragments=fragments)

    restored = journal.restore(record["seq"])
    assert restored == "semantic_inference: forbidden\n\n为 MOD-004 生成 init"
    assert journal.verify(record["seq"]).ok is True


def test_the_provider_hash_is_part_of_the_agreement(journal: PromptJournal) -> None:
    """S20 records context_sha256 for what it actually sent; that is the anchor."""
    text = "只有这一段"
    record = journal.record(task_id="S22/compile", event="assemble", fragments=[frag("任务", text)],
                            provider_context_sha256=sha(text))

    assert journal.verify(record["seq"]).ok is True


def test_a_provider_hash_disagreement_is_reported_not_swallowed(journal: PromptJournal) -> None:
    record = journal.record(task_id="S22/compile", event="assemble", fragments=[frag("任务", "内容")],
                            provider_context_sha256="0" * 64)

    result = journal.verify(record["seq"])

    assert result.ok is False
    assert "provider" in result.detail


def test_a_tampered_blob_cannot_pass_as_the_original(journal: PromptJournal) -> None:
    record = journal.record(task_id="S18/plan-2", event="assemble", fragments=[frag("需求 R-013", "原文")])

    blob = blobs(journal)[0]
    blob.write_text("被改过", encoding="utf-8")

    assert journal.verify(record["seq"]).ok is False


def test_a_missing_blob_says_which_fragment_it_lost(journal: PromptJournal) -> None:
    """A store is only trustworthy if losing part of it is loud."""
    record = journal.record(task_id="S18/plan-4", event="assemble", fragments=[frag("宪法", "规则")])
    blobs(journal)[0].unlink()

    with pytest.raises(RestoreMismatch, match="宪法"):
        journal.restore(record["seq"])


def test_the_recipe_is_stored_per_record_so_it_can_change_later(journal: PromptJournal) -> None:
    recipe = {"join": "\n---\n", "fragment_template": "[{role}] {text}", "trailing_newline": True}
    record = journal.record(task_id="S18/plan-3", event="assemble",
                            fragments=[frag("宪法", "规则", role="system"), frag("任务", "做这个")], recipe=recipe)

    assert journal.restore(record["seq"]) == "[system] 规则\n---\n[user] 做这个\n"
    assert journal.verify(record["seq"]).ok is True
    assert DEFAULT_RECIPE["join"] == "\n\n", "the default must not be mutated by a caller's recipe"


# ----------------------------------------------------------------- dedup / size


def test_repeated_content_is_stored_once(journal: PromptJournal) -> None:
    shared = frag("宪法", "同一段规则被很多任务携带")
    journal.record(task_id="task-a", event="assemble", fragments=[shared, frag("任务", "A")])
    journal.record(task_id="task-b", event="assemble", fragments=[shared, frag("任务", "B")])

    assert len(blobs(journal)) == 3


def test_a_task_switch_costs_one_line_not_a_copy_of_the_prompt(journal: PromptJournal) -> None:
    big = "很长的上下文" * 500
    fragments = [frag("上下文", big), frag("任务", "第一个任务")]
    journal.record(task_id="task-a", event="assemble", fragments=fragments)

    switched = journal.record(task_id="task-b", event="task_switch:from=task-a",
                              fragments=[frag("上下文", big), frag("任务", "第二个任务")])

    second_line = journal.records()[1]
    assert len(json.dumps(second_line)) < len(big), "the manifest must not carry the content again"
    assert len(journal.restore(switched["seq"])) > len(big), "yet the full view is still complete"


def test_every_record_restores_its_own_full_view_without_replay(journal: PromptJournal) -> None:
    first = journal.record(task_id="a", event="assemble", fragments=[frag("宪法", "规则")])
    journal.record(task_id="b", event="assemble", fragments=[frag("宪法", "规则"), frag("任务", "后来的")])

    assert journal.restore(first["seq"]) == "规则"


# ------------------------------------------------- transforms and omissions


def test_a_truncation_is_recorded_as_parameters_not_just_result(journal: PromptJournal) -> None:
    full = "寄存器定义" * 200
    cut = full[:40]
    record = journal.record(
        task_id="S18/plan-9", event="assemble",
        fragments=[frag("寄存器", cut, transform=Transform(kind="truncate", source_sha256=sha(full),
                                                           from_chars=len(full), to_chars=len(cut)))],
    )

    entry = journal.record_at(record["seq"])["fragments"][0]
    assert entry["transform"] == {"kind": "truncate", "source_sha256": sha(full),
                                  "from_chars": len(full), "to_chars": len(cut)}
    assert journal.verify(record["seq"]).ok is True


def test_a_dropped_fragment_is_still_visible_in_the_full_view(journal: PromptJournal) -> None:
    """An incomplete prompt that looks complete is worse than no prompt view."""
    dropped = [{"section": "编码规范", "sha256": sha("规范全文"), "reason": "budget", "chars": 9000}]

    record = journal.record(task_id="S18/plan-10", event="assemble", fragments=[frag("任务", "做这个")],
                            dropped=dropped)

    assert journal.record_at(record["seq"])["dropped"] == dropped


def test_an_anonymous_fragment_is_refused(journal: PromptJournal) -> None:
    anonymous = Fragment(role="user", section="来路不明", text="内容", provenance=Provenance(origin="", ref=""))

    with pytest.raises(ValueError, match="no provenance"):
        journal.record(task_id="x", event="assemble", fragments=[anonymous])


# ------------------------------------------------------------------ integrity


def test_records_chain_so_a_missing_or_edited_line_is_visible(journal: PromptJournal) -> None:
    journal.record(task_id="a", event="assemble", fragments=[frag("任务", "一")])
    journal.record(task_id="b", event="assemble", fragments=[frag("任务", "二")])
    records = journal.records()

    assert [r["seq"] for r in records] == [1, 2]
    assert records[0]["prev_line_sha256"] == "0" * 64
    assert records[1]["prev_line_sha256"] == records[0]["line_sha256"]


def test_provenance_keeps_coordinates_and_the_hashes_that_date_them(journal: PromptJournal) -> None:
    provenance = Provenance(origin="source", ref="R-013", doc="Docs/prd/x.pdf", page=23,
                            char_start=1180, char_end=1462, quote_sha256="q", doc_sha256="d")

    record = journal.record(task_id="x", event="assemble",
                            fragments=[Fragment(role="user", section="需求 R-013", text="原文", provenance=provenance)])

    stored = journal.provenance_of(record["seq"], "需求 R-013")
    assert stored.page == 23 and stored.doc_sha256 == "d" and stored.origin == "source"


def test_generated_content_is_distinguishable_from_source(journal: PromptJournal) -> None:
    record = journal.record(task_id="x", event="assemble",
                            fragments=[frag("上一轮输出", "模型自产", origin="generated", ref="audit/plan-41/output.txt")])

    assert journal.provenance_of(record["seq"], "上一轮输出").origin == "generated"


# ------------------------------------------------------------- debug-only status


def test_the_journal_lives_under_the_debug_tree_not_the_audit_tree(journal: PromptJournal) -> None:
    assert JOURNAL_DIR_RELATIVE.startswith(".epi/debug/")
    assert "Docs" not in JOURNAL_DIR_RELATIVE


def test_deleting_the_debug_directory_changes_nothing(journal: PromptJournal) -> None:
    """The test that proves this is a debug facility and not a source of truth."""
    record = journal.record(task_id="a", event="assemble", fragments=[frag("任务", "一")])
    import shutil

    shutil.rmtree(journal.directory)

    assert journal.records() == []
    with pytest.raises(KeyError):
        journal.restore(record["seq"])
    assert journal.record(task_id="b", event="assemble", fragments=[frag("任务", "二")])["seq"] == 1


def test_disabling_recording_touches_no_files(tmp_path: Path) -> None:
    quiet = PromptJournal(tmp_path, enabled=False)

    assert quiet.record(task_id="a", event="assemble", fragments=[frag("任务", "一")]) is None
    assert not (tmp_path / JOURNAL_DIR_RELATIVE).exists()

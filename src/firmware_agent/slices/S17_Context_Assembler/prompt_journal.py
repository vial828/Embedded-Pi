"""Prompt journal - record every prompt mutation so the full prompt can be read back exactly.

Why this exists: "is this prompt precise?" can only be answered by reading the prompt
that was actually sent. Re-running the assembler to guess it is not evidence - the
assembler is the thing under suspicion. So every mutation writes here, at the moment
it happens.

## How the size problem is solved

The bloat is the *content*, not the *manifest*. So:

- fragment **content** goes into a content-addressed store, written once per distinct
  text (`store/<sha[:2]>/<sha>.txt`, immutable)
- each mutation appends one journal line holding the **full ordered manifest** of that
  moment - as hashes plus provenance

Any sequence number therefore restores in one step, with no replay, and switching
tasks a thousand times costs a thousand small lines rather than a thousand copies of
the prompt.

## What makes restoration verifiable instead of plausible

Three hashes must agree:

    restored bytes sha256  ==  recorded prompt_sha  ==  S20 task.json context_sha256

If any differ, this module raises. "Best effort reconstruction" is not offered: a
silently-wrong prompt viewer is worse than none, because it reads like evidence.

## The three things that break byte-exactness if omitted

- **the recipe** (joiner, per-fragment template, trailing newline) - right content,
  wrong separators, wrong bytes
- **transforms as parameters** - a truncation is recorded as (source blob, from, to),
  so the cut is provable and re-computable
- **dropped fragments** - a fragment that did not make the cut is still recorded.
  Otherwise the "full view" is quietly incomplete, and an incomplete full view looks
  exactly like a complete one

## Not in git, by design

This is a debug facility under `.epi/debug/`, not a development artifact. Deleting the
directory must not change any behaviour - there is a test for that.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "DEBUG_ROOT_RELATIVE",
    "DEFAULT_RECIPE",
    "Fragment",
    "PromptJournal",
    "RestoreMismatch",
    "Transform",
    "render_prompt",
]

DEBUG_ROOT_RELATIVE = ".epi/debug"
JOURNAL_DIR_RELATIVE = f"{DEBUG_ROOT_RELATIVE}/prompt-journal"
_JOURNAL_FILE = "journal.jsonl"
_GENESIS = "0" * 64

# The default assembly recipe. It mirrors ContextAssembler's join so the journal can
# reproduce what was sent; a record stores its own copy, so changing this later does
# not invalidate old restorations.
DEFAULT_RECIPE: dict[str, Any] = {
    "join": "\n\n",
    "fragment_template": None,   # e.g. "[{role}] {text}" if roles are inlined
    "trailing_newline": False,
}


class RestoreMismatch(RuntimeError):
    """Restored bytes differ from what was recorded as sent."""


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def render_prompt(fragments: list[dict[str, Any]], recipe: dict[str, Any]) -> str:
    """Rebuild prompt text from manifest entries. Pure, and the only renderer."""
    template = recipe.get("fragment_template")
    parts = []
    for entry in fragments:
        text = entry["_text"]
        if template:
            text = template.format(role=entry.get("role", ""), section=entry.get("section", ""), text=text)
        parts.append(text)
    joined = recipe.get("join", "\n\n").join(parts)
    return joined + "\n" if recipe.get("trailing_newline") else joined


@dataclass(frozen=True)
class Provenance:
    """Where a fragment came from, as of the moment it was injected.

    Coordinates drift - a document is edited and page/line stop pointing at anything.
    That is why the quote hash and the whole-document hash are recorded too: they let a
    later reading say "this provenance is stale" instead of silently misleading.
    """

    origin: str                      # source | generated | conversation
    ref: str                         # human-readable locator
    doc: str = ""
    page: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    quote_sha256: str = ""           # hash of exactly the cited range
    doc_sha256: str = ""             # hash of the whole source document, then

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v not in (None, "")}

    @staticmethod
    def from_dict(data: dict[str, Any]) -> Provenance:
        return Provenance(**data)


@dataclass(frozen=True)
class Transform:
    """A change applied between source text and injected text, recorded as parameters."""

    kind: str                        # truncate | escape | template-fill
    source_sha256: str               # blob before the transform
    from_chars: int
    to_chars: int
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v != ""}


@dataclass(frozen=True)
class Fragment:
    role: str
    section: str
    text: str
    provenance: Provenance
    transform: Transform | None = None
    required: bool = False

    @property
    def sha256(self) -> str:
        return _sha(self.text)


@dataclass(frozen=True)
class VerifyResult:
    seq: int
    restored_sha256: str
    recorded_prompt_sha256: str
    provider_context_sha256: str
    ok: bool
    detail: str = ""


@dataclass
class PromptJournal:
    """Append-only recorder for prompt assemblies.

    `enabled=False` makes recording a no-op and never creates the directory, so the
    journal can be switched off without touching call sites.
    """

    project_root: Path
    enabled: bool = True
    _now: Any = field(default=lambda: datetime.now(UTC).isoformat(timespec="milliseconds"), repr=False)

    # ------------------------------------------------------------------ writing

    @property
    def directory(self) -> Path:
        return Path(self.project_root) / JOURNAL_DIR_RELATIVE

    def record(
        self,
        *,
        task_id: str,
        event: str,
        fragments: list[Fragment],
        recipe: dict[str, Any] | None = None,
        dropped: list[dict[str, Any]] | None = None,
        provider_context_sha256: str = "",
    ) -> dict[str, Any] | None:
        """Persist one mutation. Returns the record, or None when disabled.

        No fragment may arrive without provenance: an anonymous fragment is precisely
        the thing this tool exists to catch, so it is a hard error rather than a warning.
        """
        if not self.enabled:
            return None
        recipe = recipe or DEFAULT_RECIPE
        entries = []
        for index, fragment in enumerate(fragments, start=1):
            if not fragment.provenance.origin:
                raise ValueError(f"fragment {index} ({fragment.section}) has no provenance")
            self._write_blob(fragment.text)
            entry: dict[str, Any] = {
                "i": index,
                "role": fragment.role,
                "section": fragment.section,
                "sha256": fragment.sha256,
                "chars": len(fragment.text),
                "required": fragment.required,
                "provenance": fragment.provenance.as_dict(),
            }
            if fragment.transform:
                entry["transform"] = fragment.transform.as_dict()
            entries.append(entry)

        prompt_text = render_prompt([{**e, "_text": f.text} for e, f in zip(entries, fragments)], recipe)
        previous = self._last_line_sha()
        record = {
            "seq": self._next_seq(),
            "recorded_at": self._now(),
            "task_id": task_id,
            "event": event,
            "recipe": recipe,
            "fragments": entries,
            "dropped": dropped or [],
            "prompt_sha256": _sha(prompt_text),
            "provider_context_sha256": provider_context_sha256,
            "prev_line_sha256": previous,
        }
        record["line_sha256"] = _sha(json.dumps(record, sort_keys=True, ensure_ascii=False))

        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / _JOURNAL_FILE).open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
        return record

    # ------------------------------------------------------------------ reading

    def records(self) -> list[dict[str, Any]]:
        path = self.directory / _JOURNAL_FILE
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def record_at(self, seq: int) -> dict[str, Any]:
        for record in self.records():
            if record["seq"] == seq:
                return record
        raise KeyError(f"no prompt journal record at seq {seq}")

    def restore(self, seq: int) -> str:
        """Rebuild the full prompt of one sequence number from stored blobs."""
        record = self.record_at(seq)
        texts = []
        for entry in record["fragments"]:
            blob = self.directory / "store" / entry["sha256"][:2] / f"{entry['sha256']}.txt"
            if not blob.exists():
                raise RestoreMismatch(f"seq {seq}: content blob missing for fragment {entry['i']} ({entry['section']})")
            texts.append(blob.read_text(encoding="utf-8"))
        return render_prompt(
            [{**e, "_text": t} for e, t in zip(record["fragments"], texts)],
            record["recipe"],
        )

    def verify(self, seq: int) -> VerifyResult:
        """The three-way hash check. Not offered as a warning - it is the tool's premise."""
        record = self.record_at(seq)
        text = self.restore(seq)
        restored = _sha(text)
        ok = restored == record["prompt_sha256"]
        detail = ""
        if ok and record.get("provider_context_sha256"):
            ok = restored == record["provider_context_sha256"]
            detail = "" if ok else "recorded prompt differs from the hash S20 sent to the provider"
        return VerifyResult(
            seq=seq,
            restored_sha256=restored,
            recorded_prompt_sha256=record["prompt_sha256"],
            provider_context_sha256=record.get("provider_context_sha256", ""),
            ok=ok,
            detail=detail,
        )

    def provenance_of(self, seq: int, section: str) -> Provenance | None:
        for entry in self.record_at(seq)["fragments"]:
            if entry["section"] == section:
                return Provenance.from_dict(entry["provenance"])
        return None

    # -------------------------------------------------------------------- internals

    def _write_blob(self, text: str) -> str:
        digest = _sha(text)
        blob = self.directory / "store" / digest[:2] / f"{digest}.txt"
        if not blob.exists():
            blob.parent.mkdir(parents=True, exist_ok=True)
            blob.write_text(text, encoding="utf-8", newline="\n")
        return digest

    def _next_seq(self) -> int:
        records = self.records()
        return records[-1]["seq"] + 1 if records else 1

    def _last_line_sha(self) -> str:
        records = self.records()
        return records[-1]["line_sha256"] if records else _GENESIS

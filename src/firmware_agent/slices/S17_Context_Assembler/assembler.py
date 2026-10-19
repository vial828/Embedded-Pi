from __future__ import annotations

import hashlib
from pathlib import Path

from firmware_agent.config import AppConfig
from firmware_agent.slices.S17_Context_Assembler.constitution import load_constitution
from firmware_agent.slices.S17_Context_Assembler.prompt_journal import (
    Fragment,
    PromptJournal,
    Provenance,
    render_prompt,
)
from firmware_agent.slices.S17_Context_Assembler.token_counter import estimate_tokens
from firmware_agent.state import Task, WorkingState


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


class ContextAssembler:
    """Assemble the prompt from fragments, journaling every assembly.

    Fragments rather than strings, for two reasons. Provenance can only be recorded at
    the moment a piece is added - joined text cannot be un-joined honestly. And a
    budget cut becomes an *event with a record* instead of the old silent tail chop,
    which used to remove the task description first because it happened to be last.
    """

    def __init__(self, config: AppConfig, project_root: str, journal_root: str | Path | None = None,
                 journal: PromptJournal | None = None):
        self.config = config
        self.project_root = Path(project_root)
        constitution_path = self.project_root / config.context.constitution_file
        self.constitution_path = constitution_path
        self.constitution = load_constitution(str(constitution_path.resolve()))
        self.max_tokens = config.resolved_context_tokens()
        self.journal = journal if journal is not None else PromptJournal(Path(journal_root or project_root))

    def assemble(self, task: Task, state: WorkingState, long_memory_pack: str = "") -> str:
        fragments = self.fragments(task, state, long_memory_pack)
        try:
            kept, dropped = self._fit(fragments)
        except ValueError as error:
            # A failed assembly is still something that happened. Without this line the
            # only trace is an exception, and "what did it try to send?" becomes
            # unanswerable after the fact.
            self.journal.record(task_id=self.task_id(task), event=f"assemble:failed ({error})",
                                fragments=fragments, recipe=self.recipe(),
                                dropped=[{"section": f.section, "sha256": f.sha256, "chars": len(f.text),
                                          "reason": "never sent - prompt did not fit"} for f in fragments])
            raise
        text = render_prompt([{"role": f.role, "section": f.section, "_text": f.text} for f in kept],
                             self.recipe())
        self.journal.record(task_id=self.task_id(task), event="assemble", fragments=kept,
                            recipe=self.recipe(), dropped=dropped)
        return text

    @staticmethod
    def recipe() -> dict:
        """The join rules. Stored with every record: wrong separators, wrong bytes."""
        return {"join": "\n\n", "fragment_template": None, "trailing_newline": False}

    @staticmethod
    def task_id(task: Task) -> str:
        return f"{task.type.value}:{task.requirement_id or task.peripheral or 'general'}"

    def fragments(self, task: Task, state: WorkingState, long_memory_pack: str = "") -> list[Fragment]:
        """Where each piece of the prompt comes from, stated at the moment it is added."""
        constitution_sha = _sha(self.constitution)
        pieces = [
            Fragment(role="system", section="constitution", text=self.constitution, required=True,
                     provenance=Provenance(origin="source", ref=f"constitution: {self.constitution_path}",
                                           doc=str(self.constitution_path), quote_sha256=constitution_sha,
                                           doc_sha256=_sha(_read(self.constitution_path)))),
            Fragment(role="system", section="working state", text=state.snapshot(), required=True,
                     provenance=Provenance(origin="source", ref="working_state:snapshot",
                                           quote_sha256=_sha(state.snapshot()))),
        ]
        if long_memory_pack:
            # Recalled memory can contain previous model output. Marked generated until a
            # caller can say otherwise - unmarked model output re-entering a prompt as
            # fact is the failure this whole facility exists to catch.
            pieces.append(Fragment(role="system", section="long memory", text=long_memory_pack,
                                   provenance=Provenance(origin="generated", ref="memory_pack:unknown-source",
                                                         quote_sha256=_sha(long_memory_pack))))
        pieces.append(Fragment(role="user", section="task", text=f"Task: {task.description}", required=True,
                               provenance=Provenance(origin="generated",
                                                     ref=f"task:{self.task_id(task)}",
                                                     quote_sha256=_sha(task.description))))
        return pieces

    def _fit(self, fragments: list[Fragment]) -> tuple[list[Fragment], list[dict]]:
        """Fit the budget by dropping whole optional fragments, or fail loudly.

        There is deliberately no clipping branch. A truncated recall reads exactly like a
        complete one, so half a memory pack would be the one loss worth hiding - and with
        optional fragments dropped first, a clip could only ever run on a fragment that
        was already gone. If dropping every optional fragment still does not fit, the
        budget is wrong for this project and that is a configuration error, not something
        to absorb by sending less.
        """
        dropped: list[dict] = []
        kept = list(fragments)
        if estimate_tokens(self._render(kept)) <= self.max_tokens:
            return kept, dropped

        for candidate in [f for f in reversed(kept) if not f.required]:
            kept.remove(candidate)
            dropped.append({"section": candidate.section, "sha256": candidate.sha256,
                            "chars": len(candidate.text), "reason": "budget"})
            if estimate_tokens(self._render(kept)) <= self.max_tokens:
                return kept, dropped

        raise ValueError(
            f"prompt does not fit {self.max_tokens} tokens even after dropping "
            f"{[d['section'] for d in dropped]}; required fragments were not touched"
        )

    def _render(self, fragments: list[Fragment]) -> str:
        return render_prompt([{"role": f.role, "section": f.section, "_text": f.text} for f in fragments],
                             self.recipe())

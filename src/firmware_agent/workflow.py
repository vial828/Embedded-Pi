from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path

from rich.console import Console

from firmware_agent.config import load_project_config
from firmware_agent.slices.S07_Compiler.compiler import compile_system_design
from firmware_agent.slices.S09_PRD_Ingestion.prd_ingestion import ingest_prd
from firmware_agent.slices.S22_Compiler_Verifier.compiler_verifier import (
    CompilerVerifier,
)
from firmware_agent.slices.S23_Static_Verifier.static_verifier import StaticVerifier
from firmware_agent.slices.S24_Simulator_Verifier.simulator_verifier import (
    SimulatorVerifier,
)
from firmware_agent.slices.S29_Test_Report_Output.test_report import (
    build_report,
    write_report,
)

console = Console()


class WorkflowPhase(str, Enum):
    INIT = "init"
    WAIT_FOR_EXTERNAL_FILES = "wait_for_external_files"
    INGEST = "ingest"
    WAIT_FOR_DESIGN_REVIEW = "wait_for_design_review"
    GENERATE = "generate"
    TEST = "test"
    DONE = "done"


@dataclass
class WorkflowState:
    phase: str = WorkflowPhase.INIT.value
    last_completed_phase: str = ""
    approved_design: bool = False
    notes: str = ""
    # Required inputs the current run was explicitly allowed to proceed without.
    # Persisted so a state file cannot look like a gated run when it was waived.
    waived_missing: list[str] = field(default_factory=list)
    # Which authority granted the waiver: "cli" (--allow-missing) or "config"
    # (gate.allow_missing_inputs). A waiver nobody claims is indistinguishable
    # from a bug that skipped the gate.
    waived_by: str = ""
    # Last test-phase verdicts, so `status` and S30 can see what evidence existed.
    test_verdicts: dict[str, str] = field(default_factory=dict)


class WorkflowRunner:
    def __init__(self, project_dir: Path, allow_missing: bool = False):
        self.project_dir = project_dir
        self.docs_root = project_dir / "Docs"
        self.state_path = self.docs_root / "ai-generation" / "workflow" / "state.json"
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state = self.load_state()
        self.allow_missing = allow_missing
        self._config = None

    def load_state(self) -> WorkflowState:
        if self.state_path.exists():
            data = json.loads(self.state_path.read_text(encoding="utf-8") or "{}")
            return WorkflowState(**{k: data.get(k, getattr(WorkflowState(), k)) for k in WorkflowState.__dataclass_fields__})
        return WorkflowState()

    def save_state(self) -> None:
        self.state_path.write_text(json.dumps(asdict(self.state), ensure_ascii=False, indent=2), encoding="utf-8")

    def reset_state(self) -> None:
        self.state = WorkflowState()
        if self.state_path.exists():
            self.state_path.unlink()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.save_state()

    def _print_banner(self, title: str) -> None:
        console.rule(f"[bold cyan]{title}[/bold cyan]")

    def _roadmap_lines(self) -> list[str]:
        return [
            "1. Initialize project",
            "2. Wait for external documents",
            "3. Ingest documents into standard format",
            "4. Review generated design",
            "5. Generate implementation artifacts",
            "6. Run module tests and report",
            "7. Finish workflow",
        ]

    def _roadmap_order(self) -> list[str]:
        return [
            WorkflowPhase.INIT.value,
            WorkflowPhase.WAIT_FOR_EXTERNAL_FILES.value,
            WorkflowPhase.INGEST.value,
            WorkflowPhase.WAIT_FOR_DESIGN_REVIEW.value,
            WorkflowPhase.GENERATE.value,
            WorkflowPhase.TEST.value,
            WorkflowPhase.DONE.value,
        ]

    def _current_stage_index(self) -> int:
        order = self._roadmap_order()
        return order.index(self.state.phase) if self.state.phase in order else 0

    def _next_stage_label(self) -> str:
        order = self._roadmap_order()
        idx = self._current_stage_index()
        if idx + 1 < len(order):
            return self._roadmap_lines()[idx + 1]
        return "Workflow complete"

    def _status_bar(self) -> str:
        total = len(self._roadmap_lines())
        current = self._current_stage_index() + 1
        label = self._roadmap_lines()[self._current_stage_index()]
        return f"[bold cyan]Status[/bold cyan]  [yellow]▶[/yellow] {current}/{total}  {label}"

    def _show_status(self) -> None:
        console.clear()
        console.print(self._status_bar())
        if self.state.waived_missing:
            console.print(f"[magenta]Gate waived[/magenta] by {self.state.waived_by or 'unknown authority'}: "
                          f"{len(self.state.waived_missing)} required input(s) missing but accepted this run")
        console.print("[bold cyan]Roadmap[/bold cyan]")
        for idx, line in enumerate(self._roadmap_lines(), 1):
            if self._roadmap_stage_active(idx):
                marker = "[yellow]▶[/yellow]"
            elif self._roadmap_stage_done(idx):
                marker = "[green]✓[/green]"
            else:
                marker = "[dim]·[/dim]"
            console.print(f"  {marker} {line}")

    def _required_sources(self) -> list[tuple[str, list[str]]]:
        return [
            ("Docs/prd", ["*.pdf", "*.docx", "*.md"]),
            ("Docs/standards", ["*.md", "*.json"]),
            ("Docs/hardware/schematic", ["*.*"]),
            ("Docs/hardware/registers", ["*.json", "*.md"]),
            ("Docs/hardware/datasheet", ["*.*"]),
            ("Docs/bsp", ["*.*"]),
        ]

    def _read_file_text(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            try:
                result = subprocess.run(["pdftotext", "-layout", str(path), "-"], check=True, capture_output=True, text=True)
                return result.stdout
            except (FileNotFoundError, subprocess.CalledProcessError):
                return ""
        return path.read_text(encoding="utf-8", errors="ignore")

    def _has_min_content(self, path: Path, rel_dir: str) -> bool:
        if not path.is_file() or path.stat().st_size == 0:
            return False
        text = self._read_file_text(path).strip()
        if len(text) < 20:
            return False
        lowered = text.lower()
        if any(token in lowered for token in ["template", "todo", "placeholder", "n/a"]):
            return False
        if rel_dir.startswith("Docs/prd"):
            return any(keyword in text for keyword in ["User Story", "Acceptance Criteria", "Description"])
        return True

    def _path_has_files(self, rel_dir: str, patterns: list[str]) -> bool:
        root = self.project_dir / rel_dir
        if not root.exists() or not root.is_dir():
            return False
        return any(self._has_min_content(path, rel_dir) for pattern in patterns for path in root.glob(pattern))

    def _tree_line(self, prefix: str, label: str, checked: bool) -> str:
        mark = "[green]✓[/green]" if checked else "[red]✗[/red]"
        return f"{prefix}{mark} {label}"

    def _matching_files(self, rel_dir: str, patterns: list[str]) -> list[str]:
        root = self.project_dir / rel_dir
        if not root.exists() or not root.is_dir():
            return []
        matches: list[str] = []
        for pattern in patterns:
            for path in sorted(root.glob(pattern)):
                if self._has_min_content(path, rel_dir):
                    matches.append(str(path.relative_to(self.project_dir)))
        return matches

    def _format_source_tree(self) -> list[str]:
        lines: list[str] = []
        items = self._required_sources()
        lines.append("Docs/")
        for i, (rel_dir, patterns) in enumerate(items):
            is_last_dir = i == len(items) - 1
            dir_prefix = "├── " if not is_last_dir else "└── "
            group_ok = self._path_has_files(rel_dir, patterns)
            dir_name = rel_dir.split('/', 1)[1] + "/"
            lines.append(self._tree_line(dir_prefix, dir_name, group_ok))
            file_prefix = "│   " if not is_last_dir else "    "
            matches = self._matching_files(rel_dir, patterns)
            if matches:
                last_index = len(matches) - 1
                for j, file_rel in enumerate(matches):
                    branch = "└── " if j == last_index else "├── "
                    lines.append(self._tree_line(f"{file_prefix}{branch}", file_rel, True))
            else:
                or_label = " | ".join(patterns)
                lines.append(self._tree_line(f"{file_prefix}└── ", or_label, False))
        return lines

    def _print_required_tree(self) -> None:
        console.print("Required source tree:")
        for line in self._format_source_tree():
            console.print(f"  {line}")
        missing = self._missing_required_paths()
        if missing:
            console.print("[yellow]Missing paths:[/yellow]")
            for item in missing:
                waived = item in self.state.waived_missing
                tag = "  [magenta](waived)[/magenta]" if waived else ""
                console.print(f"  - {item}{tag}")

    def _missing_required_paths(self) -> list[str]:
        missing: list[str] = []
        for rel_dir, patterns in self._required_sources():
            if not self._path_has_files(rel_dir, patterns):
                missing.append(f"{rel_dir}/ ({' OR '.join(patterns)})")
        return missing

    def _detect_prd_ready(self) -> list[str]:
        """Missing inputs that still block this run, i.e. not covered by a waiver."""
        return [m for m in self._missing_required_paths() if m not in self.state.waived_missing]

    def _project_config(self):
        if self._config is None:
            self._config = load_project_config(self.project_dir)
        return self._config

    def _report_config_state(self) -> None:
        """Say out loud what the configuration actually is before doing any work."""
        cfg = self._project_config()
        if cfg.is_template:
            console.print(
                f"[yellow]Configuration is still the generated template[/yellow] ({cfg.source_path}): "
                "project / mcu / toolchain values are placeholders. Edit them, then delete the "
                "`template: true` line."
            )
        if not cfg.compiler_exists():
            console.print(
                f"[yellow]Configured compiler is not reachable:[/yellow] {cfg.toolchain.compiler} "
                "- generate will fail until it is installed or toolchain.compiler is corrected."
            )

    def _waiver_authority(self) -> str:
        """Who lets this run past the gate: "cli", "config", or "" for nobody."""
        if self.allow_missing:
            return "cli"
        if self._project_config().gate.allow_missing_inputs:
            return "config"
        return ""

    def _apply_missing_waiver(self) -> None:
        """Grant or expire the gate waiver for this run.

        A --allow-missing waiver is granted per invocation and never silently
        carries over: one run with the flag must not arm the bypass for every
        later run, which is the silent-fallback failure mode this gate exists to
        stop. A config waiver (gate.allow_missing_inputs: true) is persistent on
        purpose - it is a checked-in project decision - so it is reported with
        the file it came from.
        """
        missing = self._missing_required_paths()
        authority = self._waiver_authority()
        if not authority:
            if self.state.waived_missing:
                console.print("[dim]Previous waiver expired. Rerun with --allow-missing to waive again.[/dim]")
                self.state.waived_missing = []
                self.state.waived_by = ""
                self.state.notes = ""
                self.save_state()
            return
        if not missing:
            return
        self.state.waived_missing = sorted(set(self.state.waived_missing) | set(missing))
        self.state.waived_by = authority
        self.state.notes = f"external input gate waived by {authority}"
        self.save_state()
        reason = "--allow-missing (this run only)" if authority == "cli" else \
            f"gate.allow_missing_inputs in {self._project_config().source_path} (persistent)"
        console.print(f"[magenta]External input gate WAIVED[/magenta] via {reason}. Proceeding without:")
        for item in missing:
            console.print(f"  - {item}")
        console.print("[dim]Downstream artifacts from this run are not fully sourced; "
                      "see waived_missing in the workflow state.[/dim]")

    def _advance(self, next_phase: WorkflowPhase) -> None:
        self.state.last_completed_phase = self.state.phase
        self.state.phase = next_phase.value
        self.save_state()

    def _roadmap_stage_done(self, stage: int) -> bool:
        return stage - 1 < self._current_stage_index()

    def _roadmap_stage_active(self, stage: int) -> bool:
        return stage - 1 == self._current_stage_index()

    def _blocked_reason(self) -> str:
        return ""

    def _ensure_design_template(self) -> Path:
        path = self.docs_root / "ai-generation" / "fw-architecture" / "system-design" / "system-design.md"
        if not path.exists():
            raise FileNotFoundError(path)
        return path

    def _pin_to_external_gate_if_needed(self) -> bool:
        missing = self._detect_prd_ready()
        if missing and self.state.phase not in {WorkflowPhase.INIT.value, WorkflowPhase.WAIT_FOR_EXTERNAL_FILES.value}:
            console.print("[yellow]Gate re-armed: returning to external input. Blocking inputs:[/yellow]")
            for item in missing:
                console.print(f"  - {item}")
            self.state.phase = WorkflowPhase.WAIT_FOR_EXTERNAL_FILES.value
            self.state.last_completed_phase = ""
            self.state.approved_design = False
            self.state.notes = "waiting for external documents"
            self.save_state()
            return True
        return False

    def run(self) -> None:
        self._print_banner("EPI Workflow MVP")
        self._report_config_state()
        self._apply_missing_waiver()
        self._pin_to_external_gate_if_needed()
        self._show_status()
        self.save_state()

        while True:
            self._pin_to_external_gate_if_needed()
            phase = WorkflowPhase(self.state.phase)
            if phase == WorkflowPhase.INIT:
                console.print("[yellow]Initializing workflow state...[/yellow]")
                self._advance(WorkflowPhase.WAIT_FOR_EXTERNAL_FILES)
                self._show_status()
                continue

            if phase == WorkflowPhase.WAIT_FOR_EXTERNAL_FILES:
                console.print("[yellow]External input gate[/yellow]")
                self._print_required_tree()
                console.print("Type [bold]ready[/bold] after you place the required files.")
                console.print("Type [bold]status[/bold] to refresh the roadmap cursor.")
                self._interactive_prompt({"ready", "status", "quit"})
                if self.state.phase == WorkflowPhase.WAIT_FOR_EXTERNAL_FILES.value:
                    continue
                continue

            if phase == WorkflowPhase.INGEST:
                out = ingest_prd(self.docs_root)
                console.print(f"[green]PRD normalized:[/green] {out}")
                self._advance(WorkflowPhase.WAIT_FOR_DESIGN_REVIEW)
                continue

            if phase == WorkflowPhase.WAIT_FOR_DESIGN_REVIEW:
                design_path = self._ensure_design_template()
                console.print(f"[cyan]Design ready for review:[/cyan] {design_path}")
                console.print("Review the design, then type [bold]approve[/bold] to continue or [bold]revise[/bold] to stop here.")
                console.print("Type [bold]status[/bold] to review the roadmap, current step, and next step.")
                if self.state.approved_design:
                    console.print("[green]Design already approved. Continuing...[/green]")
                    self._advance(WorkflowPhase.GENERATE)
                    continue
                self._interactive_prompt({"approve", "revise", "status", "quit"})
                continue

            if phase == WorkflowPhase.GENERATE:
                if not self._phase_generate():
                    self._interactive_prompt({"retry", "quit", "status"})
                continue

            if phase == WorkflowPhase.TEST:
                if not self._phase_test():
                    self._interactive_prompt({"retry", "quit", "status"})
                continue

            if phase == WorkflowPhase.DONE:
                console.print("[bold green]Workflow complete.[/bold green]")
                self._show_status()
                return

    def _phase_generate(self) -> bool:
        """Turn the reviewed design into compiled artifacts. False means it did not work.

        This phase does not generate firmware. Saying so here is the point: the
        previous message claimed it "generated" from the design, which made an
        empty `src/` look like a completed step.
        """
        design_path = self._ensure_design_template()
        ok, message = compile_system_design(self.project_dir)
        if not ok:
            console.print("[red]Design compile failed:[/red]")
            console.print(message)
            return False

        console.print(f"[cyan]Design artifacts compiled from[/cyan] {design_path}")
        console.print(f"  [dim]{message}[/dim]")
        console.print("[yellow]No code generator is implemented yet - nothing was written under src/.[/yellow]")
        self._advance(WorkflowPhase.TEST)
        return True

    def _phase_test(self) -> bool:
        """Run the real verifiers and fail the phase on a real failure.

        A stub is neither a pass nor a failure: it produced no evidence. It is
        listed at the top of the report so nobody reads "0 failures" as "fully
        verified" - the quality gate (S30) is what rejects a run on stub evidence.
        """
        config = self._project_config()
        verdicts = {
            "compile": CompilerVerifier(config, self.project_dir).verify("Workflow compile"),
            "host-tests": SimulatorVerifier(config, self.project_dir).verify("Workflow host tests"),
            "static-analysis": StaticVerifier().verify("Workflow static analysis"),
        }
        report = build_report(self.project_dir, verdicts)
        paths = write_report(self.project_dir, report)

        for stage in report["stages"]:
            tag = {"PASS": "[green]PASS[/green]", "FAIL": "[red]FAIL[/red]"}.get(
                stage["verdict"], "[magenta]no evidence (stub)[/magenta]"
            )
            console.print(f"  {stage['name']}: {tag}")

        trace = report["traceability"]
        console.print(f"  traceability: {trace['status']}")
        if trace["status"] == "not-evaluated":
            console.print(f"    [yellow]{trace['reason']}[/yellow]")

        if report["failed_stages"]:
            console.print(f"[red]Failed:[/red] {', '.join(report['failed_stages'])} - see {paths['markdown']}")
            return False

        console.print(f"[green]Test report written:[/green] {paths['markdown']}")
        self.state.test_verdicts = {stage["name"]: stage["verdict"].lower() for stage in report["stages"]}
        self._advance(WorkflowPhase.DONE)
        return True

    def _interactive_prompt(self, allowed: set[str]) -> None:
        while True:
            cmd = console.input("[bold cyan]epi>[/bold cyan] ").strip().lower()
            if cmd in allowed:
                if cmd == "status":
                    self._show_status()
                    continue
                if cmd == "retry":
                    # Return so the caller re-enters the phase; a phase that failed
                    # stays where it is, so retrying means running it again.
                    return
                if cmd == "ready":
                    self._print_required_tree()
                    missing = self._detect_prd_ready()
                    if missing:
                        console.print("[red]Cannot continue yet. Please fix the missing paths above.[/red]")
                        continue
                    console.print("[green]All required items are checked.[/green]")
                    while True:
                        answer = console.input("Proceed to ingest? [y/N]: ").strip().lower()
                        if answer in {"y", "yes"}:
                            self._advance(WorkflowPhase.INGEST)
                            return
                        if answer in {"", "n", "no"}:
                            console.print("[yellow]Staying at the external input gate.[/yellow]")
                            return
                        console.print("Please answer y or n.")
                if cmd == "approve":
                    self.state.approved_design = True
                    self.save_state()
                    self._advance(WorkflowPhase.GENERATE)
                    return
                if cmd == "revise":
                    self.state.approved_design = False
                    self.state.notes = "design revision requested"
                    self.save_state()
                    console.print("[yellow]Design marked for revision. Update files, then rerun epi.[/yellow]")
                    return
                if cmd == "retry":
                    return
                if cmd == "quit":
                    self.save_state()
                    raise SystemExit(0)
            console.print(f"[red]Allowed commands:[/red] {', '.join(sorted(allowed))}")


def run_workflow(project_dir: Path, allow_missing: bool = False) -> None:
    WorkflowRunner(project_dir, allow_missing=allow_missing).run()

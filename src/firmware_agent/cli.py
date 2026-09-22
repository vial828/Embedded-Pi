from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from firmware_agent.agent import FirmwareAgent
from firmware_agent.project_layout import (
    ensure_project_layout,
    inspect_project_layout,
    reset_system_design_template,
)
from firmware_agent.schema.compiler import compile_system_design

console = Console()


def _render_layout_table(
    root: Path,
    *,
    check_only: bool,
    created_keys: set[str] | None = None,
    updated_keys: set[str] | None = None,
) -> bool:
    items = inspect_project_layout(root)
    created_keys = created_keys or set()
    updated_keys = updated_keys or set()

    table = Table(title=f"Project Layout Check: {root}")
    table.add_column("Type", style="cyan", width=10)
    table.add_column("Path")
    table.add_column("Status", width=12)
    table.add_column("Detail", style="dim")

    has_missing = False
    for item in items:
        if item.exists:
            if not check_only and item.key in created_keys:
                status = "[yellow]CREATED[/yellow]"
            elif not check_only and item.key in updated_keys:
                status = "[blue]UPDATED[/blue]"
            else:
                status = "[green]PASS[/green]"
        else:
            has_missing = True
            status = "[red]MISSING[/red]"

        table.add_row(item.kind, item.key, status, item.detail)

    console.print(table)
    return has_missing


def entry(
    project_dir: str = typer.Argument(".", help="Project path"),
    check_only: bool = typer.Option(False, "--check-only", help="Only check layout, do not create missing items"),
    schema_compile: bool = typer.Option(False, "--schema-compile", help="Compile Docs/ai-generation/fw-architecture/system-design/system-design.md into fixed JSON outputs"),
    reset_schema_template: bool = typer.Option(False, "--reset-schema-template", help="Force-regenerate canonical system-design.md template"),
    run_agent: bool = typer.Option(False, "--run", help="Run agent after ensuring layout"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Used with --run"),
) -> None:
    """
    Usage:
      epi /path/to/project

    Behavior:
      - If path exists: check whether required project layout is present.
      - If path does not exist: create it.
      - If missing items: create missing directory tree/files (unless --check-only).
    """
    root = Path(project_dir)

    if check_only:
        has_missing = _render_layout_table(root, check_only=True)
        if has_missing:
            raise typer.Exit(code=2)
        return

    report = ensure_project_layout(root)
    created_keys = set(report.created_dirs + report.created_files)
    updated_keys = set(report.updated_files)
    has_missing = _render_layout_table(root, check_only=False, created_keys=created_keys, updated_keys=updated_keys)

    if has_missing:
        raise typer.Exit(code=3)

    if reset_schema_template:
        target = reset_system_design_template(root)
        console.print(f"[yellow]Schema template reset[/yellow] {target}")

    if schema_compile:
        ok, msg = compile_system_design(root)
        if ok:
            console.print(f"[green]SCHEMA COMPILE PASS[/green] {msg}")
        else:
            console.print("[red]SCHEMA COMPILE FAIL[/red]")
            console.print(msg)
            raise typer.Exit(code=4)

    if run_agent:
        agent = FirmwareAgent(str(root))
        logs = agent.run(dry_run=dry_run)
        for line in logs:
            console.print(line)


def main() -> None:
    typer.run(entry)

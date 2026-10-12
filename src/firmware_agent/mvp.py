from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path

from firmware_agent.workflow import WorkflowRunner, run_workflow


def main() -> None:
    parser = ArgumentParser(prog="epi-mvp", description="Installable MVP launcher for the EPI workflow")
    parser.add_argument("project_dir", nargs="?", default=".", help="Project path")
    parser.add_argument("--reset-workflow", action="store_true", help="Reset workflow state before launching")
    args = parser.parse_args()

    runner = WorkflowRunner(Path(args.project_dir))
    if args.reset_workflow:
        runner.reset_state()
    run_workflow(Path(args.project_dir))

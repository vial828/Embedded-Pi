"""P0-5: S21 action executor. Rules under test: default-deny writes, everything logged."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from firmware_agent.slices.S21_Executor.action_executor import (
    ActionExecutor,
    ExecutorError,
    read_action_log,
)


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    return root


def log(root: Path, task: str = "T-1") -> list[dict]:
    return read_action_log(root, task)


def test_writes_src_and_logs_it_with_content_hash(project: Path) -> None:
    ex = ActionExecutor(project, "T-1")
    content = "int main(void) { return 0; }\n"
    path = ex.write_text("src/main.c", content)

    assert path.read_text(encoding="utf-8") == content
    entry = log(project)[-1]
    assert entry["action"] == "write_text"
    assert entry["result"]["previous_sha256"] is None, "first write has no predecessor"
    assert entry["result"]["sha256"] == hashlib.sha256(content.encode("utf-8")).hexdigest()


def test_overwrite_records_what_it_replaced(project: Path) -> None:
    ex = ActionExecutor(project, "T-1")
    ex.write_text("src/main.c", "first\n")
    ex.write_text("src/main.c", "second\n")

    entries = log(project)
    assert entries[0]["result"]["previous_sha256"] is None
    assert entries[1]["result"]["previous_sha256"] == entries[0]["result"]["sha256"], (
        "an overwrite must name the content it destroyed"
    )


@pytest.mark.parametrize(
    "bad_path, may_exist_afterwards",
    [
        ("Docs/prd/injected.md", False),              # source of truth
        ("Docs/ai-generation/knowledge/requirements_index.json", False),
        ("Docs/ai-generation/workflow/state.json", False),
        ("Docs/ai-generation/audit/T-1/actions.jsonl", True),  # its own trail
        ("config.yaml", False),
        (".git/config", False),
        ("../outside.c", False),
        ("src/../../outside.c", False),
        ("/etc/passwd", False),
    ],
)
def test_writes_outside_the_allowlist_are_refused_and_logged(
    project: Path, bad_path: str, may_exist_afterwards: bool
) -> None:
    ex = ActionExecutor(project, "T-1")
    with pytest.raises(ExecutorError):
        ex.write_text(bad_path, "x")

    # The check has to run before any I/O: a refusal that still created the file
    # is the bug this whole slice exists to prevent. The audit trail is the one
    # path that legitimately exists afterwards - the refusal itself is recorded.
    target = project / bad_path
    if not bad_path.startswith(("/", "..")):
        if may_exist_afterwards:
            text = target.read_text(encoding="utf-8")
            assert text.strip() != "x", "the requested content must not have been written"
            assert json.loads(text.splitlines()[-1])["result"]["refused"]
        else:
            assert not target.exists(), f"{bad_path} was written despite being refused"
    refusal = log(project)[-1]
    assert "refused" in refusal["result"]


def test_refusals_are_not_silent(project: Path) -> None:
    ex = ActionExecutor(project, "T-1")
    with pytest.raises(ExecutorError) as err:
        ex.write_text("README.md", "x")
    assert "writable prefix" in str(err.value)
    assert log(project), "a refusal with no trace is indistinguishable from a missing check"


def test_runs_a_command_and_records_output(project: Path) -> None:
    ex = ActionExecutor(project, "T-1", allowed_executables={sys.executable})
    ex.write_text("src/hello.txt", "hi\n")

    result = ex.run_command([sys.executable, "-c", "print(open('src/hello.txt').read().strip())"], cwd=".")

    assert result.ok and result.stdout.strip() == "hi"
    entry = log(project)[-1]
    assert entry["result"]["exit_code"] == 0
    assert entry["result"]["stdout"].strip() == "hi"
    assert entry["result"]["duration_ms"] >= 0


def test_working_directory_is_the_project_not_the_shell(project: Path) -> None:
    ex = ActionExecutor(project, "T-1", allowed_executables={sys.executable})
    result = ex.run_command([sys.executable, "-c", "import os; print(os.getcwd())"])
    assert Path(result.stdout.strip()).resolve() == project


def test_no_shell_means_no_second_interpretation(project: Path) -> None:
    ex = ActionExecutor(project, "T-1", allowed_executables={sys.executable})
    result = ex.run_command([sys.executable, "-c", "print('a > b ; c')"])

    assert result.ok
    assert result.stdout.strip() == "a > b ; c"
    assert not (project / "b").exists(), "a redirect must not be honoured"


def test_failing_command_is_a_result_not_an_exception(project: Path) -> None:
    ex = ActionExecutor(project, "T-1", allowed_executables={sys.executable})
    result = ex.run_command([sys.executable, "-c", "import sys; sys.stderr.write('nope'); sys.exit(3)"])

    assert result.exit_code == 3 and not result.ok
    assert result.stderr == "nope"
    assert log(project)[-1]["result"]["exit_code"] == 3


def test_timeout_is_reported_as_timeout(project: Path) -> None:
    ex = ActionExecutor(project, "T-1", allowed_executables={sys.executable})
    result = ex.run_command([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1)

    assert result.timed_out and result.exit_code is None and not result.ok
    assert log(project)[-1]["result"]["timed_out"] is True


def test_missing_executable_is_a_finding_not_a_traceback(project: Path) -> None:
    ex = ActionExecutor(project, "T-1")
    result = ex.run_command(["definitely-not-a-real-compiler"])

    assert result.exit_code is None and not result.ok and result.stderr
    assert log(project)[-1]["result"]["exit_code"] is None


def test_unlisted_executable_is_refused(project: Path) -> None:
    ex = ActionExecutor(project, "T-1", allowed_executables={"arm-none-eabi-gcc"})
    with pytest.raises(ExecutorError) as err:
        ex.run_command([sys.executable, "-c", "print(1)"])
    assert "not in the allowed executables" in str(err.value)
    assert log(project)[-1]["result"]["refused"]


def test_cwd_must_exist_inside_the_project(project: Path) -> None:
    ex = ActionExecutor(project, "T-1", allowed_executables={sys.executable})
    with pytest.raises(ExecutorError):
        ex.run_command([sys.executable, "-c", "print(1)"], cwd="../../etc")
    with pytest.raises(ExecutorError):
        ex.run_command([sys.executable, "-c", "print(1)"], cwd="src/nope")


def test_action_log_is_append_only_jsonl_with_stable_sequence(project: Path) -> None:
    ActionExecutor(project, "T-1").write_text("src/a.c", "a")
    ActionExecutor(project, "T-1").write_text("src/b.c", "b")  # a second run, same task

    entries = log(project)
    assert [e["seq"] for e in entries] == [1, 2], "sequence must continue across runs"
    assert all(json.dumps(e) for e in entries)
    assert {e["task_id"] for e in entries} == {"T-1"}

    ActionExecutor(project, "T-2").write_text("src/c.c", "c")
    assert [e["task_id"] for e in read_action_log(project, "T-2")] == ["T-2"]
    assert len(log(project)) == 2, "tasks must not share a trail"


def test_audit_trail_lives_where_the_llm_standard_says(project: Path) -> None:
    ActionExecutor(project, "T-1").write_text("src/a.c", "a")
    assert (project / "Docs/ai-generation/audit/T-1/actions.jsonl").exists()

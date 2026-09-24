from firmware_agent.state import Task, TaskType


class TaskPlanner:
    """S18 planner: returns a minimal fixed pipeline (M0)."""

    def plan(self) -> list[Task]:
        return [
            Task(TaskType.PARSE_PRD, "Parse PRD and assign requirement IDs"),
            Task(TaskType.DRIVER_IMPL, "Generate UART1 driver", peripheral="UART1", needs_verification=True),
            Task(TaskType.COMPILE, "Compile generated firmware", needs_verification=True),
            Task(TaskType.DOCUMENT, "Generate minimal report"),
        ]

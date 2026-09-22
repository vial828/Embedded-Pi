from dataclasses import dataclass


@dataclass
class VerifyResult:
    passed: bool
    output: str = ""


class Verifier:
    """M0 verifier stub. Compile integration comes next."""

    def verify(self, task_name: str) -> VerifyResult:
        return VerifyResult(passed=True, output=f"[stub] verified: {task_name}")

from dataclasses import dataclass


@dataclass
class VerifyResult:
    passed: bool
    output: str = ""


class CompilerVerifier:
    """S22 compiler verifier stub."""

    def verify(self, task_name: str) -> VerifyResult:
        return VerifyResult(passed=True, output=f"[stub] compiler verified: {task_name}")

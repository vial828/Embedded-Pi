from firmware_agent.slices.S22_Compiler_Verifier.compiler_verifier import VerifyResult


class StaticVerifier:
    """S23 static verifier stub."""

    def verify(self, task_name: str) -> VerifyResult:
        return VerifyResult(passed=True, output=f"[stub] static verified: {task_name}")

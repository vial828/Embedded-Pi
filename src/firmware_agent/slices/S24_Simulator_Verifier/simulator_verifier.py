from firmware_agent.slices.S22_Compiler_Verifier.compiler_verifier import VerifyResult


class SimulatorVerifier:
    """S24 simulator verifier stub."""

    def verify(self, task_name: str) -> VerifyResult:
        return VerifyResult(passed=True, output=f"[stub] simulator verified: {task_name}")

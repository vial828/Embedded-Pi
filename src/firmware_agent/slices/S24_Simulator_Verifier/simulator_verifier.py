from firmware_agent.slices.S22_Compiler_Verifier.compiler_verifier import VerifyResult


class SimulatorVerifier:
    """S24 simulator verifier stub."""

    def verify(self, task_name: str) -> VerifyResult:
        # See S23: a stub reports that it did nothing, it does not hand out a pass.
        return VerifyResult(
            passed=False,
            output=f"[stub] simulator run not implemented; no verdict for {task_name!r}",
            stub=True,
            tool="stub",
        )

from __future__ import annotations

from firmware_agent.slices.S19_State_Machine.state_models import Phase, WorkingState


class StateMachine:
    """S19 state machine scaffold for phase transitions."""

    ORDER = [
        Phase.REQUIREMENTS_REVIEW,
        Phase.ARCHITECTURE,
        Phase.IMPLEMENTATION,
        Phase.VERIFICATION,
        Phase.DOCUMENTATION,
        Phase.DONE,
    ]

    def next_phase(self, current: Phase) -> Phase:
        if current in {Phase.FAILED, Phase.DONE}:
            return current
        idx = self.ORDER.index(current)
        return self.ORDER[min(idx + 1, len(self.ORDER) - 1)]

    def fail(self, state: WorkingState, reason: str) -> None:
        state.phase = Phase.FAILED
        state.last_error = reason

"""The pump operations a transaction needs from an adapter."""

from typing import Protocol

from .pump_write_outcome import PumpWriteOutcome


class PumpPort(Protocol):
    """Supplies fresh pump readings and writes absolute degree-minute targets."""

    async def write_degree_minutes(
        self, target_degree_minutes: int
    ) -> PumpWriteOutcome:
        """Attempt to write the target and report whether it may have reached the pump."""
        ...

    async def read_degree_minutes(self) -> int:
        """Return a fresh observed degree-minute value from the pump."""
        ...

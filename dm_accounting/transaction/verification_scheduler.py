"""Time-based scheduling for transaction verification."""

from collections.abc import Awaitable, Callable
from typing import Protocol


class ScheduledCall(Protocol):
    """A scheduled callback that may no longer be needed."""

    def cancel(self) -> None:
        """Prevent the callback from running when it has not run already."""
        ...


class VerificationScheduler(Protocol):
    """Schedules the delayed verification callbacks requested by a transaction."""

    def call_later(
        self,
        delay_seconds: int,
        callback: Callable[[], Awaitable[None]],
    ) -> ScheduledCall:
        """Schedule an asynchronous callback and return its cancellation handle."""
        ...

"""Home Assistant implementation of delayed transaction verification."""

from collections.abc import Awaitable, Callable
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later

from dm_accounting.transaction import ScheduledCall, VerificationScheduler

_LOGGER = logging.getLogger(__name__)


class _HomeAssistantScheduledCall(ScheduledCall):
    """Adapter for Home Assistant's unsubscribe callback."""

    def __init__(self, cancel: Callable[[], None]) -> None:
        self._cancel = cancel
        self._cancelled = False

    def cancel(self) -> None:
        """Prevent the callback from starting when it has not fired."""
        if not self._cancelled:
            self._cancelled = True
            self._cancel()


class HomeAssistantVerificationScheduler(VerificationScheduler):
    """Schedules transaction verification callbacks on Home Assistant's event loop."""

    def __init__(
        self,
        hass: HomeAssistant,
        on_callback_complete: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Create a scheduler backed by Home Assistant's event loop."""
        self._hass = hass
        self._on_callback_complete = on_callback_complete

    def call_later(
        self,
        delay_seconds: int,
        callback: Callable[[], Awaitable[None]],
    ) -> ScheduledCall:
        """Schedule the callback and return a handle that can cancel it."""
        if not isinstance(delay_seconds, int) or isinstance(delay_seconds, bool):
            raise TypeError("delay_seconds must be an integer")
        if delay_seconds < 0:
            raise ValueError("delay_seconds must not be negative")

        async def start_callback(_: object) -> None:
            try:
                await callback()
            except Exception:
                _LOGGER.exception("Delayed verification callback failed")
            finally:
                if self._on_callback_complete is not None:
                    try:
                        await self._on_callback_complete()
                    except Exception:
                        _LOGGER.exception("Verification state persistence callback failed")

        cancel = async_call_later(self._hass, delay_seconds, start_callback)
        return _HomeAssistantScheduledCall(cancel)

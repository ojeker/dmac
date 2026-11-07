"""Home Assistant entry points and periodic scheduling for heating control."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from dm_accounting import HeatingController, TimingPolicy

_LOGGER = logging.getLogger(__name__)


class HomeAssistantHeatingAdapter:
    """Routes Home Assistant signals and maintenance ticks to the controller."""

    def __init__(
        self,
        hass: HomeAssistant,
        controller: HeatingController,
        *,
        timing: TimingPolicy = TimingPolicy(),
        on_state_changed: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Create an adapter around the configured core controller."""
        if not isinstance(timing, TimingPolicy):
            raise TypeError("timing must be a TimingPolicy")

        self._hass = hass
        self._controller = controller
        self._maintenance_interval = timedelta(
            seconds=timing.maintenance_interval_seconds
        )
        self._on_state_changed = on_state_changed
        self._unsubscribe_maintenance: Callable[[], None] | None = None
        self._maintenance_tasks: set[asyncio.Task[None]] = set()

    async def handle_start_heating_signal(self) -> None:
        """Forward a Home Assistant start-heating signal to the controller."""
        try:
            await self._controller.handle_start_heating()
        finally:
            await self._async_notify_state_changed()

    async def handle_stop_heating_signal(self) -> None:
        """Forward a Home Assistant stop-heating signal to the controller."""
        try:
            await self._controller.handle_stop_heating()
        finally:
            await self._async_notify_state_changed()

    async def run_maintenance(self) -> None:
        """Run one externally scheduled maintenance cycle."""
        try:
            await self._controller.maintain_requested_mode()
        finally:
            await self._async_notify_state_changed()

    async def async_start(self) -> None:
        """Register the adapter's recurring maintenance schedule."""
        if self._unsubscribe_maintenance is None:
            self._unsubscribe_maintenance = async_track_time_interval(
                self._hass,
                self._schedule_maintenance,
                self._maintenance_interval,
            )

    async def async_stop(self) -> None:
        """Cancel recurring maintenance and outstanding adapter work."""
        if self._unsubscribe_maintenance is not None:
            self._unsubscribe_maintenance()
            self._unsubscribe_maintenance = None

        tasks = tuple(self._maintenance_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _schedule_maintenance(self, _: datetime) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._maintenance_tasks.add(task)
        try:
            await self.run_maintenance()
        except Exception:
            _LOGGER.exception("Scheduled heating maintenance failed")
        finally:
            if task is not None:
                self._maintenance_tasks.discard(task)

    async def _async_notify_state_changed(self) -> None:
        if self._on_state_changed is None:
            return
        try:
            await self._on_state_changed()
        except Exception:
            _LOGGER.exception("Heating state persistence callback failed")

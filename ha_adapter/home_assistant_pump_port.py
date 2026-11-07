"""Home Assistant implementation of the core pump boundary."""

from __future__ import annotations

import asyncio
import logging

from homeassistant.components.number import (
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceNotFound

from dm_accounting.transaction import PumpPort, PumpWriteOutcome


_LOGGER = logging.getLogger(__name__)


class HomeAssistantPumpReadError(RuntimeError):
    """The configured Home Assistant entity cannot provide an integer DM value."""


class HomeAssistantPumpPort(PumpPort):
    """Reads and writes the configured pump number through Home Assistant."""

    def __init__(self, hass: HomeAssistant, pump_entity_id: str) -> None:
        """Create a port for the Home Assistant entity representing pump DM."""
        if not isinstance(pump_entity_id, str) or not pump_entity_id.startswith(
            f"{NUMBER_DOMAIN}."
        ):
            raise ValueError("pump_entity_id must be a number.* entity ID")

        self._hass = hass
        self._pump_entity_id = pump_entity_id

    async def read_degree_minutes(self) -> int:
        """Read a fresh degree-minute value from Home Assistant."""
        state = self._hass.states.get(self._pump_entity_id)
        if state is None:
            raise HomeAssistantPumpReadError(
                f"pump entity {self._pump_entity_id!r} does not exist"
            )
        if state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            raise HomeAssistantPumpReadError(
                f"pump entity {self._pump_entity_id!r} is {state.state}"
            )

        try:
            return self._parse_degree_minutes(state.state)
        except ValueError as error:
            raise HomeAssistantPumpReadError(
                f"pump entity {self._pump_entity_id!r} has non-integer state "
                f"{state.state!r}"
            ) from error

    async def write_degree_minutes(
        self, target_degree_minutes: int
    ) -> PumpWriteOutcome:
        """Attempt to set the absolute pump DM value and classify the outcome."""
        if not isinstance(target_degree_minutes, int) or isinstance(
            target_degree_minutes, bool
        ):
            return PumpWriteOutcome.NOT_ATTEMPTED

        state = self._hass.states.get(self._pump_entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return PumpWriteOutcome.NOT_ATTEMPTED

        try:
            _LOGGER.debug(
                "Writing pump entity: entity_id=%s target_degree_minutes=%s",
                self._pump_entity_id,
                target_degree_minutes,
            )
            await self._hass.services.async_call(
                NUMBER_DOMAIN,
                SERVICE_SET_VALUE,
                {
                    ATTR_ENTITY_ID: self._pump_entity_id,
                    ATTR_VALUE: target_degree_minutes,
                },
                blocking=True,
            )
        except ServiceNotFound:
            return PumpWriteOutcome.NOT_ATTEMPTED
        except (HomeAssistantError, asyncio.TimeoutError):
            return PumpWriteOutcome.UNKNOWN

        return PumpWriteOutcome.ACCEPTED

    @staticmethod
    def _parse_degree_minutes(value: str) -> int:
        """Return an integer-formatted HA state, rejecting fractional values."""
        if not value or value.strip() != value:
            raise ValueError("empty or whitespace-padded value")
        if value.startswith(("+", "-")):
            digits = value[1:]
        else:
            digits = value
        if not digits.isdecimal():
            raise ValueError("not an integer")
        return int(value)

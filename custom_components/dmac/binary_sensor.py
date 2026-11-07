"""DMAC requested-heating binary sensor platform."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from dm_accounting import HeatingMode

from .const import DOMAIN, SIGNAL_STATE_UPDATED


class DmacHeatingRequestedBinarySensor(BinarySensorEntity):
    """Expose whether the controller is currently asked to heat."""

    _attr_name = "DMAC Heating Requested"
    _attr_unique_id = "dmac_heating_requested"

    def __init__(self, runtime: Any) -> None:
        """Create a binary sensor backed by the integration runtime."""
        self._runtime = runtime

    @property
    def is_on(self) -> bool:
        """Return whether heating is currently requested."""
        return self._runtime.controller.requested_mode is HeatingMode.HEATING

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return the controller status alongside requested heating."""
        return {
            "controller_status": self._runtime.controller.status.name.lower(),
        }

    async def async_added_to_hass(self) -> None:
        """Refresh the entity whenever the runtime publishes a state change."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_STATE_UPDATED,
                self.async_write_ha_state,
            )
        )


async def async_setup_platform(
    hass: HomeAssistant,
    _: dict[str, Any],
    async_add_entities: Any,
    discovery_info: dict[str, Any] | None = None,
) -> None:
    """Set up the requested-heating binary sensor from the DMAC runtime."""
    del discovery_info
    runtime = hass.data.get(DOMAIN)
    if runtime is not None:
        async_add_entities([DmacHeatingRequestedBinarySensor(runtime)])

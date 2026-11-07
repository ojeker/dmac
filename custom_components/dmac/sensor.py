"""DMAC account-balance sensor platform."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN, SIGNAL_STATE_UPDATED


class DmacAccountDegreeMinutesSensor(SensorEntity):
    """Expose the DMAC account's signed degree-minute balance."""

    _attr_name = "DMAC Account Degree Minutes"
    _attr_unique_id = "dmac_account_degree_minutes"
    _attr_native_unit_of_measurement = "DM"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, runtime: Any) -> None:
        """Create a sensor backed by the integration runtime."""
        self._runtime = runtime

    @property
    def native_value(self) -> int:
        """Return the current signed account balance."""
        return self._runtime.account.degree_minutes

    @property
    def extra_state_attributes(self) -> dict[str, str | int | None]:
        """Return current controller and pending-transaction diagnostics."""
        transaction = self._runtime.controller.unvalidated_transaction
        attributes: dict[str, str | int | None] = {
            "requested_mode": self._runtime.controller.requested_mode.name.lower(),
            "controller_status": self._runtime.controller.status.name.lower(),
        }
        if transaction is not None:
            attributes.update(
                {
                    "pending_degree_minutes": transaction.degree_minutes,
                    "pending_direction": transaction.direction.name.lower(),
                    "pending_status": transaction.status.name.lower(),
                }
            )
        return attributes

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
    """Set up the account-balance sensor from the configured DMAC runtime."""
    del discovery_info
    runtime = hass.data.get(DOMAIN)
    if runtime is not None:
        async_add_entities([DmacAccountDegreeMinutesSensor(runtime)])

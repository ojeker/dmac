"""YAML setup, services, and persistence for the DMAC integration."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import sys
from typing import Any

import voluptuous as vol

# Release archives vendor the core and adapter packages beside this integration.
# A checkout still finds them through its project-root import path.
_VENDORED_PACKAGE_ROOT = str(Path(__file__).resolve().parent)
if _VENDORED_PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, _VENDORED_PACKAGE_ROOT)

from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.storage import Store

from dm_accounting import (
    Account,
    FixedReserves,
    HeatingController,
    HeatingMode,
    PumpLimits,
    TimingPolicy,
    TransactionPlanner,
)
from ha_adapter import (
    HomeAssistantHeatingAdapter,
    HomeAssistantPumpPort,
    HomeAssistantVerificationScheduler,
)

from .const import (
    CONF_IDLING_FLOOR_RESERVE,
    CONF_FINAL_VERIFICATION_DELAY_SECONDS,
    CONF_FIRST_VERIFICATION_DELAY_SECONDS,
    CONF_MAINTENANCE_INTERVAL_SECONDS,
    CONF_PUMP_ENTITY_ID,
    CONF_RUNNING_STOP_RESERVE,
    DOMAIN,
    SERVICE_START_HEATING,
    SERVICE_STOP_HEATING,
    SIGNAL_STATE_UPDATED,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)


def _strict_integer(value: object) -> int:
    """Validate an integer while refusing booleans and coercion."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise vol.Invalid("expected an integer")
    return value


def _positive_integer(value: object) -> int:
    """Validate a positive integer configuration value."""
    integer = _strict_integer(value)
    if integer <= 0:
        raise vol.Invalid("expected a positive integer")
    return integer


def _number_entity_id(value: object) -> str:
    """Validate the configured writable HA number entity ID."""
    entity_id = cv.entity_id(value)
    if not entity_id.startswith("number."):
        raise vol.Invalid("expected a number.* entity ID")
    return entity_id


def _test_timing_integer(value: object) -> int:
    """Accept timing overrides only in an explicitly enabled test process."""
    if os.environ.get("DMAC_TEST_MODE") != "1":
        raise vol.Invalid("timing overrides require DMAC_TEST_MODE=1")
    return _strict_integer(value)


CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_PUMP_ENTITY_ID): _number_entity_id,
                vol.Required(CONF_RUNNING_STOP_RESERVE): _positive_integer,
                vol.Required(CONF_IDLING_FLOOR_RESERVE): _positive_integer,
                vol.Optional(
                    CONF_FIRST_VERIFICATION_DELAY_SECONDS
                ): _test_timing_integer,
                vol.Optional(
                    CONF_FINAL_VERIFICATION_DELAY_SECONDS
                ): _test_timing_integer,
                vol.Optional(
                    CONF_MAINTENANCE_INTERVAL_SECONDS
                ): _test_timing_integer,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


@dataclass(slots=True)
class _Runtime:
    """The singleton objects owned by a configured DMAC integration."""

    account: Account
    controller: HeatingController
    adapter: HomeAssistantHeatingAdapter
    save_state: Callable[[], Awaitable[None]]


class _StateStore:
    """Serializes the persisted DMAC account and requested mode."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[Mapping[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY
        )
        self._lock = asyncio.Lock()

    async def async_load(self) -> tuple[int, HeatingMode]:
        """Load safe persisted state, falling back to a fresh idle account."""
        payload = await self._store.async_load()
        if payload is None:
            return 0, HeatingMode.IDLING
        try:
            balance = payload["account_degree_minutes"]
            mode = payload["requested_mode"]
            if not isinstance(balance, int) or isinstance(balance, bool):
                raise ValueError("account_degree_minutes must be an integer")
            if mode == "heating":
                return balance, HeatingMode.HEATING
            if mode == "idling":
                return balance, HeatingMode.IDLING
            raise ValueError("requested_mode must be heating or idling")
        except (KeyError, TypeError, ValueError):
            _LOGGER.warning("Ignoring malformed persisted DMAC state")
            return 0, HeatingMode.IDLING

    async def async_save(self, account: Account, controller: HeatingController) -> None:
        """Persist only restart-safe controller state."""
        payload = {
            "account_degree_minutes": account.degree_minutes,
            "requested_mode": controller.requested_mode.name.lower(),
        }
        async with self._lock:
            await self._store.async_save(payload)


async def async_setup(hass: HomeAssistant, config: Mapping[str, Any]) -> bool:
    """Set up DMAC from its single YAML configuration block."""
    settings = config.get(DOMAIN)
    if settings is None:
        return True
    if DOMAIN in hass.data:
        _LOGGER.error("DMAC is already configured")
        return False

    runtime = await _async_create_runtime(hass, settings)
    hass.data[DOMAIN] = runtime
    for platform in (Platform.SENSOR, Platform.BINARY_SENSOR):
        hass.async_create_task(async_load_platform(hass, platform, DOMAIN, {}, config))

    async def async_start_service(call: ServiceCall) -> None:
        await _async_start_heating(hass, call)

    async def async_stop_service(call: ServiceCall) -> None:
        await _async_stop_heating(hass, call)

    async def async_handle_home_assistant_stop(_: object) -> None:
        await _async_stop_integration(hass)

    hass.services.async_register(
        DOMAIN,
        SERVICE_START_HEATING,
        async_start_service,
        schema=vol.Schema({}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP_HEATING,
        async_stop_service,
        schema=vol.Schema({}),
    )
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_handle_home_assistant_stop)
    await runtime.adapter.async_start()
    return True


async def _async_create_runtime(
    hass: HomeAssistant, settings: Mapping[str, Any]
) -> _Runtime:
    state_store = _StateStore(hass)
    balance, requested_mode = await state_store.async_load()
    account = Account(balance)
    pump = HomeAssistantPumpPort(hass, settings[CONF_PUMP_ENTITY_ID])
    default_timing = TimingPolicy()
    timing = TimingPolicy(
        first_verification_delay_seconds=settings.get(
            CONF_FIRST_VERIFICATION_DELAY_SECONDS,
            default_timing.first_verification_delay_seconds,
        ),
        final_verification_delay_seconds=settings.get(
            CONF_FINAL_VERIFICATION_DELAY_SECONDS,
            default_timing.final_verification_delay_seconds,
        ),
        maintenance_interval_seconds=settings.get(
            CONF_MAINTENANCE_INTERVAL_SECONDS,
            default_timing.maintenance_interval_seconds,
        ),
    )
    runtime: _Runtime | None = None

    async def save_state() -> None:
        if runtime is None:
            return
        await state_store.async_save(runtime.account, runtime.controller)
        async_dispatcher_send(hass, SIGNAL_STATE_UPDATED)

    scheduler = HomeAssistantVerificationScheduler(hass, save_state)
    planner = TransactionPlanner(
        PumpLimits(),
        FixedReserves(
            settings[CONF_RUNNING_STOP_RESERVE],
            settings[CONF_IDLING_FLOOR_RESERVE],
        ),
        timing=timing,
    )
    controller = HeatingController(
        account,
        planner,
        pump,
        scheduler,
        initial_requested_mode=requested_mode,
    )
    adapter = HomeAssistantHeatingAdapter(
        hass,
        controller,
        timing=timing,
        on_state_changed=save_state,
    )
    runtime = _Runtime(account, controller, adapter, save_state)
    return runtime


async def _async_start_heating(hass: HomeAssistant, _: ServiceCall) -> None:
    runtime: _Runtime = hass.data[DOMAIN]
    await runtime.adapter.handle_start_heating_signal()


async def _async_stop_heating(hass: HomeAssistant, _: ServiceCall) -> None:
    runtime: _Runtime = hass.data[DOMAIN]
    await runtime.adapter.handle_stop_heating_signal()


async def _async_stop_integration(hass: HomeAssistant) -> None:
    """Persist final state and cancel adapter work at Home Assistant shutdown."""
    runtime: _Runtime | None = hass.data.get(DOMAIN)
    if runtime is None:
        return
    await runtime.adapter.async_stop()
    await runtime.save_state()

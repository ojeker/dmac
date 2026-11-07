"""Tests for the Home Assistant pump adapter."""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from homeassistant.components.number import ATTR_VALUE, DOMAIN, SERVICE_SET_VALUE
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

from dm_accounting import PumpWriteOutcome
from ha_adapter import HomeAssistantPumpPort, HomeAssistantPumpReadError


@pytest_asyncio.fixture
async def hass(tmp_path) -> HomeAssistant:
    """Provide a minimal live HA object for adapter tests."""
    return HomeAssistant(str(tmp_path))


@pytest.mark.asyncio
async def test_reads_an_integer_number_entity(hass: HomeAssistant) -> None:
    hass.states.async_set("number.pump_dm", "-1200")

    assert await HomeAssistantPumpPort(hass, "number.pump_dm").read_degree_minutes() == -1200


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["unknown", "unavailable", "-12.5", " 12", "abc"])
async def test_rejects_unusable_number_states(hass: HomeAssistant, state: str) -> None:
    hass.states.async_set("number.pump_dm", state)

    with pytest.raises(HomeAssistantPumpReadError):
        await HomeAssistantPumpPort(hass, "number.pump_dm").read_degree_minutes()


@pytest.mark.asyncio
async def test_rejects_a_missing_number_entity(hass: HomeAssistant) -> None:
    with pytest.raises(HomeAssistantPumpReadError):
        await HomeAssistantPumpPort(hass, "number.pump_dm").read_degree_minutes()


@pytest.mark.asyncio
async def test_writes_an_absolute_target_with_number_service(hass: HomeAssistant) -> None:
    calls: list[ServiceCall] = []

    async def set_value(call: ServiceCall) -> None:
        calls.append(call)

    hass.services.async_register(DOMAIN, SERVICE_SET_VALUE, set_value)
    hass.states.async_set("number.pump_dm", "-1200")

    result = await HomeAssistantPumpPort(hass, "number.pump_dm").write_degree_minutes(-1700)

    assert result is PumpWriteOutcome.ACCEPTED
    assert len(calls) == 1
    assert calls[0].data == {ATTR_ENTITY_ID: "number.pump_dm", ATTR_VALUE: -1700}


@pytest.mark.asyncio
async def test_does_not_attempt_write_without_a_writable_entity(hass: HomeAssistant) -> None:
    port = HomeAssistantPumpPort(hass, "number.pump_dm")

    assert await port.write_degree_minutes(-1700) is PumpWriteOutcome.NOT_ATTEMPTED

    hass.states.async_set("number.pump_dm", "unavailable")
    assert await port.write_degree_minutes(-1700) is PumpWriteOutcome.NOT_ATTEMPTED


@pytest.mark.asyncio
async def test_marks_service_failure_as_unknown(hass: HomeAssistant) -> None:
    async def set_value(_: ServiceCall) -> None:
        raise HomeAssistantError("integration failed after dispatch")

    hass.services.async_register(DOMAIN, SERVICE_SET_VALUE, set_value)
    hass.states.async_set("number.pump_dm", "-1200")

    result = await HomeAssistantPumpPort(hass, "number.pump_dm").write_degree_minutes(-1700)

    assert result is PumpWriteOutcome.UNKNOWN


@pytest.mark.asyncio
async def test_propagates_cancellation_during_write(hass: HomeAssistant) -> None:
    entered = asyncio.Event()

    async def set_value(_: ServiceCall) -> None:
        entered.set()
        await asyncio.Event().wait()

    hass.services.async_register(DOMAIN, SERVICE_SET_VALUE, set_value)
    hass.states.async_set("number.pump_dm", "-1200")
    task = hass.async_create_task(
        HomeAssistantPumpPort(hass, "number.pump_dm").write_degree_minutes(-1700)
    )
    await entered.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


def test_requires_a_number_entity_id(hass: HomeAssistant) -> None:
    with pytest.raises(ValueError, match=r"number\.\*"):
        HomeAssistantPumpPort(hass, "sensor.pump_dm")

"""Tests for YAML DMAC integration wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant

from dm_accounting import Account, ControllerStatus, HeatingMode, TimingPolicy
from custom_components.dmac import (
    CONFIG_SCHEMA,
    _Runtime,
    _StateStore,
    _async_create_runtime,
    _async_stop_integration,
    async_setup,
)
from custom_components.dmac.const import (
    CONF_IDLING_FLOOR_RESERVE,
    CONF_FINAL_VERIFICATION_DELAY_SECONDS,
    CONF_FIRST_VERIFICATION_DELAY_SECONDS,
    CONF_MAINTENANCE_INTERVAL_SECONDS,
    CONF_PUMP_ENTITY_ID,
    CONF_RUNNING_STOP_RESERVE,
    DOMAIN,
    SERVICE_START_HEATING,
    SERVICE_STOP_HEATING,
)


class _Controller:
    def __init__(self, mode: HeatingMode) -> None:
        self.requested_mode = mode
        self.status = ControllerStatus.OPERATING
        self.unvalidated_transaction = None


class _Adapter:
    def __init__(self) -> None:
        self.async_start = AsyncMock()
        self.async_stop = AsyncMock()
        self.handle_start_heating_signal = AsyncMock()
        self.handle_stop_heating_signal = AsyncMock()


@pytest.fixture
def valid_settings() -> dict[str, object]:
    return {
        CONF_PUMP_ENTITY_ID: "number.pump_dm",
        CONF_RUNNING_STOP_RESERVE: 100,
        CONF_IDLING_FLOOR_RESERVE: 100,
    }


def test_schema_accepts_the_required_yaml_settings(valid_settings: dict[str, object]) -> None:
    assert CONFIG_SCHEMA({DOMAIN: valid_settings})[DOMAIN] == valid_settings


@pytest.mark.parametrize(
    "settings",
    [
        {
            CONF_PUMP_ENTITY_ID: "sensor.pump_dm",
            CONF_RUNNING_STOP_RESERVE: 100,
            CONF_IDLING_FLOOR_RESERVE: 100,
        },
        {
            CONF_PUMP_ENTITY_ID: "number.pump_dm",
            CONF_RUNNING_STOP_RESERVE: True,
            CONF_IDLING_FLOOR_RESERVE: 100,
        },
        {
            CONF_PUMP_ENTITY_ID: "number.pump_dm",
            CONF_RUNNING_STOP_RESERVE: 100,
        },
    ],
)
def test_schema_rejects_invalid_yaml_settings(settings: dict[str, object]) -> None:
    with pytest.raises(Exception):
        CONFIG_SCHEMA({DOMAIN: settings})


def test_schema_rejects_test_timing_without_test_mode(
    valid_settings: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DMAC_TEST_MODE", raising=False)
    settings = valid_settings | {CONF_FIRST_VERIFICATION_DELAY_SECONDS: 1}

    with pytest.raises(Exception):
        CONFIG_SCHEMA({DOMAIN: settings})


def test_schema_accepts_test_timing_with_test_mode(
    valid_settings: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DMAC_TEST_MODE", "1")
    settings = valid_settings | {
        CONF_FIRST_VERIFICATION_DELAY_SECONDS: 1,
        CONF_FINAL_VERIFICATION_DELAY_SECONDS: 2,
        CONF_MAINTENANCE_INTERVAL_SECONDS: 3,
    }

    assert CONFIG_SCHEMA({DOMAIN: settings})[DOMAIN] == settings


@pytest.mark.asyncio
async def test_setup_registers_services_routes_commands_and_starts_adapter(
    tmp_path, valid_settings: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    hass = HomeAssistant(str(tmp_path))
    await hass.async_start()
    adapter = _Adapter()
    runtime = _Runtime(
        account=Account(-250),
        controller=_Controller(HeatingMode.HEATING),  # type: ignore[arg-type]
        adapter=adapter,  # type: ignore[arg-type]
        save_state=AsyncMock(),
    )
    create_runtime = AsyncMock(return_value=runtime)
    load_platform = AsyncMock()
    monkeypatch.setattr("custom_components.dmac._async_create_runtime", create_runtime)
    monkeypatch.setattr("custom_components.dmac.async_load_platform", load_platform)

    assert await async_setup(hass, {DOMAIN: valid_settings})
    await hass.services.async_call(DOMAIN, SERVICE_START_HEATING, blocking=True)
    await hass.services.async_call(DOMAIN, SERVICE_STOP_HEATING, blocking=True)

    assert hass.data[DOMAIN] is runtime
    assert load_platform.await_count == 2
    adapter.async_start.assert_awaited_once_with()
    adapter.handle_start_heating_signal.assert_awaited_once_with()
    adapter.handle_stop_heating_signal.assert_awaited_once_with()
    await hass.async_stop(force=True)


@pytest.mark.asyncio
async def test_shutdown_stops_adapter_and_persists_final_state(tmp_path) -> None:
    hass = HomeAssistant(str(tmp_path))
    adapter = _Adapter()
    save_state = AsyncMock()
    hass.data[DOMAIN] = _Runtime(
        account=Account(0),
        controller=_Controller(HeatingMode.IDLING),  # type: ignore[arg-type]
        adapter=adapter,  # type: ignore[arg-type]
        save_state=save_state,
    )

    await _async_stop_integration(hass)

    adapter.async_stop.assert_awaited_once_with()
    save_state.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_state_store_serializes_balance_and_requested_mode(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hass = HomeAssistant(str(tmp_path))
    state_store = _StateStore(hass)
    account = Account(-500)
    controller = _Controller(HeatingMode.HEATING)
    save = AsyncMock()
    monkeypatch.setattr(state_store._store, "async_save", save)

    await state_store.async_save(account, controller)  # type: ignore[arg-type]

    save.assert_awaited_once_with(
        {"account_degree_minutes": -500, "requested_mode": "heating"}
    )


@pytest.mark.asyncio
async def test_state_store_falls_back_for_malformed_data(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    hass = HomeAssistant(str(tmp_path))
    state_store = _StateStore(hass)
    monkeypatch.setattr(state_store._store, "async_load", AsyncMock(return_value={"bad": "data"}))

    assert await state_store.async_load() == (0, HeatingMode.IDLING)


@pytest.mark.asyncio
async def test_runtime_passes_one_test_timing_policy_to_planner_and_adapter(
    tmp_path, valid_settings: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    hass = HomeAssistant(str(tmp_path))
    settings = valid_settings | {
        CONF_FIRST_VERIFICATION_DELAY_SECONDS: 1,
        CONF_FINAL_VERIFICATION_DELAY_SECONDS: 2,
        CONF_MAINTENANCE_INTERVAL_SECONDS: 3,
    }
    captured: dict[str, object] = {}

    class FakeStateStore:
        def __init__(self, _: HomeAssistant) -> None:
            pass

        async def async_load(self) -> tuple[int, HeatingMode]:
            return 0, HeatingMode.IDLING

        async def async_save(self, *_: object) -> None:
            return None

    class FakeScheduler:
        def __init__(self, _: HomeAssistant, __: object) -> None:
            pass

    class FakePlanner:
        def __init__(self, *_: object, timing: TimingPolicy) -> None:
            captured["planner_timing"] = timing

    class FakeController:
        def __init__(self, *_: object, initial_requested_mode: HeatingMode) -> None:
            self.requested_mode = initial_requested_mode

    class FakeAdapter:
        def __init__(self, _: HomeAssistant, __: object, *, timing: TimingPolicy, on_state_changed: object) -> None:
            captured["adapter_timing"] = timing

    monkeypatch.setattr("custom_components.dmac._StateStore", FakeStateStore)
    monkeypatch.setattr("custom_components.dmac.HomeAssistantVerificationScheduler", FakeScheduler)
    monkeypatch.setattr("custom_components.dmac.TransactionPlanner", FakePlanner)
    monkeypatch.setattr("custom_components.dmac.HeatingController", FakeController)
    monkeypatch.setattr("custom_components.dmac.HomeAssistantHeatingAdapter", FakeAdapter)

    runtime = await _async_create_runtime(hass, settings)

    assert isinstance(runtime.account, Account)
    assert captured["planner_timing"] == TimingPolicy(1, 2, 3)
    assert captured["adapter_timing"] is captured["planner_timing"]

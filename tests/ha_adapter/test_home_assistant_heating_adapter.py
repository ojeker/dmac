"""Tests for Home Assistant controller routing and lifecycle."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.core import HomeAssistant

from dm_accounting import HeatingController, TimingPolicy
from ha_adapter import HomeAssistantHeatingAdapter


@pytest.fixture
def controller() -> Mock:
    controller = Mock(spec=HeatingController)
    controller.handle_start_heating = AsyncMock()
    controller.handle_stop_heating = AsyncMock()
    controller.maintain_requested_mode = AsyncMock()
    return controller


@pytest.mark.asyncio
async def test_forwards_controller_operations(tmp_path, controller: Mock) -> None:
    state_changed = AsyncMock()
    adapter = HomeAssistantHeatingAdapter(
        HomeAssistant(str(tmp_path)), controller, on_state_changed=state_changed
    )

    await adapter.handle_start_heating_signal()
    await adapter.handle_stop_heating_signal()
    await adapter.run_maintenance()

    controller.handle_start_heating.assert_awaited_once_with()
    controller.handle_stop_heating.assert_awaited_once_with()
    controller.maintain_requested_mode.assert_awaited_once_with()
    assert state_changed.await_count == 3


@pytest.mark.asyncio
async def test_start_is_idempotent_and_stop_cancels_schedule(
    tmp_path, controller: Mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    hass = HomeAssistant(str(tmp_path))
    cancellations = 0
    scheduled_callback = None

    def track_time_interval(_, callback, interval):
        nonlocal cancellations, scheduled_callback
        assert interval == timedelta(minutes=10)
        scheduled_callback = callback

        def cancel() -> None:
            nonlocal cancellations
            cancellations += 1

        return cancel

    monkeypatch.setattr(
        "ha_adapter.home_assistant_heating_adapter.async_track_time_interval",
        track_time_interval,
    )
    adapter = HomeAssistantHeatingAdapter(hass, controller)

    await adapter.async_start()
    await adapter.async_start()
    assert scheduled_callback is not None

    await scheduled_callback(None)
    await adapter.async_stop()
    await adapter.async_stop()

    assert cancellations == 1
    controller.maintain_requested_mode.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_logs_a_scheduled_maintenance_failure(
    tmp_path, controller: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    controller.maintain_requested_mode.side_effect = RuntimeError("failed")
    adapter = HomeAssistantHeatingAdapter(HomeAssistant(str(tmp_path)), controller)

    with caplog.at_level(logging.ERROR):
        await adapter._schedule_maintenance(None)

    assert "Scheduled heating maintenance failed" in caplog.text


@pytest.mark.asyncio
async def test_uses_the_policy_maintenance_interval(
    tmp_path, controller: Mock
) -> None:
    scheduled_interval: timedelta | None = None

    def track_time_interval(_, __, interval):
        nonlocal scheduled_interval
        scheduled_interval = interval
        return lambda: None

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "ha_adapter.home_assistant_heating_adapter.async_track_time_interval",
        track_time_interval,
    )
    try:
        adapter = HomeAssistantHeatingAdapter(
            HomeAssistant(str(tmp_path)),
            controller,
            timing=TimingPolicy(1, 2, 7),
        )
        await adapter.async_start()
    finally:
        monkeypatch.undo()

    assert scheduled_interval == timedelta(seconds=7)

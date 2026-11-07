"""Tests for the Home Assistant verification scheduler."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant

from ha_adapter import HomeAssistantVerificationScheduler


@pytest.mark.asyncio
async def test_runs_a_delayed_callback(tmp_path) -> None:
    hass = HomeAssistant(str(tmp_path))
    await hass.async_start()
    completed = asyncio.Event()
    callback_complete = AsyncMock()

    async def callback() -> None:
        completed.set()

    HomeAssistantVerificationScheduler(hass, callback_complete).call_later(0, callback)

    await asyncio.wait_for(completed.wait(), timeout=1)
    callback_complete.assert_awaited_once_with()
    await hass.async_stop(force=True)


@pytest.mark.asyncio
async def test_cancels_a_callback_before_it_runs(tmp_path) -> None:
    hass = HomeAssistant(str(tmp_path))
    await hass.async_start()
    completed = asyncio.Event()

    async def callback() -> None:
        completed.set()

    scheduled = HomeAssistantVerificationScheduler(hass).call_later(0, callback)
    scheduled.cancel()
    scheduled.cancel()

    await asyncio.sleep(0.05)
    assert not completed.is_set()
    await hass.async_stop(force=True)


@pytest.mark.asyncio
async def test_logs_a_callback_failure_and_keeps_home_assistant_running(
    tmp_path, caplog: pytest.LogCaptureFixture
) -> None:
    hass = HomeAssistant(str(tmp_path))
    await hass.async_start()

    async def callback() -> None:
        raise RuntimeError("verification failed")

    with caplog.at_level(logging.ERROR):
        HomeAssistantVerificationScheduler(hass).call_later(0, callback)
        await asyncio.sleep(0.05)

    assert "Delayed verification callback failed" in caplog.text
    await hass.async_stop(force=True)


@pytest.mark.asyncio
async def test_rejects_an_invalid_delay(tmp_path) -> None:
    scheduler = HomeAssistantVerificationScheduler(HomeAssistant(str(tmp_path)))

    with pytest.raises(ValueError):
        scheduler.call_later(-1, _no_op)


async def _no_op() -> None:
    return None

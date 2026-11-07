import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from dm_accounting import PumpWriteOutcome
from ha_adapter import HomeAssistantPumpPort


@pytest.mark.asyncio
async def test_pump_entity_write_is_logged_at_debug(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="ha_adapter.home_assistant_pump_port")
    services = SimpleNamespace(async_call=AsyncMock())
    hass = SimpleNamespace(
        states=SimpleNamespace(get=lambda _: SimpleNamespace(state="-1000")),
        services=services,
    )
    port = HomeAssistantPumpPort(hass, "number.pump_dm")

    outcome = await port.write_degree_minutes(-2900)

    assert outcome is PumpWriteOutcome.ACCEPTED
    assert any(
        record.levelno == logging.DEBUG
        and record.name == "ha_adapter.home_assistant_pump_port"
        and "Writing pump entity" in record.getMessage()
        for record in caplog.records
    )

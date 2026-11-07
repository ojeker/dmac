from types import SimpleNamespace

import pytest

from dm_accounting import (
    Account,
    ControllerStatus,
    HeatingMode,
    Transaction,
    TransferDirection,
)
from custom_components.dmac.binary_sensor import DmacHeatingRequestedBinarySensor
from custom_components.dmac.binary_sensor import async_setup_platform as async_setup_binary_sensor
from custom_components.dmac.sensor import DmacAccountDegreeMinutesSensor
from custom_components.dmac.sensor import async_setup_platform as async_setup_sensor


def test_account_sensor_exposes_balance_controller_and_pending_transaction() -> None:
    transaction = Transaction(-500, TransferDirection.ACCOUNT_TO_PUMP)
    runtime = SimpleNamespace(
        account=Account(-1200),
        controller=SimpleNamespace(
            requested_mode=HeatingMode.HEATING,
            status=ControllerStatus.OPERATING,
            unvalidated_transaction=transaction,
        ),
    )

    sensor = DmacAccountDegreeMinutesSensor(runtime)

    assert sensor.native_value == -1200
    assert sensor.extra_state_attributes == {
        "requested_mode": "heating",
        "controller_status": "operating",
        "pending_degree_minutes": -500,
        "pending_direction": "account_to_pump",
        "pending_status": "planned",
    }


def test_heating_requested_binary_sensor_follows_requested_mode() -> None:
    controller = SimpleNamespace(
        requested_mode=HeatingMode.IDLING,
        status=ControllerStatus.OPERATING,
    )
    sensor = DmacHeatingRequestedBinarySensor(
        SimpleNamespace(controller=controller)
    )

    assert sensor.is_on is False
    assert sensor.extra_state_attributes == {"controller_status": "operating"}

    controller.requested_mode = HeatingMode.HEATING

    assert sensor.is_on is True


@pytest.mark.asyncio
async def test_platforms_add_entities_from_the_configured_runtime() -> None:
    runtime = SimpleNamespace(
        account=Account(-1200),
        controller=SimpleNamespace(
            requested_mode=HeatingMode.IDLING,
            status=ControllerStatus.OPERATING,
            unvalidated_transaction=None,
        ),
    )
    hass = SimpleNamespace(data={"dmac": runtime})
    sensor_entities: list[object] = []
    binary_sensor_entities: list[object] = []

    await async_setup_sensor(
        hass,
        {},
        sensor_entities.extend,
    )
    await async_setup_binary_sensor(
        hass,
        {},
        binary_sensor_entities.extend,
    )

    assert isinstance(sensor_entities[0], DmacAccountDegreeMinutesSensor)
    assert isinstance(binary_sensor_entities[0], DmacHeatingRequestedBinarySensor)

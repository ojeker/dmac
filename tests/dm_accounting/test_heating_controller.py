import asyncio
from collections.abc import Awaitable, Callable

import pytest

from dm_accounting import (
    Account,
    ControllerStatus,
    FixedReserves,
    HeatingController,
    HeatingMode,
    PumpLimits,
    PumpWriteOutcome,
    TransactionPlanner,
)


class FakePump:
    def __init__(
        self,
        readings: list[int | Exception],
        outcome: PumpWriteOutcome = PumpWriteOutcome.ACCEPTED,
    ) -> None:
        self._readings = readings
        self._outcome = outcome
        self.written_targets: list[int] = []

    async def read_degree_minutes(self) -> int:
        result = self._readings.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def write_degree_minutes(self, target_degree_minutes: int) -> PumpWriteOutcome:
        self.written_targets.append(target_degree_minutes)
        return self._outcome


class ScheduledCall:
    def __init__(self, callback: Callable[[], Awaitable[None]]) -> None:
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class ManualScheduler:
    def __init__(self) -> None:
        self.calls: dict[int, list[ScheduledCall]] = {}

    def call_later(
        self,
        delay_seconds: int,
        callback: Callable[[], Awaitable[None]],
    ) -> ScheduledCall:
        call = ScheduledCall(callback)
        self.calls.setdefault(delay_seconds, []).append(call)
        return call

    async def run(self, delay_seconds: int) -> None:
        for call in self.calls.get(delay_seconds, []):
            if not call.cancelled:
                await call.callback()


class BlockingPump(FakePump):
    def __init__(self) -> None:
        super().__init__([-1000, -1000])
        self.read_started = asyncio.Event()
        self.release_first_read = asyncio.Event()
        self._first_read = True

    async def read_degree_minutes(self) -> int:
        if self._first_read:
            self._first_read = False
            self.read_started.set()
            await self.release_first_read.wait()
        return await super().read_degree_minutes()


@pytest.fixture
def planner() -> TransactionPlanner:
    return TransactionPlanner(PumpLimits(), FixedReserves())


def test_controller_starts_idling(planner: TransactionPlanner) -> None:
    controller = HeatingController(Account(-500), planner, FakePump([]), ManualScheduler())

    assert controller.requested_mode is HeatingMode.IDLING
    assert controller.status is ControllerStatus.OPERATING
    assert controller.unvalidated_transaction is None


@pytest.mark.asyncio
async def test_start_creates_an_unvalidated_transaction_at_floor_margin(
    planner: TransactionPlanner,
) -> None:
    account = Account(-5000)
    pump = FakePump([-1000, -1000])
    controller = HeatingController(account, planner, pump, ManualScheduler())

    await controller.handle_start_heating()

    assert controller.requested_mode is HeatingMode.HEATING
    assert pump.written_targets == [-2900]
    assert account.degree_minutes == -3100
    assert controller.unvalidated_transaction is not None


@pytest.mark.asyncio
async def test_idling_maintenance_transfers_pump_debt_at_floor_reserve(
    planner: TransactionPlanner,
) -> None:
    pump = FakePump([-2900, -2900])
    controller = HeatingController(Account(-500), planner, pump, ManualScheduler())

    await controller.maintain_requested_mode()

    assert pump.written_targets == [0]
    assert controller.unvalidated_transaction is not None


@pytest.mark.asyncio
async def test_stop_requested_during_start_runs_after_start_verifies(
    planner: TransactionPlanner,
) -> None:
    scheduler = ManualScheduler()
    pump = FakePump([-1000, -1000, -2887, -2887, -2887])
    controller = HeatingController(Account(-5000), planner, pump, scheduler)

    await controller.handle_start_heating()
    await controller.handle_stop_heating()
    await scheduler.run(90)

    assert controller.requested_mode is HeatingMode.IDLING
    assert pump.written_targets == [-2900, 0]
    assert controller.unvalidated_transaction is not None


@pytest.mark.asyncio
async def test_final_verification_failure_enters_error_and_blocks_writes(
    planner: TransactionPlanner,
) -> None:
    scheduler = ManualScheduler()
    pump = FakePump([-1000, -1000, -2886, -2879])
    controller = HeatingController(Account(-5000), planner, pump, scheduler)

    await controller.handle_start_heating()
    await scheduler.run(90)
    await scheduler.run(180)
    await controller.handle_stop_heating()

    assert controller.status is ControllerStatus.ERROR
    assert controller.unvalidated_transaction is None
    assert pump.written_targets == [-2900]


@pytest.mark.asyncio
async def test_not_attempted_write_enters_error(planner: TransactionPlanner) -> None:
    pump = FakePump([-1000, -1000], PumpWriteOutcome.NOT_ATTEMPTED)
    controller = HeatingController(Account(-5000), planner, pump, ManualScheduler())

    await controller.handle_start_heating()

    assert controller.status is ControllerStatus.ERROR
    assert controller.unvalidated_transaction is None
    assert pump.written_targets == [-2900]


@pytest.mark.asyncio
async def test_pump_read_failure_enters_error_and_propagates(
    planner: TransactionPlanner,
) -> None:
    controller = HeatingController(
        Account(-5000),
        planner,
        FakePump([RuntimeError("pump unavailable")]),
        ManualScheduler(),
    )

    with pytest.raises(RuntimeError, match="pump unavailable"):
        await controller.handle_start_heating()

    assert controller.status is ControllerStatus.ERROR
    assert controller.unvalidated_transaction is None


@pytest.mark.asyncio
async def test_signal_updates_intent_while_pump_read_is_in_progress(
    planner: TransactionPlanner,
) -> None:
    pump = BlockingPump()
    controller = HeatingController(Account(-5000), planner, pump, ManualScheduler())

    start_task = asyncio.create_task(controller.handle_start_heating())
    await pump.read_started.wait()
    stop_task = asyncio.create_task(controller.handle_stop_heating())
    await asyncio.sleep(0)

    assert controller.requested_mode is HeatingMode.IDLING

    pump.release_first_read.set()
    await start_task
    await stop_task

    assert pump.written_targets == [0]

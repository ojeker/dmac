import asyncio
from collections.abc import Awaitable, Callable

import pytest

from dm_accounting import (
    Account,
    PumpWriteOutcome,
    Transaction,
    TransactionStatus,
    TimingPolicy,
    TransferDirection,
)


class FakePump:
    def __init__(
        self,
        readings: list[int | Exception],
        write_outcome: PumpWriteOutcome = PumpWriteOutcome.ACCEPTED,
    ) -> None:
        self._readings = readings
        self._write_outcome = write_outcome
        self.written_targets: list[int] = []

    async def read_degree_minutes(self) -> int:
        result = self._readings.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def write_degree_minutes(self, target_degree_minutes: int) -> PumpWriteOutcome:
        self.written_targets.append(target_degree_minutes)
        return self._write_outcome


class ManualScheduledCall:
    def __init__(self, callback: Callable[[], Awaitable[None]]) -> None:
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class ManualVerificationScheduler:
    def __init__(self) -> None:
        self.calls: dict[int, list[ManualScheduledCall]] = {}

    def call_later(
        self,
        delay_seconds: int,
        callback: Callable[[], Awaitable[None]],
    ) -> ManualScheduledCall:
        scheduled_call = ManualScheduledCall(callback)
        self.calls.setdefault(delay_seconds, []).append(scheduled_call)
        return scheduled_call

    async def run(self, delay_seconds: int) -> None:
        for scheduled_call in self.calls.get(delay_seconds, []):
            if not scheduled_call.cancelled:
                await scheduled_call.callback()


class FailingVerificationScheduler:
    def call_later(
        self,
        delay_seconds: int,
        callback: Callable[[], Awaitable[None]],
    ) -> ManualScheduledCall:
        raise RuntimeError("scheduler unavailable")


class RecordingListener:
    def __init__(self) -> None:
        self.verified: list[Transaction] = []
        self.failed: list[Transaction] = []

    async def transaction_verified(self, transaction: Transaction) -> None:
        self.verified.append(transaction)

    async def transaction_failed(self, transaction: Transaction) -> None:
        self.failed.append(transaction)


@pytest.mark.parametrize(
    ("direction", "expected_target", "expected_account_delta"),
    [
        (TransferDirection.ACCOUNT_TO_PUMP, -2700, 700),
        (TransferDirection.PUMP_TO_ACCOUNT, -1300, -700),
    ],
)
def test_transaction_preserves_total_degree_minutes(
    direction: TransferDirection,
    expected_target: int,
    expected_account_delta: int,
) -> None:
    transaction = Transaction(-700, direction)
    account = Account(-1200)

    assert transaction.pump_target_for(-2000) == expected_target

    transaction.record_write_attempt(-2000, account)

    assert transaction.status is TransactionStatus.UNVALIDATED
    assert transaction.pre_write_pump_degree_minutes == -2000
    assert transaction.target_pump_degree_minutes == expected_target
    assert transaction.account_degree_minutes_delta == expected_account_delta
    assert account.degree_minutes == -1200 + expected_account_delta
    assert account.degree_minutes + expected_target == -3200


def test_verified_transaction_keeps_applied_account_change() -> None:
    transaction = Transaction(-500, TransferDirection.ACCOUNT_TO_PUMP)
    account = Account(-900)

    transaction.record_write_attempt(-1000, account)
    transaction.mark_verified()

    assert transaction.status is TransactionStatus.VERIFIED
    assert account.degree_minutes == -400


def test_failed_transaction_rolls_back_applied_account_change() -> None:
    transaction = Transaction(-500, TransferDirection.ACCOUNT_TO_PUMP)
    account = Account(-900)

    transaction.record_write_attempt(-1000, account)
    transaction.mark_failed(account)

    assert transaction.status is TransactionStatus.FAILED
    assert account.degree_minutes == -900


@pytest.mark.parametrize("degree_minutes", [0, 1, 500, True])
def test_transaction_rejects_non_debt_amounts(degree_minutes: int) -> None:
    with pytest.raises((TypeError, ValueError)):
        Transaction(degree_minutes, TransferDirection.ACCOUNT_TO_PUMP)


def test_transaction_rejects_an_invalid_direction() -> None:
    with pytest.raises(TypeError):
        Transaction(-500, "account_to_pump")  # type: ignore[arg-type]


def test_transaction_rejects_repeated_or_invalid_lifecycle_transitions() -> None:
    transaction = Transaction(-500, TransferDirection.ACCOUNT_TO_PUMP)
    account = Account(-900)

    with pytest.raises(RuntimeError):
        transaction.mark_verified()
    with pytest.raises(RuntimeError):
        transaction.mark_failed(account)

    transaction.record_write_attempt(-1000, account)

    with pytest.raises(RuntimeError):
        transaction.record_write_attempt(-1000, account)

    transaction.mark_failed(account)

    with pytest.raises(RuntimeError):
        transaction.mark_failed(account)
    with pytest.raises(RuntimeError):
        transaction.mark_verified()


@pytest.mark.parametrize(
    "write_outcome",
    [PumpWriteOutcome.ACCEPTED, PumpWriteOutcome.UNKNOWN],
)
def test_execute_applies_account_change_and_schedules_verification(
    write_outcome: PumpWriteOutcome,
) -> None:
    transaction = Transaction(-500, TransferDirection.ACCOUNT_TO_PUMP)
    account = Account(-900)
    pump = FakePump([-1000], write_outcome)
    scheduler = ManualVerificationScheduler()
    listener = RecordingListener()

    outcome = asyncio.run(transaction.execute(account, pump, scheduler, listener))

    assert outcome is write_outcome
    assert pump.written_targets == [-1500]
    assert account.degree_minutes == -400
    assert transaction.status is TransactionStatus.UNVALIDATED
    assert sorted(scheduler.calls) == [90, 180]


def test_execute_uses_its_injected_verification_delays() -> None:
    transaction = Transaction(
        -500,
        TransferDirection.ACCOUNT_TO_PUMP,
        timing=TimingPolicy(1, 2, 3),
    )
    account = Account(-900)
    scheduler = ManualVerificationScheduler()

    asyncio.run(
        transaction.execute(
            account,
            FakePump([-1000]),
            scheduler,
            RecordingListener(),
        )
    )

    assert sorted(scheduler.calls) == [1, 2]


def test_not_attempted_write_keeps_transaction_planned() -> None:
    transaction = Transaction(-500, TransferDirection.ACCOUNT_TO_PUMP)
    account = Account(-900)
    pump = FakePump([-1000], PumpWriteOutcome.NOT_ATTEMPTED)
    scheduler = ManualVerificationScheduler()
    listener = RecordingListener()

    outcome = asyncio.run(transaction.execute(account, pump, scheduler, listener))

    assert outcome is PumpWriteOutcome.NOT_ATTEMPTED
    assert pump.written_targets == [-1500]
    assert transaction.status is TransactionStatus.PLANNED
    assert account.degree_minutes == -900
    assert scheduler.calls == {}


def test_first_successful_verification_notifies_and_cancels_final_check() -> None:
    transaction = Transaction(-500, TransferDirection.ACCOUNT_TO_PUMP)
    account = Account(-900)
    pump = FakePump([-1000, -1487])
    scheduler = ManualVerificationScheduler()
    listener = RecordingListener()

    asyncio.run(transaction.execute(account, pump, scheduler, listener))
    asyncio.run(scheduler.run(90))

    assert transaction.status is TransactionStatus.VERIFIED
    assert listener.verified == [transaction]
    assert listener.failed == []
    assert scheduler.calls[180][0].cancelled is True


def test_final_verification_succeeds_after_first_check_misses() -> None:
    transaction = Transaction(-500, TransferDirection.ACCOUNT_TO_PUMP)
    account = Account(-900)
    pump = FakePump([-1000, -1486, -1480])
    scheduler = ManualVerificationScheduler()
    listener = RecordingListener()

    asyncio.run(transaction.execute(account, pump, scheduler, listener))
    asyncio.run(scheduler.run(90))

    assert transaction.status is TransactionStatus.UNVALIDATED
    assert listener.verified == []

    asyncio.run(scheduler.run(180))

    assert transaction.status is TransactionStatus.VERIFIED
    assert listener.verified == [transaction]


@pytest.mark.parametrize(
    "final_reading",
    [-1479, RuntimeError("pump unavailable")],
)
def test_failed_final_verification_rolls_back_and_notifies(
    final_reading: int | Exception,
) -> None:
    transaction = Transaction(-500, TransferDirection.ACCOUNT_TO_PUMP)
    account = Account(-900)
    pump = FakePump([-1000, -1486, final_reading])
    scheduler = ManualVerificationScheduler()
    listener = RecordingListener()

    asyncio.run(transaction.execute(account, pump, scheduler, listener))
    asyncio.run(scheduler.run(90))
    asyncio.run(scheduler.run(180))

    assert transaction.status is TransactionStatus.FAILED
    assert account.degree_minutes == -900
    assert listener.verified == []
    assert listener.failed == [transaction]


def test_drift_tolerance_uses_elapsed_time() -> None:
    transaction = Transaction(-500, TransferDirection.ACCOUNT_TO_PUMP)
    account = Account(-900)
    transaction.record_write_attempt(-1000, account)

    assert transaction.verify(-1487, 90) is True
    assert transaction.verify(-1486, 90) is False
    assert transaction.verify(-1480, 180) is True
    assert transaction.verify(-1479, 180) is False


def test_small_transaction_is_rejected_before_pump_write() -> None:
    transaction = Transaction(-20, TransferDirection.ACCOUNT_TO_PUMP)
    account = Account(-900)
    pump = FakePump([-1000])
    scheduler = ManualVerificationScheduler()
    listener = RecordingListener()

    with pytest.raises(ValueError, match="too small"):
        asyncio.run(transaction.execute(account, pump, scheduler, listener))

    assert pump.written_targets == []
    assert account.degree_minutes == -900
    assert transaction.status is TransactionStatus.PLANNED


def test_small_stop_transaction_targeting_zero_is_permitted() -> None:
    transaction = Transaction(-10, TransferDirection.PUMP_TO_ACCOUNT)
    account = Account(-900)
    pump = FakePump([-10])
    scheduler = ManualVerificationScheduler()
    listener = RecordingListener()

    asyncio.run(transaction.execute(account, pump, scheduler, listener))

    assert pump.written_targets == [0]
    assert transaction.status is TransactionStatus.UNVALIDATED


def test_scheduler_failure_rolls_back_and_notifies() -> None:
    transaction = Transaction(-500, TransferDirection.ACCOUNT_TO_PUMP)
    account = Account(-900)
    pump = FakePump([-1000])
    listener = RecordingListener()

    with pytest.raises(RuntimeError, match="scheduler unavailable"):
        asyncio.run(
            transaction.execute(account, pump, FailingVerificationScheduler(), listener)
        )

    assert transaction.status is TransactionStatus.FAILED
    assert account.degree_minutes == -900
    assert listener.failed == [transaction]

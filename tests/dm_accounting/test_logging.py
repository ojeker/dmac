import asyncio
import logging
from collections.abc import Awaitable, Callable

import pytest

from dm_accounting import Account, PumpWriteOutcome, Transaction, TransferDirection


class _Pump:
    def __init__(self) -> None:
        self._readings = [-1000, -1487]

    async def read_degree_minutes(self) -> int:
        return self._readings.pop(0)

    async def write_degree_minutes(self, _: int) -> PumpWriteOutcome:
        return PumpWriteOutcome.ACCEPTED


class _Call:
    def __init__(self, callback: Callable[[], Awaitable[None]]) -> None:
        self.callback = callback

    def cancel(self) -> None:
        return None


class _Scheduler:
    def __init__(self) -> None:
        self.calls: dict[int, _Call] = {}

    def call_later(
        self,
        delay_seconds: int,
        callback: Callable[[], Awaitable[None]],
    ) -> _Call:
        call = _Call(callback)
        self.calls[delay_seconds] = call
        return call


class _Listener:
    async def transaction_verified(self, _: Transaction) -> None:
        return None

    async def transaction_failed(self, _: Transaction) -> None:
        return None


@pytest.mark.asyncio
async def test_transaction_emits_write_and_validation_info_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    transaction = Transaction(-500, TransferDirection.ACCOUNT_TO_PUMP)
    account = Account(-900)
    scheduler = _Scheduler()

    await transaction.execute(account, _Pump(), scheduler, _Listener())
    await scheduler.calls[90].callback()

    transaction_info_messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == "dm_accounting.transaction.transaction"
        and record.levelno == logging.INFO
    ]

    assert len(transaction_info_messages) == 2
    assert "Transaction pump write finished" in transaction_info_messages[0]
    assert "Transaction validation finished: outcome=verified" in transaction_info_messages[1]
    assert any(
        record.name == "dm_accounting.account"
        and record.levelno == logging.DEBUG
        and "Account balance written" in record.getMessage()
        for record in caplog.records
    )

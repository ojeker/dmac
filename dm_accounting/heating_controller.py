"""Serializes heating commands, maintenance, and transaction completion."""

import asyncio

from .account import Account
from .controller_status import ControllerStatus
from .tplanner import HeatingMode, TransactionPlanner
from .transaction import (
    PumpPort,
    PumpWriteOutcome,
    Transaction,
    VerificationListener,
    VerificationScheduler,
)


class HeatingController(VerificationListener):
    """Coordinates requested mode changes and periodic mode maintenance."""

    def __init__(
        self,
        account: Account,
        planner: TransactionPlanner,
        pump: PumpPort,
        verification_scheduler: VerificationScheduler,
        *,
        initial_requested_mode: HeatingMode = HeatingMode.IDLING,
    ) -> None:
        """Create a controller holding at most one unvalidated transaction."""
        if not isinstance(account, Account):
            raise TypeError("account must be an Account")
        if not isinstance(planner, TransactionPlanner):
            raise TypeError("planner must be a TransactionPlanner")
        if not isinstance(initial_requested_mode, HeatingMode):
            raise TypeError("initial requested mode must be HeatingMode")

        self._account = account
        self._planner = planner
        self._pump = pump
        self._verification_scheduler = verification_scheduler
        self._requested_mode = initial_requested_mode
        self._status = ControllerStatus.OPERATING
        self._unvalidated_transaction: Transaction | None = None
        self._state_change_requested = False
        self._state_lock = asyncio.Lock()
        self._reconciliation_lock = asyncio.Lock()

    @property
    def requested_mode(self) -> HeatingMode:
        """Return the most recently requested heating mode."""
        return self._requested_mode

    @property
    def status(self) -> ControllerStatus:
        """Return whether automatic heating control may continue."""
        return self._status

    @property
    def unvalidated_transaction(self) -> Transaction | None:
        """Return the one transaction whose pump write is not verified yet."""
        return self._unvalidated_transaction

    async def handle_start_heating(self) -> None:
        """Request heating and immediately plan its state-change transaction."""
        await self._request_mode(HeatingMode.HEATING)

    async def handle_stop_heating(self) -> None:
        """Request idling and immediately plan its state-change transaction."""
        await self._request_mode(HeatingMode.IDLING)

    async def maintain_requested_mode(self) -> None:
        """Periodically plan a transaction that preserves the requested mode."""
        await self._reconcile()

    async def transaction_verified(self, transaction: Transaction) -> None:
        """Clear the unvalidated transaction and reconcile the requested mode."""
        async with self._state_lock:
            if transaction is not self._unvalidated_transaction:
                return
            self._unvalidated_transaction = None
            if self._status is ControllerStatus.ERROR:
                return
        await self._reconcile()

    async def transaction_failed(self, transaction: Transaction) -> None:
        """Enter the controller error state after failed final verification."""
        async with self._state_lock:
            if transaction is not self._unvalidated_transaction:
                return
            self._unvalidated_transaction = None
            self._status = ControllerStatus.ERROR

    async def _request_mode(self, mode: HeatingMode) -> None:
        async with self._state_lock:
            self._requested_mode = mode
            self._state_change_requested = True
        await self._reconcile()

    async def _reconcile(self) -> None:
        async with self._reconciliation_lock:
            async with self._state_lock:
                if (
                    self._status is ControllerStatus.ERROR
                    or self._unvalidated_transaction is not None
                ):
                    return

            try:
                observed_pump_degree_minutes = await self._pump.read_degree_minutes()
                async with self._state_lock:
                    if (
                        self._status is ControllerStatus.ERROR
                        or self._unvalidated_transaction is not None
                    ):
                        return

                    if self._state_change_requested:
                        transaction = self._planner.plan_state_change(
                            self._account,
                            self._requested_mode,
                            observed_pump_degree_minutes,
                        )
                    else:
                        transaction = self._planner.plan_maintenance(
                            self._account,
                            self._requested_mode,
                            observed_pump_degree_minutes,
                        )
                    self._state_change_requested = False
                    if transaction is None:
                        return
                    self._unvalidated_transaction = transaction

                outcome = await transaction.execute(
                    self._account,
                    self._pump,
                    self._verification_scheduler,
                    self,
                )
            except Exception:
                async with self._state_lock:
                    if self._unvalidated_transaction is not None:
                        self._unvalidated_transaction = None
                    self._status = ControllerStatus.ERROR
                raise

            if outcome is PumpWriteOutcome.NOT_ATTEMPTED:
                async with self._state_lock:
                    if transaction is self._unvalidated_transaction:
                        self._unvalidated_transaction = None
                        self._status = ControllerStatus.ERROR

"""A transfer of degree minutes between the account and heat pump."""

from __future__ import annotations

from enum import Enum, auto
import logging
from math import ceil

from ..account import Account
from ..timing import TimingPolicy
from .pump_port import PumpPort
from .pump_write_outcome import PumpWriteOutcome
from .transaction_status import TransactionStatus
from .verification_listener import VerificationListener
from .verification_scheduler import ScheduledCall, VerificationScheduler


_LOGGER = logging.getLogger(__name__)


class TransferDirection(Enum):
    """The direction in which a transaction transfers degree minutes."""

    ACCOUNT_TO_PUMP = auto()
    PUMP_TO_ACCOUNT = auto()


class Transaction:
    """Tracks one degree-minute transfer until the pump write is verified."""

    MAXIMUM_NATURAL_DRIFT_PER_MINUTE = 5
    VERIFICATION_SAFETY_MARGIN_DEGREE_MINUTES = 5
    MINIMUM_RELIABLY_VERIFIABLE_DEGREE_MINUTES = 21

    def __init__(
        self,
        degree_minutes: int,
        direction: TransferDirection,
        *,
        timing: TimingPolicy = TimingPolicy(),
    ) -> None:
        """Create a transaction with its degree-minute value and direction."""
        if not isinstance(degree_minutes, int) or isinstance(degree_minutes, bool):
            raise TypeError("degree minutes must be an integer")
        if degree_minutes >= 0:
            raise ValueError("transactions must transfer a negative debt amount")
        if not isinstance(direction, TransferDirection):
            raise TypeError("direction must be a TransferDirection")
        if not isinstance(timing, TimingPolicy):
            raise TypeError("timing must be a TimingPolicy")

        self._degree_minutes = degree_minutes
        self._direction = direction
        self._timing = timing
        self._status = TransactionStatus.PLANNED
        self._pre_write_pump_degree_minutes: int | None = None
        self._target_pump_degree_minutes: int | None = None
        self._account_degree_minutes_delta: int | None = None
        self._verification_calls: list[ScheduledCall] = []

    @property
    def degree_minutes(self) -> int:
        """Return the signed debt amount transferred by this transaction."""
        return self._degree_minutes

    @property
    def direction(self) -> TransferDirection:
        """Return the transfer direction."""
        return self._direction

    @property
    def timing(self) -> TimingPolicy:
        """Return the immutable timing policy used for verification."""
        return self._timing

    @property
    def status(self) -> TransactionStatus:
        """Return the current transaction lifecycle state."""
        return self._status

    @property
    def pre_write_pump_degree_minutes(self) -> int | None:
        """Return the pump DM observed immediately before the write attempt."""
        return self._pre_write_pump_degree_minutes

    @property
    def target_pump_degree_minutes(self) -> int | None:
        """Return the absolute pump DM target after a write attempt."""
        return self._target_pump_degree_minutes

    @property
    def account_degree_minutes_delta(self) -> int | None:
        """Return the account change applied after the write attempt."""
        return self._account_degree_minutes_delta

    def pump_target_for(self, pre_write_pump_degree_minutes: int) -> int:
        """Calculate the absolute pump target from a pre-write DM observation."""
        self._require_degree_minutes(pre_write_pump_degree_minutes)
        if self._direction is TransferDirection.ACCOUNT_TO_PUMP:
            return pre_write_pump_degree_minutes + self._degree_minutes
        return pre_write_pump_degree_minutes - self._degree_minutes

    def record_write_attempt(
        self,
        pre_write_pump_degree_minutes: int,
        account: Account,
    ) -> None:
        """Record an attempted write and apply its equal-and-opposite account delta."""
        if self._status is not TransactionStatus.PLANNED:
            raise RuntimeError("a write attempt may only be recorded for a planned transaction")
        if not isinstance(account, Account):
            raise TypeError("account must be an Account")

        target_pump_degree_minutes = self.pump_target_for(
            pre_write_pump_degree_minutes
        )
        account_degree_minutes_delta = self._account_delta()
        account.apply(account_degree_minutes_delta)

        self._pre_write_pump_degree_minutes = pre_write_pump_degree_minutes
        self._target_pump_degree_minutes = target_pump_degree_minutes
        self._account_degree_minutes_delta = account_degree_minutes_delta
        self._status = TransactionStatus.UNVALIDATED

    def mark_verified(self) -> None:
        """Mark an unvalidated transaction as successfully verified."""
        self._require_unvalidated("verified")
        self._status = TransactionStatus.VERIFIED

    def mark_failed(self, account: Account) -> None:
        """Roll back the account change of an unvalidated transaction."""
        self._require_unvalidated("failed")
        if not isinstance(account, Account):
            raise TypeError("account must be an Account")

        assert self._account_degree_minutes_delta is not None
        account.apply(-self._account_degree_minutes_delta)
        self._status = TransactionStatus.FAILED

    async def execute(
        self,
        account: Account,
        pump: PumpPort,
        scheduler: VerificationScheduler,
        listener: VerificationListener,
    ) -> PumpWriteOutcome:
        """Write its target, update the account, and schedule verification checks."""
        if self._status is not TransactionStatus.PLANNED:
            raise RuntimeError("only a planned transaction can be executed")

        pre_write_pump_degree_minutes = await pump.read_degree_minutes()
        target_pump_degree_minutes = self.pump_target_for(
            pre_write_pump_degree_minutes
        )
        self._require_reliably_verifiable(target_pump_degree_minutes)

        outcome = await pump.write_degree_minutes(target_pump_degree_minutes)
        if not isinstance(outcome, PumpWriteOutcome):
            raise TypeError("pump write must return a PumpWriteOutcome")
        _LOGGER.info(
            "Transaction pump write finished: degree_minutes=%s direction=%s "
            "target_degree_minutes=%s outcome=%s",
            self._degree_minutes,
            self._direction.name.lower(),
            target_pump_degree_minutes,
            outcome.name.lower(),
        )
        if outcome is PumpWriteOutcome.NOT_ATTEMPTED:
            return outcome

        self.record_write_attempt(pre_write_pump_degree_minutes, account)
        try:
            self._verification_calls.append(
                scheduler.call_later(
                    self._timing.first_verification_delay_seconds,
                    lambda: self._verify_at(
                        self._timing.first_verification_delay_seconds,
                        pump,
                        account,
                        listener,
                    ),
                )
            )
            self._verification_calls.append(
                scheduler.call_later(
                    self._timing.final_verification_delay_seconds,
                    lambda: self._verify_at(
                        self._timing.final_verification_delay_seconds,
                        pump,
                        account,
                        listener,
                    ),
                )
            )
        except Exception:
            await self._fail_and_notify(account, listener)
            raise

        return outcome

    def verify(self, observed_pump_degree_minutes: int, elapsed_seconds: int) -> bool:
        """Verify the pump state and report whether this transaction is complete."""
        self._require_unvalidated("verified")
        self._require_degree_minutes(observed_pump_degree_minutes)
        if not isinstance(elapsed_seconds, int) or isinstance(elapsed_seconds, bool):
            raise TypeError("elapsed seconds must be an integer")
        if elapsed_seconds < 0:
            raise ValueError("elapsed seconds must not be negative")

        assert self._target_pump_degree_minutes is not None
        return (
            abs(observed_pump_degree_minutes - self._target_pump_degree_minutes)
            <= self._allowed_drift(elapsed_seconds)
        )

    def _account_delta(self) -> int:
        if self._direction is TransferDirection.ACCOUNT_TO_PUMP:
            return -self._degree_minutes
        return self._degree_minutes

    async def _verify_at(
        self,
        elapsed_seconds: int,
        pump: PumpPort,
        account: Account,
        listener: VerificationListener,
    ) -> None:
        if self._status is not TransactionStatus.UNVALIDATED:
            return

        try:
            observed_pump_degree_minutes = await pump.read_degree_minutes()
            verified = self.verify(observed_pump_degree_minutes, elapsed_seconds)
        except Exception:
            if elapsed_seconds == self._timing.final_verification_delay_seconds:
                await self._fail_and_notify(account, listener)
            return

        if verified:
            self.mark_verified()
            self._cancel_verification_calls()
            _LOGGER.info(
                "Transaction validation finished: outcome=verified "
                "observed_degree_minutes=%s",
                observed_pump_degree_minutes,
            )
            await listener.transaction_verified(self)
        elif elapsed_seconds == self._timing.final_verification_delay_seconds:
            await self._fail_and_notify(account, listener)

    async def _fail_and_notify(
        self,
        account: Account,
        listener: VerificationListener,
    ) -> None:
        if self._status is not TransactionStatus.UNVALIDATED:
            return
        self.mark_failed(account)
        self._cancel_verification_calls()
        _LOGGER.info("Transaction validation finished: outcome=failed")
        await listener.transaction_failed(self)

    def _cancel_verification_calls(self) -> None:
        for scheduled_call in self._verification_calls:
            scheduled_call.cancel()
        self._verification_calls.clear()

    def _require_reliably_verifiable(self, target_pump_degree_minutes: int) -> None:
        if (
            abs(self._degree_minutes)
            >= self.MINIMUM_RELIABLY_VERIFIABLE_DEGREE_MINUTES
        ):
            return
        if (
            self._direction is TransferDirection.PUMP_TO_ACCOUNT
            and target_pump_degree_minutes == 0
        ):
            return
        raise ValueError("transaction is too small to verify reliably")

    def _allowed_drift(self, elapsed_seconds: int) -> int:
        return (
            ceil(
                self.MAXIMUM_NATURAL_DRIFT_PER_MINUTE * elapsed_seconds / 60
            )
            + self.VERIFICATION_SAFETY_MARGIN_DEGREE_MINUTES
        )

    def _require_unvalidated(self, requested_state: str) -> None:
        if self._status is not TransactionStatus.UNVALIDATED:
            raise RuntimeError(
                f"only an unvalidated transaction can be marked {requested_state}"
            )

    @staticmethod
    def _require_degree_minutes(value: int) -> None:
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError("degree minutes must be an integer")

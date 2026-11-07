"""Plans state-change and maintenance degree-minute transactions."""

from ..account import Account
from ..timing import TimingPolicy
from ..transaction import Transaction, TransferDirection
from .fixed_reserves import FixedReserves
from .pump_limits import PumpLimits
from .heating_mode import HeatingMode


class TransactionPlanner:
    """Bundles transferable degree minutes into one safe transaction."""

    def __init__(
        self,
        limits: PumpLimits,
        reserves: FixedReserves,
        *,
        timing: TimingPolicy = TimingPolicy(),
    ) -> None:
        """Create a planner with physical limits and fixed operating reserves."""
        if not isinstance(limits, PumpLimits):
            raise TypeError("limits must be PumpLimits")
        if not isinstance(reserves, FixedReserves):
            raise TypeError("reserves must be FixedReserves")
        if not isinstance(timing, TimingPolicy):
            raise TypeError("timing must be a TimingPolicy")
        if (
            reserves.running_stop_reserve + reserves.idling_floor_reserve
            >= limits.range_degree_minutes
        ):
            raise ValueError("combined reserves must fit inside the pump range")

        self._limits = limits
        self._reserves = reserves
        self._timing = timing

    def plan_state_change(
        self,
        account: Account,
        desired_mode: HeatingMode,
        observed_pump_degree_minutes: int,
    ) -> Transaction | None:
        """Plan the largest safe transaction to enter the requested mode."""
        self._validate_inputs(account, desired_mode, observed_pump_degree_minutes)
        if desired_mode is HeatingMode.HEATING:
            return self._plan_account_to_pump(account, observed_pump_degree_minutes)
        return self._plan_pump_to_account(observed_pump_degree_minutes)

    def plan_maintenance(
        self,
        account: Account,
        desired_mode: HeatingMode,
        observed_pump_degree_minutes: int,
    ) -> Transaction | None:
        """Plan the largest safe transaction that maintains the requested mode."""
        self._validate_inputs(account, desired_mode, observed_pump_degree_minutes)
        if desired_mode is HeatingMode.HEATING:
            if (
                observed_pump_degree_minutes
                < self._limits.stop_degree_minutes
                - self._reserves.running_stop_reserve
            ):
                return None
            return self._plan_account_to_pump(account, observed_pump_degree_minutes)

        if (
            observed_pump_degree_minutes
            > self._limits.minimum_degree_minutes
            + self._reserves.idling_floor_reserve
        ):
            return None
        return self._plan_pump_to_account(observed_pump_degree_minutes)

    def _plan_account_to_pump(
        self,
        account: Account,
        observed_pump_degree_minutes: int,
    ) -> Transaction | None:
        available_account_debt = max(0, -account.degree_minutes)
        lowest_planned_pump_degree_minutes = (
            self._limits.minimum_degree_minutes
            + self._reserves.idling_floor_reserve
        )
        available_pump_capacity = max(
            0,
            observed_pump_degree_minutes - lowest_planned_pump_degree_minutes,
        )
        transfer_degree_minutes = min(
            available_account_debt,
            available_pump_capacity,
        )
        return self._transaction_or_none(
            transfer_degree_minutes,
            TransferDirection.ACCOUNT_TO_PUMP,
            observed_pump_degree_minutes,
        )

    def _plan_pump_to_account(
        self,
        observed_pump_degree_minutes: int,
    ) -> Transaction | None:
        transfer_degree_minutes = max(
            0,
            self._limits.stop_degree_minutes - observed_pump_degree_minutes,
        )
        return self._transaction_or_none(
            transfer_degree_minutes,
            TransferDirection.PUMP_TO_ACCOUNT,
            observed_pump_degree_minutes,
        )

    def _transaction_or_none(
        self,
        transfer_degree_minutes: int,
        direction: TransferDirection,
        observed_pump_degree_minutes: int,
    ) -> Transaction | None:
        if transfer_degree_minutes == 0:
            return None

        signed_degree_minutes = -transfer_degree_minutes
        if direction is TransferDirection.ACCOUNT_TO_PUMP:
            target_pump_degree_minutes = (
                observed_pump_degree_minutes + signed_degree_minutes
            )
        else:
            target_pump_degree_minutes = (
                observed_pump_degree_minutes - signed_degree_minutes
            )
        is_small_stop_transaction = (
            direction is TransferDirection.PUMP_TO_ACCOUNT
            and self._limits.stop_degree_minutes == 0
            and target_pump_degree_minutes == 0
        )
        if (
            transfer_degree_minutes
            < Transaction.MINIMUM_RELIABLY_VERIFIABLE_DEGREE_MINUTES
            and not is_small_stop_transaction
        ):
            return None
        return Transaction(signed_degree_minutes, direction, timing=self._timing)

    @staticmethod
    def _validate_inputs(
        account: Account,
        desired_mode: HeatingMode,
        observed_pump_degree_minutes: int,
    ) -> None:
        if not isinstance(account, Account):
            raise TypeError("account must be an Account")
        if not isinstance(desired_mode, HeatingMode):
            raise TypeError("desired mode must be HeatingMode")
        if (
            not isinstance(observed_pump_degree_minutes, int)
            or isinstance(observed_pump_degree_minutes, bool)
        ):
            raise TypeError("observed pump degree minutes must be an integer")

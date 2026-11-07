import pytest

from dm_accounting import (
    Account,
    FixedReserves,
    HeatingMode,
    PumpLimits,
    TimingPolicy,
    TransactionPlanner,
    TransferDirection,
)


@pytest.fixture
def planner() -> TransactionPlanner:
    return TransactionPlanner(PumpLimits(), FixedReserves())


def test_default_limits_and_reserves() -> None:
    limits = PumpLimits()
    reserves = FixedReserves()

    assert limits.minimum_degree_minutes == -3000
    assert limits.stop_degree_minutes == 0
    assert limits.range_degree_minutes == 3000
    assert reserves.running_stop_reserve == 100
    assert reserves.idling_floor_reserve == 100


@pytest.mark.parametrize(
    ("minimum", "stop"),
    [(0, 0), (1, 0), ("-3000", 0)],
)
def test_limits_reject_invalid_bounds(minimum: object, stop: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        PumpLimits(minimum, stop)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [0, -1, "100"])
def test_reserves_reject_invalid_values(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        FixedReserves(value, 100)  # type: ignore[arg-type]


def test_planner_rejects_reserves_that_fill_the_pump_range() -> None:
    with pytest.raises(ValueError):
        TransactionPlanner(PumpLimits(), FixedReserves(1500, 1500))


def test_planner_passes_its_timing_to_planned_transactions() -> None:
    timing = TimingPolicy(1, 2, 3)
    planner = TransactionPlanner(PumpLimits(), FixedReserves(), timing=timing)

    transaction = planner.plan_state_change(Account(-500), HeatingMode.HEATING, -1000)

    assert transaction is not None
    assert transaction.timing is timing


@pytest.mark.parametrize(
    ("account_balance", "observed_pump_dm", "expected_amount", "expected_target"),
    [
        (-4000, -1000, -1900, -2900),
        (-500, -1000, -500, -1500),
        (-4000, 5, -2905, -2900),
    ],
)
def test_start_plans_the_largest_safe_account_to_pump_transfer(
    planner: TransactionPlanner,
    account_balance: int,
    observed_pump_dm: int,
    expected_amount: int,
    expected_target: int,
) -> None:
    account = Account(account_balance)

    transaction = planner.plan_state_change(
        account,
        HeatingMode.HEATING,
        observed_pump_dm,
    )

    assert transaction is not None
    assert transaction.degree_minutes == expected_amount
    assert transaction.direction is TransferDirection.ACCOUNT_TO_PUMP
    assert transaction.pump_target_for(observed_pump_dm) == expected_target
    assert account.degree_minutes == account_balance


@pytest.mark.parametrize("account_balance", [0, 300, -20])
def test_start_returns_none_without_reliably_transferable_account_debt(
    planner: TransactionPlanner,
    account_balance: int,
) -> None:
    transaction = planner.plan_state_change(
        Account(account_balance),
        HeatingMode.HEATING,
        -1000,
    )

    assert transaction is None


@pytest.mark.parametrize(
    ("observed_pump_dm", "expected_amount"),
    [(-2000, -2000), (-10, -10)],
)
def test_stop_transfers_all_pump_debt_including_a_small_final_debt(
    planner: TransactionPlanner,
    observed_pump_dm: int,
    expected_amount: int,
) -> None:
    transaction = planner.plan_state_change(
        Account(-500),
        HeatingMode.IDLING,
        observed_pump_dm,
    )

    assert transaction is not None
    assert transaction.degree_minutes == expected_amount
    assert transaction.direction is TransferDirection.PUMP_TO_ACCOUNT
    assert transaction.pump_target_for(observed_pump_dm) == 0


@pytest.mark.parametrize("observed_pump_dm", [0, 1])
def test_stop_returns_none_when_pump_has_no_debt(
    planner: TransactionPlanner,
    observed_pump_dm: int,
) -> None:
    assert (
        planner.plan_state_change(
            Account(-500),
            HeatingMode.IDLING,
            observed_pump_dm,
        )
        is None
    )


@pytest.mark.parametrize(
    ("observed_pump_dm", "expects_transaction"),
    [(-101, False), (-100, True), (-99, True)],
)
def test_heating_maintenance_acts_at_the_stop_reserve(
    planner: TransactionPlanner,
    observed_pump_dm: int,
    expects_transaction: bool,
) -> None:
    transaction = planner.plan_maintenance(
        Account(-5000),
        HeatingMode.HEATING,
        observed_pump_dm,
    )

    assert (transaction is not None) is expects_transaction
    if transaction is not None:
        assert transaction.direction is TransferDirection.ACCOUNT_TO_PUMP
        assert transaction.pump_target_for(observed_pump_dm) == -2900


@pytest.mark.parametrize(
    ("observed_pump_dm", "expects_transaction"),
    [(-2899, False), (-2900, True), (-3001, True)],
)
def test_idling_maintenance_acts_at_the_floor_reserve(
    planner: TransactionPlanner,
    observed_pump_dm: int,
    expects_transaction: bool,
) -> None:
    transaction = planner.plan_maintenance(
        Account(-500),
        HeatingMode.IDLING,
        observed_pump_dm,
    )

    assert (transaction is not None) is expects_transaction
    if transaction is not None:
        assert transaction.direction is TransferDirection.PUMP_TO_ACCOUNT
        assert transaction.pump_target_for(observed_pump_dm) == 0


def test_heating_maintenance_does_not_worsen_an_already_below_floor_pump(
    planner: TransactionPlanner,
) -> None:
    assert (
        planner.plan_maintenance(Account(-5000), HeatingMode.HEATING, -3001)
        is None
    )

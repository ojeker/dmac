import pytest

from dm_accounting import Account


def test_account_applies_signed_degree_minute_deltas() -> None:
    account = Account(-1000)

    account.apply(250)
    account.apply(-75)

    assert account.degree_minutes == -825


@pytest.mark.parametrize("value", [1.5, "-100", True])
def test_account_rejects_non_integer_degree_minutes(value: object) -> None:
    with pytest.raises(TypeError):
        Account(value)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [1.5, "-100", True])
def test_account_rejects_invalid_delta_without_changing_balance(value: object) -> None:
    account = Account(-100)

    with pytest.raises(TypeError):
        account.apply(value)  # type: ignore[arg-type]

    assert account.degree_minutes == -100

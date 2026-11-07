"""Tests for shared verification and maintenance timing."""

import pytest

from dm_accounting import TimingPolicy


def test_production_timing_defaults() -> None:
    assert TimingPolicy() == TimingPolicy(90, 180, 600)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"first_verification_delay_seconds": True},
        {"final_verification_delay_seconds": 0},
        {"maintenance_interval_seconds": -1},
        {
            "first_verification_delay_seconds": 10,
            "final_verification_delay_seconds": 10,
        },
    ],
)
def test_rejects_invalid_timing(kwargs: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        TimingPolicy(**kwargs)  # type: ignore[arg-type]

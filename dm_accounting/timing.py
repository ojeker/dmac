"""Timing policy shared by transaction verification and maintenance scheduling."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TimingPolicy:
    """Defines production or test timing without Home Assistant dependencies."""

    first_verification_delay_seconds: int = 90
    final_verification_delay_seconds: int = 180
    maintenance_interval_seconds: int = 600

    def __post_init__(self) -> None:
        """Validate a safe sequence of positive whole-second intervals."""
        for name, value in (
            ("first_verification_delay_seconds", self.first_verification_delay_seconds),
            ("final_verification_delay_seconds", self.final_verification_delay_seconds),
            ("maintenance_interval_seconds", self.maintenance_interval_seconds),
        ):
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{name} must be an integer")
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.final_verification_delay_seconds <= self.first_verification_delay_seconds:
            raise ValueError(
                "final_verification_delay_seconds must be later than "
                "first_verification_delay_seconds"
            )

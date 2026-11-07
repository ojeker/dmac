"""Domain model for the degree-minute account."""

import logging


_LOGGER = logging.getLogger(__name__)


class Account:
    """Stores the degree-minute balance used for soft steering."""

    def __init__(self, degree_minutes: int) -> None:
        """Create an account with its current signed degree-minute balance."""
        self._require_degree_minutes(degree_minutes)
        self._degree_minutes = degree_minutes

    @property
    def degree_minutes(self) -> int:
        """Return the current signed degree-minute balance."""
        return self._degree_minutes

    def apply(self, delta_degree_minutes: int) -> None:
        """Adjust the balance by a signed degree-minute delta."""
        self._require_degree_minutes(delta_degree_minutes)
        previous_degree_minutes = self._degree_minutes
        self._degree_minutes += delta_degree_minutes
        _LOGGER.debug(
            "Account balance written: previous_dm=%s delta_dm=%s current_dm=%s",
            previous_degree_minutes,
            delta_degree_minutes,
            self._degree_minutes,
        )

    @staticmethod
    def _require_degree_minutes(value: int) -> None:
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError("degree minutes must be an integer")

"""Fixed operating margins inside the pump's physical limits."""


class FixedReserves:
    """Defines the fixed margins used to protect the pump boundaries."""

    def __init__(
        self,
        running_stop_reserve: int = 100,
        idling_floor_reserve: int = 100,
    ) -> None:
        """Create reserves below the stop boundary and above the lower floor."""
        self._require_positive_integer(running_stop_reserve, "running stop reserve")
        self._require_positive_integer(idling_floor_reserve, "idling floor reserve")

        self._running_stop_reserve = running_stop_reserve
        self._idling_floor_reserve = idling_floor_reserve

    @property
    def running_stop_reserve(self) -> int:
        """Return the reserve held below the pump stop boundary while heating."""
        return self._running_stop_reserve

    @property
    def idling_floor_reserve(self) -> int:
        """Return the reserve held above the pump's lower DM limit while idling."""
        return self._idling_floor_reserve

    @staticmethod
    def _require_positive_integer(value: int, description: str) -> None:
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"{description} must be an integer")
        if value <= 0:
            raise ValueError(f"{description} must be positive")

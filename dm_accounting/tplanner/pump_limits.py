"""Physical degree-minute limits of the heat pump."""


class PumpLimits:
    """Defines the pump's hard lower limit and running stop boundary."""

    def __init__(
        self,
        minimum_degree_minutes: int = -3000,
        stop_degree_minutes: int = 0,
    ) -> None:
        """Create the physical bounds observed by every transaction plan."""
        self._require_integer(minimum_degree_minutes, "minimum degree minutes")
        self._require_integer(stop_degree_minutes, "stop degree minutes")
        if minimum_degree_minutes >= stop_degree_minutes:
            raise ValueError("minimum degree minutes must be below stop degree minutes")

        self._minimum_degree_minutes = minimum_degree_minutes
        self._stop_degree_minutes = stop_degree_minutes

    @property
    def minimum_degree_minutes(self) -> int:
        """Return the hard lower pump DM limit."""
        return self._minimum_degree_minutes

    @property
    def stop_degree_minutes(self) -> int:
        """Return the pump DM boundary at which heating stops."""
        return self._stop_degree_minutes

    @property
    def range_degree_minutes(self) -> int:
        """Return the usable range between the physical pump boundaries."""
        return self._stop_degree_minutes - self._minimum_degree_minutes

    @staticmethod
    def _require_integer(value: int, description: str) -> None:
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"{description} must be an integer")

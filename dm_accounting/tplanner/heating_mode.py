"""The operating mode the controller is asked to maintain."""

from enum import Enum, auto


class HeatingMode(Enum):
    """Whether the pump should be kept heating or idling."""

    HEATING = auto()
    IDLING = auto()

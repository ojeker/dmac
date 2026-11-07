"""The externally observable operating status of the heating controller."""

from enum import Enum, auto


class ControllerStatus(Enum):
    """Indicates whether automatic heating control may continue."""

    OPERATING = auto()
    ERROR = auto()

"""The result of attempting an absolute degree-minute pump write."""

from enum import Enum, auto


class PumpWriteOutcome(Enum):
    """Describes whether a pump-write request might have reached the pump."""

    NOT_ATTEMPTED = auto()
    ACCEPTED = auto()
    UNKNOWN = auto()

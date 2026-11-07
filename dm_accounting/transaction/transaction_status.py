"""Lifecycle states of a degree-minute transaction."""

from enum import Enum, auto


class TransactionStatus(Enum):
    """Records whether a transaction's pump write has been verified."""

    PLANNED = auto()
    UNVALIDATED = auto()
    VERIFIED = auto()
    FAILED = auto()

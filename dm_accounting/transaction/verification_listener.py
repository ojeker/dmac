"""Notification boundary for a transaction that verified successfully."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .transaction import Transaction


class VerificationListener(Protocol):
    """Receives terminal verification notifications from open transactions."""

    async def transaction_verified(self, transaction: Transaction) -> None:
        """Record that an open transaction has reached its expected pump state."""
        ...

    async def transaction_failed(self, transaction: Transaction) -> None:
        """Record that an open transaction could not be verified."""
        ...

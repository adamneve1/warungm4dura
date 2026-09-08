"""Ephemeral per-chat transaction state for Telegram application flow."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


@dataclass
class UnresolvedItem:
    """An item whose product could not be uniquely resolved due to multiple candidates."""

    original_query: str               # e.g. "sarimie" — used in disambiguation prompts
    qty: int
    candidates: list[dict[str, Any]]  # [{product_id, nama, satuan}] — subset to match against
    unit: str | None = None           # satuan from user message, e.g. "butir", "kg", "bungkus"


@dataclass
class PendingTransaction:
    items: list[dict[str, Any]]      # Fully resolved items: [{product_id, qty}]
    payment_method: str | None
    status: str                       # "WAITING_PAYMENT" | "WAITING_PRODUCT"
    created_at: datetime
    unresolved: list[UnresolvedItem] = field(default_factory=list)
    # Invariant: status == "WAITING_PRODUCT"  ↔  len(unresolved) >= 1
    # Invariant: status == "WAITING_PAYMENT"  →  len(unresolved) == 0


class PendingTransactionStore:
    def __init__(self, ttl: timedelta = timedelta(minutes=10)) -> None:
        self._states: dict[int, PendingTransaction] = {}
        self._ttl = ttl

    def get(self, chat_id: int, now: datetime) -> PendingTransaction | None:
        state = self._states.get(chat_id)
        if state is None:
            return None
        if now - state.created_at >= self._ttl:
            self._states.pop(chat_id, None)
            return None
        return state

    def put(self, chat_id: int, state: PendingTransaction) -> None:
        self._states[chat_id] = state

    def clear(self, chat_id: int) -> None:
        self._states.pop(chat_id, None)

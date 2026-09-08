"""Telegram text adapter; no business logic belongs here."""

import logging
from datetime import datetime, timezone
from typing import Any

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from .gemini import TextModel
from .telegram_state import PendingTransaction, PendingTransactionStore, UnresolvedItem


logger = logging.getLogger(__name__)

# Explicit map: casefold → canonical payment method as expected by TransactionService
_PAYMENT_MAP: dict[str, str] = {"tunai": "Tunai", "transfer": "Transfer", "qris": "QRIS"}


def _match_candidates(selection: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Priority-based matching of user selection against a product candidate list.

    Priority:
    1. Exact full-name match (case-insensitive)
    2. All meaningful selection tokens (≥2 chars) appear as whole word-tokens in candidate name

    Returns the subset of candidates that match:
    - [] → no match (message is not a product selection)
    - [one] → unique resolve
    - [many] → still ambiguous

    Never performs a global product search — only matches against the provided candidates.
    """
    sel = selection.strip().casefold()
    if not sel:
        return []

    # P1: exact full-name match
    exact = [c for c in candidates if c["nama"].casefold() == sel]
    if exact:
        return exact

    # P2: word-token match — all meaningful tokens in selection ⊆ word-tokens in candidate name.
    # Meaningful = length ≥ 2. This prevents single-letter noise and avoids partial-word matches
    # (e.g. "mi" does NOT match "indomie" because "mi" is not a word-token of "indomie goreng spesial").
    tokens = {t for t in sel.split() if len(t) >= 2}
    if not tokens:
        return []

    return [
        c for c in candidates
        if tokens.issubset(set(c["nama"].casefold().split()))
    ]


def _format_candidate_names(candidates: list[dict[str, Any]], max_shown: int = 5) -> str:
    """Return a human-readable comma-separated list of candidate names, capped at max_shown."""
    names = [c["nama"] for c in candidates[:max_shown]]
    if len(candidates) > max_shown:
        names.append("dll.")
    return ", ".join(names)


class TelegramBot:
    def __init__(
        self,
        token: str,
        model: TextModel,
        transaction_adapter: Any | None = None,
        state_store: PendingTransactionStore | None = None,
    ) -> None:
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN wajib dikonfigurasi.")
        self._token = token
        self._model = model
        self._transaction_adapter = transaction_adapter
        self._states = state_store or PendingTransactionStore()

    def build_application(self) -> Application:
        application = Application.builder().token(self._token).build()
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))
        return application

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or not update.message.text:
            return
        update_id = update.update_id
        effective_chat = getattr(update, "effective_chat", None)
        chat_id = effective_chat.id if effective_chat else update.message.chat_id
        now = datetime.now(timezone.utc)
        pending = self._states.get(chat_id, now)
        normalized = update.message.text.strip().casefold()

        # Guard 1: cancel — clears any pending state regardless of status
        if pending and normalized in {"batal", "cancel"}:
            self._states.clear(chat_id)
            await update.message.reply_text("Siap Bos, transaksi dibatalkan.")
            return

        # Guard 2: product disambiguation — only when WAITING_PRODUCT.
        # Candidate matching is attempted first. If no candidate matches, the message is
        # treated as a separate intent and handled by respond(); pending state is preserved.
        if pending and pending.status == "WAITING_PRODUCT":
            handled = await self._handle_product_disambiguation(
                update, chat_id, pending, normalized, update_id, now
            )
            if handled:
                return
            # Not a product selection → process as other intent, keep pending intact
            try:
                response = self._model.respond(update.message.text, f"telegram:{update_id}")
            except Exception:
                logger.exception("Telegram request failed for update %s", update_id)
                response = "Maaf, terjadi gangguan saat memproses pesan."
            await update.message.reply_text(response)
            return  # pending state NOT cleared

        # Guard 3: payment token detection — runs when WAITING_PAYMENT (or any non-product pending).
        # Word-token matching prevents "tunaikasir" from triggering "Tunai".
        if pending:
            _tokens = set(normalized.split())
            _matched_pms = {canonical for kw, canonical in _PAYMENT_MAP.items() if kw in _tokens}
            if len(_matched_pms) > 1:
                # Ambiguous: user said e.g. "tunai atau qris" — ask them to pick one
                await update.message.reply_text(
                    "Bayarnya pakai metode yang mana, Bos? Pilih satu: Tunai, Transfer, atau QRIS."
                )
                return
            if len(_matched_pms) == 1:
                await self._complete_pending(update, chat_id, pending, _matched_pms.pop(), update_id)
                return
            # No payment keyword — fall through to Gemini intent resolver

        # Normal intent resolution
        try:
            intent = None
            resolver = getattr(self._model, "resolve_transaction_intent", None)
            if self._transaction_adapter is not None and resolver is not None:
                intent = resolver(update.message.text)
            if intent and intent.get("intent") == "sale":
                response = await self._handle_sale_intent(update, chat_id, intent, update_id, now)
            else:
                response = self._model.respond(update.message.text, f"telegram:{update_id}")
        except Exception:
            logger.exception("Telegram request failed for update %s", update_id)
            response = "Maaf, terjadi gangguan saat memproses pesan."
        await update.message.reply_text(response)

    async def _handle_product_disambiguation(
        self,
        update: Update,
        chat_id: int,
        pending: PendingTransaction,
        normalized: str,
        update_id: int,
        now: datetime,
    ) -> bool:
        """Attempt to match user input against the current unresolved item's candidate list.

        Returns True  → message handled as a product selection (resolved, narrowed, or retry).
        Returns False → message is not a product selection; caller handles as other intent.

        Never performs a new global product search. Matching is always restricted to the
        candidate list stored in the pending state.
        """
        current = pending.unresolved[0]
        matched = _match_candidates(normalized, current.candidates)

        if len(matched) == 0:
            # No candidate match — signal caller to treat as a different intent
            return False

        if len(matched) > 1:
            # Still ambiguous — narrow candidates and ask again
            narrowed_unresolved = [
                UnresolvedItem(current.original_query, current.qty, matched),
                *pending.unresolved[1:],
            ]
            self._states.put(chat_id, PendingTransaction(
                items=pending.items,
                payment_method=pending.payment_method,
                status="WAITING_PRODUCT",
                created_at=pending.created_at,  # preserve original timestamp for TTL
                unresolved=narrowed_unresolved,
            ))
            await update.message.reply_text(
                f"Masih ada beberapa, Bos. Maksudnya yang mana? "
                f"{_format_candidate_names(matched)}"
            )
            return True

        # Exactly 1 match — item resolved
        resolved_item = {"product_id": matched[0]["product_id"], "qty": current.qty}
        new_items = [*pending.items, resolved_item]
        new_unresolved = pending.unresolved[1:]

        if new_unresolved:
            # More items still need disambiguation — keep WAITING_PRODUCT
            self._states.put(chat_id, PendingTransaction(
                items=new_items,
                payment_method=pending.payment_method,
                status="WAITING_PRODUCT",
                created_at=pending.created_at,
                unresolved=new_unresolved,
            ))
            nxt = new_unresolved[0]
            await update.message.reply_text(
                f"{nxt.original_query.title()} yang mana, Bos? "
                f"{_format_candidate_names(nxt.candidates)}"
            )
            return True

        # All items resolved — proceed to payment or create transaction
        if pending.payment_method:
            # Payment already known from original message → create transaction immediately
            self._states.clear(chat_id)
            result = self._transaction_adapter.create_transaction(
                new_items, pending.payment_method, idempotency_key=f"telegram:{update_id}"
            )
            if result.get("success") and "payment_method" not in result:
                result = {**result, "payment_method": pending.payment_method}
            await update.message.reply_text(_format_result(result))
        else:
            # Payment unknown → switch state to WAITING_PAYMENT
            self._states.put(chat_id, PendingTransaction(
                items=new_items,
                payment_method=None,
                status="WAITING_PAYMENT",
                created_at=pending.created_at,
                unresolved=[],
            ))
            await update.message.reply_text(
                "Siap Bos, penjualan sudah dicatat sementara. Bayarnya Tunai, Transfer, atau QRIS?"
            )
        return True

    async def _handle_sale_intent(
        self,
        update: Update,
        chat_id: int,
        intent: dict[str, Any],
        update_id: int,
        now: datetime,
    ) -> str:
        if not intent.get("success"):
            if intent.get("error_code") == "AMBIGUOUS_PRODUCT":
                unresolved_raw = intent.get("unresolved_items", [])
                if unresolved_raw:
                    # Build state for product disambiguation
                    unresolved = [
                        UnresolvedItem(
                            original_query=u["original_query"],
                            qty=u["qty"],
                            candidates=u["candidates"],
                        )
                        for u in unresolved_raw
                    ]
                    self._states.put(chat_id, PendingTransaction(
                        items=intent.get("resolved_items", []),
                        payment_method=intent.get("payment_method"),
                        status="WAITING_PRODUCT",
                        created_at=now,
                        unresolved=unresolved,
                    ))
                    first = unresolved[0]
                    return (
                        f"{first.original_query.title()} yang mana, Bos? "
                        f"{_format_candidate_names(first.candidates)}"
                    )
            return _format_result(intent)
        items = intent["items"]
        payment_method = intent.get("payment_method")
        if not payment_method:
            self._states.put(chat_id, PendingTransaction(items, None, "WAITING_PAYMENT", now))
            return "Siap Bos, penjualan sudah dicatat sementara. Bayarnya Tunai, Transfer, atau QRIS?"
        result = self._transaction_adapter.create_transaction(
            items, payment_method, idempotency_key=f"telegram:{update_id}"
        )
        return _format_result(result)

    async def _complete_pending(
        self,
        update: Update,
        chat_id: int,
        pending: PendingTransaction,
        payment_method: str,
        update_id: int,
    ) -> None:
        result = self._transaction_adapter.create_transaction(
            pending.items, payment_method, idempotency_key=f"telegram:{update_id}"
        )
        self._states.clear(chat_id)
        # Inject payment_method so formatter can include it even if service omits it
        if result.get("success") and "payment_method" not in result:
            result = {**result, "payment_method": payment_method}
        await update.message.reply_text(_format_result(result))

    def run(self) -> None:
        self.build_application().run_polling()


def _format_result(result: dict[str, Any]) -> str:
    if result.get("success"):
        total = result.get("total", 0)
        payment_method = str(result.get("payment_method", "")).lower()
        items = result.get("items", [])
        item_summary = ""
        if items:
            item_summary = ", ".join(
                f"{item.get('nama', item.get('product_id', 'barang'))} x{item.get('qty', 0)}"
                for item in items
            )
        payment_text = f" {payment_method}" if payment_method else ""
        if item_summary:
            return f"Siap Bos. Penjualan {item_summary} sudah dicatat{payment_text}.\nTotal Rp{total:,}.".replace(",", ".")
        return f"Siap Bos. Transaksi sudah dicatat{payment_text}.\nTotal Rp{total:,}.".replace(",", ".")
    if result.get("error_code") == "INSUFFICIENT_STOCK":
        return f"Maaf Bos, stok tidak cukup. Stok tersedia: {result.get('available_stock')}, diminta: {result.get('requested_qty')}."
    if result.get("error_code") == "PRODUCT_NOT_FOUND":
        return "Maaf Bos, barangnya belum ketemu. Coba sebutkan nama barangnya seperti yang ada di daftar stok."
    if result.get("error_code") == "PRODUCT_INACTIVE":
        return "Maaf Bos, barang itu sedang tidak aktif di daftar stok."
    if result.get("error_code") == "TRANSACTION_RECONCILIATION_REQUIRED":
        return "Maaf Bos, transaksi belum berhasil dicatat. Tidak saya ulang otomatis supaya tidak terjadi transaksi dobel."
    return "Maaf Bos, transaksi belum berhasil dicatat."

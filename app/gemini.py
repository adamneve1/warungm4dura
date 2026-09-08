"""Gemini orchestration boundary with MCP tool calling."""

import logging
import json
from datetime import datetime
from typing import Any, Callable, Protocol
from zoneinfo import ZoneInfo

from .mcp_adapter import MCPToolAdapter
from .prompts import SYSTEM_PROMPT


logger = logging.getLogger(__name__)

_JAKARTA = ZoneInfo("Asia/Jakarta")

# Canonical payment method names as expected by TransactionService.
# Keys are casefold variants that Gemini may return.
_CANONICAL_PM: dict[str, str] = {
    "tunai": "Tunai",
    "cash": "Tunai",
    "transfer": "Transfer",
    "bank transfer": "Transfer",
    "qris": "QRIS",
}


def _build_system_instruction(clock: Callable[[], datetime]) -> str:
    """Append current date context so Gemini can supply valid YYYY-MM-DD arguments."""
    now = clock()
    date_str = now.strftime("%Y-%m-%d")
    day_str = now.strftime("%A")  # e.g. Monday
    return (
        SYSTEM_PROMPT
        + f"\n\nContext: today is {date_str} ({day_str}). Use this exact date when tools require a date parameter."
    )


class TextModel(Protocol):
    def respond(self, text: str, idempotency_key: str | None = None) -> str: ...


class GeminiService:
    def __init__(self, api_key: str, model: str, tools: MCPToolAdapter, client: Any | None = None, clock: Callable[[], datetime] | None = None) -> None:
        if not api_key or not model:
            raise RuntimeError("GEMINI_API_KEY dan GEMINI_MODEL wajib dikonfigurasi.")
        if client is None:
            from google import genai
            client = genai.Client(api_key=api_key)
        self._client = client
        self._model = model
        self._tools = tools
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(_JAKARTA))

    def resolve_transaction_intent(self, text: str) -> dict[str, Any]:
        """Extract a seller sale report and resolve names through the product tool."""
        from google.genai import types

        response = self._client.models.generate_content(
            model=self._model,
            contents=[text],
            config=types.GenerateContentConfig(
                system_instruction=(
                    _build_system_instruction(self._clock)
                    + "\nReturn JSON only with intent (sale or other), items[{product_query,qty}], and payment_method."
                ),
                response_mime_type="application/json",
                response_schema={
                    "type": "OBJECT",
                    "properties": {
                        "intent": {"type": "STRING", "enum": ["sale", "other"]},
                        "items": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {"product_query": {"type": "STRING"}, "qty": {"type": "INTEGER"}, "unit": {"type": "STRING"}}}},
                        "payment_method": {"type": "STRING"},
                    },
                    "required": ["intent", "items"],
                },
            ),
        )
        try:
            parsed = json.loads(response.text or "{}")
        except (TypeError, json.JSONDecodeError):
            return {"intent": "other"}
        if parsed.get("intent") != "sale":
            return {"intent": "other"}
        pm = _CANONICAL_PM.get(str(parsed.get("payment_method") or "").strip().casefold())
        resolved_items: list[dict] = []
        unresolved_items: list[dict] = []
        for item in parsed.get("items", []):
            query = str(item.get("product_query", ""))
            qty = int(item.get("qty") or 1)
            unit = str(item.get("unit") or "").strip().casefold() or None
            raw_matches = self._tools.search_product(query)
            # Deduplicate by product_id — Sheets may return same row twice
            seen_ids: set[str] = set()
            matches = []
            for m in raw_matches:
                pid = m.get("product_id", "")
                if pid not in seen_ids:
                    seen_ids.add(pid)
                    matches.append(m)
            if len(matches) == 0:
                return {
                    "intent": "sale",
                    "success": False,
                    "error_code": "PRODUCT_NOT_FOUND",
                    "query": query,
                }
            if len(matches) == 1:
                resolved_items.append({"product_id": matches[0]["product_id"], "qty": qty})
            else:
                # Multiple candidates — attempt unit-aware auto-resolution first
                candidates = [
                    {"product_id": m["product_id"], "nama": m["nama"], "satuan": m.get("satuan", "")}
                    for m in matches
                ]
                if unit:
                    unit_matched = [
                        c for c in candidates
                        if c["satuan"].casefold() == unit
                    ]
                    if len(unit_matched) == 1:
                        # Unit uniquely identifies the product — resolve automatically
                        resolved_items.append({"product_id": unit_matched[0]["product_id"], "qty": qty})
                        continue  # do not add to unresolved_items
                # Still ambiguous — defer to user disambiguation
                unresolved_items.append({
                    "original_query": query,
                    "qty": qty,
                    "unit": unit,
                    "candidates": candidates,
                })
        if unresolved_items:
            return {
                "intent": "sale",
                "success": False,
                "error_code": "AMBIGUOUS_PRODUCT",
                "resolved_items": resolved_items,
                "unresolved_items": unresolved_items,
                "payment_method": pm,
            }
        return {
            "intent": "sale",
            "success": True,
            "items": resolved_items,
            "payment_method": pm,
        }

    def respond(self, text: str, idempotency_key: str | None = None) -> str:
        from google.genai import types

        declarations = [_function_declaration(name) for name in self._tools.tool_functions()]
        contents: list[Any] = [text]
        for _ in range(4):
            response = self._client.models.generate_content(
                model=self._model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=_build_system_instruction(self._clock),
                    tools=[types.Tool(function_declarations=declarations)],
                ),
            )
            calls = []
            text_parts = []
            for candidate in response.candidates or []:
                for part in candidate.content.parts or []:
                    if part.text:
                        text_parts.append(part.text)
                    if part.function_call:
                        calls.append(part.function_call)
            if not calls:
                return "\n".join(text_parts).strip()
            contents.append(response.candidates[0].content)
            for call in calls:
                result = self._call_tool(call.name, dict(call.args or {}), idempotency_key)
                contents.append(types.Content(role="user", parts=[types.Part.from_function_response(name=call.name, response={"result": result})]))
        return "Maaf, permintaan terlalu kompleks untuk diproses sekarang."

    def _call_tool(self, name: str, args: dict[str, Any], idempotency_key: str | None) -> dict[str, Any] | list[dict[str, Any]]:
        if name == "create_transaction":
            args.setdefault("idempotency_key", idempotency_key)
        function = self._tools.tool_functions().get(name)
        if function is None:
            return {"success": False, "error_code": "UNKNOWN_TOOL", "message": "Tool tidak tersedia."}
        try:
            return function(**args)
        except Exception:
            logger.exception("Gemini tool call failed: %s", name)
            return {"success": False, "error_code": "INTERNAL_ERROR", "message": "Operasi tidak dapat diproses."}


def _function_declaration(name: str) -> Any:
    from google.genai import types

    schemas: dict[str, dict[str, Any]] = {
        "search_product": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        "get_product": {"type": "object", "properties": {"product_id": {"type": "string"}}, "required": ["product_id"]},
        "get_stock": {"type": "object", "properties": {"product_id": {"type": "string"}}, "required": ["product_id"]},
        "create_transaction": {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {"product_id": {"type": "string"}, "qty": {"type": "integer"}}, "required": ["product_id", "qty"]}}, "payment_method": {"type": "string", "enum": ["Tunai", "Transfer", "QRIS"]}, "note": {"type": "string"}}, "required": ["items", "payment_method"]},
        "add_stock": {"type": "object", "properties": {"product_id": {"type": "string"}, "qty": {"type": "integer"}, "reference": {"type": "string"}, "note": {"type": "string"}}, "required": ["product_id", "qty"]},
        "get_daily_sales": {"type": "object", "properties": {"date": {"type": "string"}}, "required": ["date"]},
        "get_sales_summary": {"type": "object", "properties": {"date": {"type": "string"}}, "required": ["date"]},
        "get_product_sales": {"type": "object", "properties": {"date": {"type": "string"}}, "required": ["date"]},
        "get_category_sales": {"type": "object", "properties": {"date": {"type": "string"}}, "required": ["date"]},
        "get_payment_summary": {"type": "object", "properties": {"date": {"type": "string"}}, "required": ["date"]},
        "get_low_stock": {"type": "object", "properties": {}},
        "get_out_of_stock": {"type": "object", "properties": {}},
        "get_stock_status": {"type": "object", "properties": {"include_inactive": {"type": "boolean"}}},
        "get_stock_movements": {"type": "object", "properties": {"product_id": {"type": "string"}, "start_date": {"type": "string"}, "end_date": {"type": "string"}}},
    }
    schema = schemas.get(name, {"type": "object"})
    return types.FunctionDeclaration(name=name, description=f"Warung business operation: {name}", parameters_json_schema=schema)

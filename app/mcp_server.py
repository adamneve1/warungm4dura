"""MCP transport will be added in PHASE 4.

The PHASE 1 product service is intentionally independent from MCP transport.
"""
"""MCP stdio server exposing only business-level Warung tools."""

import logging
from typing import Any

from mcp.server import MCPServer

from .mcp_adapter import MCPToolAdapter


logger = logging.getLogger(__name__)


def create_mcp_server(adapter: MCPToolAdapter) -> MCPServer:
	mcp = MCPServer("warung-madura-agent")

	@mcp.tool()
	def search_product(query: str) -> list[dict[str, Any]]:
		return adapter.search_product(query)

	@mcp.tool()
	def get_product(product_id: str) -> dict[str, Any]:
		return adapter.get_product(product_id)

	@mcp.tool()
	def get_stock(product_id: str) -> dict[str, Any]:
		return adapter.get_stock(product_id)

	@mcp.tool()
	def create_transaction(items: list[dict[str, Any]], payment_method: str, note: str | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
		return adapter.create_transaction(items, payment_method, note, idempotency_key)

	@mcp.tool()
	def add_stock(product_id: str, qty: int, reference: str | None = None, note: str | None = None) -> dict[str, Any]:
		return adapter.add_stock(product_id, qty, reference, note)

	@mcp.tool()
	def get_daily_sales(date: str) -> dict[str, Any]:
		return adapter.get_daily_sales(date)

	@mcp.tool()
	def get_sales_summary(date: str) -> dict[str, Any]:
		return adapter.get_sales_summary(date)

	@mcp.tool()
	def get_product_sales(date: str) -> list[dict[str, Any]] | dict[str, Any]:
		return adapter.get_product_sales(date)

	@mcp.tool()
	def get_category_sales(date: str) -> list[dict[str, Any]] | dict[str, Any]:
		return adapter.get_category_sales(date)

	@mcp.tool()
	def get_payment_summary(date: str) -> list[dict[str, Any]] | dict[str, Any]:
		return adapter.get_payment_summary(date)

	@mcp.tool()
	def get_stock_status(include_inactive: bool = False) -> list[dict[str, Any]] | dict[str, Any]:
		return adapter.get_stock_status(include_inactive)

	@mcp.tool()
	def get_low_stock() -> list[dict[str, Any]] | dict[str, Any]:
		return adapter.get_low_stock()

	@mcp.tool()
	def get_out_of_stock() -> list[dict[str, Any]] | dict[str, Any]:
		return adapter.get_out_of_stock()

	@mcp.tool()
	def get_stock_movements(product_id: str | None = None, start_date: str | None = None, end_date: str | None = None) -> list[dict[str, Any]] | dict[str, Any]:
		return adapter.get_stock_movements(product_id, start_date, end_date)

	return mcp


def run_mcp_server(adapter: MCPToolAdapter) -> None:
	import asyncio

	logging.basicConfig(level=logging.INFO)
	logger.info("Starting Warung MCP server over stdio")
	asyncio.run(create_mcp_server(adapter).run_stdio_async())
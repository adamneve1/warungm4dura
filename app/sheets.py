"""Narrow Google Sheets access layer for the Warung workbook."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import Resource, build


SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class SheetsGateway(Protocol):
    def read_rows(self, sheet_name: str) -> list[dict[str, str]]: ...

    def update_cell(self, sheet_name: str, row_number: int, column_name: str, value: Any) -> None: ...

    def append_rows(self, sheet_name: str, rows: list[list[Any]]) -> None: ...

    def find_row(self, sheet_name: str, column_name: str, value: str) -> tuple[int, dict[str, str]] | None: ...


class GoogleSheetsClient:
    """Header-aware Sheets client; business logic never uses cell coordinates."""

    def __init__(self, credentials_path: Path, spreadsheet_id: str) -> None:
        credentials = Credentials.from_service_account_file(
            str(credentials_path), scopes=SHEETS_SCOPES
        )
        self._service: Resource = build("sheets", "v4", credentials=credentials)
        self._spreadsheet_id = spreadsheet_id

    def read_rows(self, sheet_name: str) -> list[dict[str, str]]:
        response = (
            self._service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self._spreadsheet_id,
                range=sheet_name,
                valueRenderOption="UNFORMATTED_VALUE",
            )
            .execute()
        )
        values: Sequence[Sequence[Any]] = response.get("values", [])
        if not values:
            return []
        headers = [str(header).strip() for header in values[0]]
        return [
            {headers[index]: str(value) if value is not None else "" for index, value in enumerate(row)}
            for row in values[1:]
        ]

    def update_cell(self, sheet_name: str, row_number: int, column_name: str, value: Any) -> None:
        headers = self._read_headers(sheet_name)
        try:
            column_index = headers.index(column_name)
        except ValueError as exc:
            raise ValueError(f"Kolom {column_name} tidak ditemukan di sheet {sheet_name}.") from exc
        column_letter = _column_letter(column_index + 1)
        (
            self._service.spreadsheets()
            .values()
            .update(
                spreadsheetId=self._spreadsheet_id,
                range=f"{sheet_name}!{column_letter}{row_number}",
                valueInputOption="USER_ENTERED",
                body={"values": [[value]]},
            )
            .execute()
        )

    def append_rows(self, sheet_name: str, rows: list[list[Any]]) -> None:
        if not rows:
            return
        (
            self._service.spreadsheets()
            .values()
            .append(
                spreadsheetId=self._spreadsheet_id,
                range=sheet_name,
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": rows},
            )
            .execute()
        )

    def find_row(self, sheet_name: str, column_name: str, value: str) -> tuple[int, dict[str, str]] | None:
        rows = self.read_rows(sheet_name)
        for row_number, row in enumerate(rows, start=2):
            if row.get(column_name, "").strip() == value.strip():
                return row_number, row
        return None

    def _read_headers(self, sheet_name: str) -> list[str]:
        response = (
            self._service.spreadsheets()
            .values()
            .get(spreadsheetId=self._spreadsheet_id, range=f"{sheet_name}!1:1")
            .execute()
        )
        values = response.get("values", [[]])
        return [str(header).strip() for header in values[0]]


def _column_letter(column_number: int) -> str:
    letters = ""
    while column_number:
        column_number, remainder = divmod(column_number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters

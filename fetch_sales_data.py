#!/usr/bin/env python3

"""Fetch Petpooja sales data and store it in SQLite."""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

import requests
from dotenv import load_dotenv


# Load the .env file located next to this script.
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)


API_URL = os.getenv(
    "PETPOOJA_API_URL",
    "http://api.petpooja.com/V1/orders/get_sales_data/",
)

DB_PATH = Path(
    os.getenv("SALES_DB_PATH", str(BASE_DIR / "sales_data.db"))
)

DEFAULT_FROM = "2025-05-03 00:00:00"
DEFAULT_TO = "2025-05-30 23:59:19"

TIMEOUT_SECONDS = 30
MAX_RETRIES = 3


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sales_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_number TEXT,
    sale_date TEXT,
    transaction_time TEXT,
    sale_amount REAL,
    tax_amount REAL,
    discount_amount REAL,
    round_off REAL,
    net_sale REAL,
    payment_mode TEXT,
    order_type TEXT,
    transaction_status TEXT
);
"""


# Petpooja field names mapped to the required SQLite columns.
ALIASES: dict[str, tuple[str, ...]] = {
    "receipt_number": (
        "receipt number",
        "receipt_number",
        "receiptNumber",
        "transaction id",
        "transaction_id",
        "transactionId",
    ),
    "sale_date": (
        "receipt date",
        "receipt_date",
        "receiptDate",
        "sale date",
        "sale_date",
        "saleDate",
    ),
    "transaction_time": (
        "transaction time",
        "transaction_time",
        "transactionTime",
        "sale time",
        "sale_time",
        "saleTime",
        "time",
    ),
    "sale_amount": (
        "invoice amount",
        "invoice_amount",
        "invoiceAmount",
        "sale amount",
        "sale_amount",
        "saleAmount",
    ),
    "tax_amount": (
        "tax amount",
        "tax_amount",
        "taxAmount",
    ),
    "discount_amount": (
        "discount amount",
        "discount_amount",
        "discountAmount",
    ),
    "round_off": (
        "round off",
        "round_off",
        "roundOff",
        "round off amount",
        "round_off_amount",
    ),
    "net_sale": (
        "net sale",
        "net_sale",
        "netSale",
        "final sale amount",
        "final_sale_amount",
        "finalSaleAmount",
    ),
    "payment_mode": (
        "payment mode",
        "payment_mode",
        "paymentMode",
        "payment type",
        "payment_type",
        "paymentType",
    ),
    "order_type": (
        "order type",
        "order_type",
        "orderType",
    ),
    "transaction_status": (
        "transaction status",
        "transaction_status",
        "transactionStatus",
        "sale type",
        "sale_type",
        "saleType",
        "status",
    ),
}


NUMERIC_FIELDS = {
    "sale_amount",
    "tax_amount",
    "discount_amount",
    "round_off",
    "net_sale",
}


def _norm_key(value: Any) -> str:
    """Normalize JSON keys for case/punctuation-insensitive matching."""
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _build_normalized_mapping(
    record: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        _norm_key(key): value
        for key, value in record.items()
    }


def _get_value(
    record: Mapping[str, Any],
    field: str,
) -> Any:
    normalized = _build_normalized_mapping(record)

    for alias in ALIASES[field]:
        key = _norm_key(alias)

        if key in normalized:
            return normalized[key]

    return None


def _parse_number(value: Any) -> float | None:
    if value is None or value == "":
        return None

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)

    cleaned = re.sub(
        r"[^0-9.\-]",
        "",
        str(value).strip(),
    )

    if cleaned in {"", "-", ".", "-."}:
        return None

    try:
        return float(cleaned)
    except ValueError as exc:
        raise ValueError(
            f"Invalid numeric value: {value!r}"
        ) from exc


def _split_datetime(
    value: Any,
) -> tuple[str | None, str | None]:
    """Return ISO-like date and time strings."""
    if value is None or value == "":
        return None, None

    raw = str(value).strip()

    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
    )

    for fmt in formats:
        try:
            parsed = datetime.strptime(raw, fmt)

            date_value = parsed.date().isoformat()

            time_value = (
                parsed.time().isoformat(timespec="seconds")
                if "%H" in fmt
                else None
            )

            return date_value, time_value

        except ValueError:
            continue

    return raw, None


def normalize_record(
    record: Mapping[str, Any],
) -> tuple[Any, ...]:
    """Map one API record to the required SQLite column order."""

    receipt_number = _get_value(
        record,
        "receipt_number",
    )

    raw_sale_date = _get_value(
        record,
        "sale_date",
    )

    sale_date, derived_time = _split_datetime(
        raw_sale_date
    )

    raw_transaction_time = _get_value(
        record,
        "transaction_time",
    )

    transaction_time = (
        str(raw_transaction_time).strip()
        if raw_transaction_time not in (None, "")
        else derived_time
    )

    values: dict[str, Any] = {
        "receipt_number": (
            str(receipt_number).strip()
            if receipt_number not in (None, "")
            else None
        ),
        "sale_date": sale_date,
        "transaction_time": transaction_time,
        "payment_mode": _get_value(
            record,
            "payment_mode",
        ),
        "order_type": _get_value(
            record,
            "order_type",
        ),
        "transaction_status": _get_value(
            record,
            "transaction_status",
        ),
    }

    for field in NUMERIC_FIELDS:
        values[field] = _parse_number(
            _get_value(record, field)
        )

    status = values["transaction_status"]

    if status not in (None, ""):
        values["transaction_status"] = (
            str(status).strip().upper()
        )

    return (
        values["receipt_number"],
        values["sale_date"],
        values["transaction_time"],
        values["sale_amount"],
        values["tax_amount"],
        values["discount_amount"],
        values["round_off"],
        values["net_sale"],
        values["payment_mode"],
        values["order_type"],
        values["transaction_status"],
    )


def _record_score(
    record: Mapping[str, Any],
) -> int:
    """Score how likely a mapping is to represent a sales record."""

    normalized = {
        _norm_key(key)
        for key in record
    }

    score = 0

    for field_aliases in ALIASES.values():
        if any(
            _norm_key(alias) in normalized
            for alias in field_aliases
        ):
            score += 1

    return score


def _find_record_list(
    value: Any,
) -> list[Mapping[str, Any]] | None:
    """Recursively find the most likely list of sales records."""

    if isinstance(value, list):
        mappings = [
            item
            for item in value
            if isinstance(item, Mapping)
        ]

        if mappings:
            record_score = sum(
                _record_score(item)
                for item in mappings[:10]
            )

            if record_score > 0:
                return mappings

        for item in value:
            found = _find_record_list(item)

            if found:
                return found

        return [] if not value else None

    if isinstance(value, Mapping):
        if _record_score(value) >= 2:
            return [value]

        for child in value.values():
            found = _find_record_list(child)

            if found:
                return found

        return None

    return None


def extract_records(
    payload: Any,
) -> list[Mapping[str, Any]]:
    """Extract sales records from the API response."""

    if isinstance(payload, list):
        found = _find_record_list(payload)

        if found is not None:
            return found

        return []

    if not isinstance(payload, Mapping):
        raise ValueError(
            "API response JSON must be an object or array"
        )

    preferred_keys = (
        "data",
        "sales",
        "sales_data",
        "orders",
        "records",
        "rows",
        "result",
        "response",
        "report",
        "Report",
        "items",
        "results",
    )

    normalized_keys = {
        _norm_key(key): key
        for key in payload
    }

    for preferred in preferred_keys:
        actual = normalized_keys.get(
            _norm_key(preferred)
        )

        if actual is None:
            continue

        candidate = payload[actual]

        if isinstance(candidate, list):
            if not candidate:
                return []

            found = _find_record_list(candidate)

            if found is not None:
                return found

        elif isinstance(candidate, Mapping):
            found = _find_record_list(candidate)

            if found is not None:
                return found

    found = _find_record_list(payload)

    if found is not None:
        return found

    success_value = payload.get("success")

    if (
        success_value is False
        or str(success_value).strip().lower()
        in {"false", "0", "no"}
    ):
        message = str(
            payload.get(
                "message",
                "Unknown API error",
            )
        ).strip()

        error_code = payload.get(
            "errorCode",
            payload.get("error_code", ""),
        )

        suffix = (
            f" (errorCode: {error_code})"
            if error_code not in (None, "")
            else ""
        )

        raise RuntimeError(
            "Petpooja API reported failure: "
            f"{message}{suffix}"
        )

    message = str(
        payload.get("message", "")
    ).lower()

    if any(
        term in message
        for term in (
            "no record",
            "no data",
            "not found",
            "no sales",
        )
    ):
        return []

    top_level = ", ".join(
        str(key)
        for key in list(payload.keys())[:20]
    )

    raise ValueError(
        "Could not find a list of sales records "
        "in the API response. "
        f"Top-level response keys: [{top_level}]"
    )


@dataclass(frozen=True)
class Config:
    app_key: str
    app_secret: str
    access_token: str
    rest_id: str

    @classmethod
    def from_env(cls) -> "Config":
        required = (
            "PETPOOJA_APP_KEY",
            "PETPOOJA_APP_SECRET",
            "PETPOOJA_ACCESS_TOKEN",
            "PETPOOJA_REST_ID",
        )

        missing = [
            name
            for name in required
            if not os.getenv(name)
        ]

        if missing:
            raise RuntimeError(
                "Missing environment variable(s): "
                + ", ".join(missing)
            )

        return cls(
            app_key=os.environ["PETPOOJA_APP_KEY"],
            app_secret=os.environ["PETPOOJA_APP_SECRET"],
            access_token=os.environ[
                "PETPOOJA_ACCESS_TOKEN"
            ],
            rest_id=os.environ["PETPOOJA_REST_ID"],
        )


def fetch_sales_data(
    config: Config,
    from_date: str,
    to_date: str,
    *,
    retries: int = MAX_RETRIES,
    timeout: int = TIMEOUT_SECONDS,
) -> Any:
    """Fetch sales data with retry/backoff."""

    params = {
        "app_key": config.app_key,
        "app_secret": config.app_secret,
        "access_token": config.access_token,
        "restID": config.rest_id,
        "from_date": from_date,
        "to_date": to_date,
    }

    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            response = requests.get(
                API_URL,
                params=params,
                timeout=timeout,
            )

            if 500 <= response.status_code < 600:
                response.raise_for_status()

            if not 200 <= response.status_code < 300:
                raise RuntimeError(
                    "Petpooja API returned HTTP "
                    f"{response.status_code}: "
                    f"{response.text[:300]}"
                )

            try:
                return response.json()

            except ValueError as exc:
                raise RuntimeError(
                    "Petpooja API returned "
                    "a non-JSON response"
                ) from exc

        except (
            requests.RequestException,
            RuntimeError,
        ) as exc:
            last_error = exc

            if attempt == retries:
                break

            time.sleep(2 ** (attempt - 1))

    raise RuntimeError(
        f"API request failed after {retries} "
        f"attempt(s): {last_error}"
    ) from last_error


def init_db(
    db_path: Path,
) -> sqlite3.Connection:
    """Create the SQLite database and required table."""

    db_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    connection = sqlite3.connect(db_path)

    try:
        connection.execute(SCHEMA_SQL)
        connection.commit()
        return connection

    except sqlite3.DatabaseError:
        connection.close()
        raise


def replace_records(
    connection: sqlite3.Connection,
    records: Iterable[Mapping[str, Any]],
) -> int:
    """
    Replace the current sales data with the fetched dataset.

    This makes repeated runs deterministic and prevents
    duplicate records from accumulating.
    """

    rows = [
        normalize_record(record)
        for record in records
    ]

    sql = """
        INSERT INTO sales_data (
            receipt_number,
            sale_date,
            transaction_time,
            sale_amount,
            tax_amount,
            discount_amount,
            round_off,
            net_sale,
            payment_mode,
            order_type,
            transaction_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    try:
        with connection:
            connection.execute(
                "DELETE FROM sales_data"
            )

            if rows:
                connection.executemany(
                    sql,
                    rows,
                )

    except sqlite3.DatabaseError:
        connection.rollback()
        raise

    return len(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "--from-date",
        default=os.getenv(
            "FROM_DATE",
            DEFAULT_FROM,
        ),
        help=(
            "Start datetime, e.g. "
            "'2025-05-03 00:00:00'"
        ),
    )

    parser.add_argument(
        "--to-date",
        default=os.getenv(
            "TO_DATE",
            DEFAULT_TO,
        ),
        help=(
            "End datetime, e.g. "
            "'2025-05-30 23:59:19'"
        ),
    )

    parser.add_argument(
        "--db",
        default=str(DB_PATH),
        help="SQLite database path",
    )

    parser.add_argument(
        "--retries",
        type=int,
        default=MAX_RETRIES,
        help="Number of API attempts",
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        config = Config.from_env()

        payload = fetch_sales_data(
            config,
            args.from_date,
            args.to_date,
            retries=max(1, args.retries),
        )

        records = extract_records(payload)

        connection = init_db(
            Path(args.db)
        )

        try:
            inserted = replace_records(
                connection,
                records,
            )
        finally:
            connection.close()

        print(
            f"Fetched {len(records)} record(s); "
            f"inserted {inserted} record(s) "
            f"into {args.db}."
        )

        return 0

    except (
        RuntimeError,
        ValueError,
        sqlite3.DatabaseError,
    ) as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
# Petpooja Sales Data - Machine Test

This repository implements the supplied machine-test requirement: fetch sales data from the Petpooja API and store the mapped records in a local SQLite database named `sales_data.db`.

## What is included

* `fetch_sales_data.py` - API client, JSON normalization, SQLite schema creation, data insertion, error handling, and retry/backoff.
* `sales_data.db` - SQLite database containing the required `sales_data` table and the fetched Petpooja sales records.
* `.env.example` - environment-variable template; credentials are intentionally not stored in the repository.
* `tests/test_fetch_sales_data.py` - tests for field mapping, response-envelope handling, SQLite insertion/schema, and retry behavior.
* `requirements.txt` - Python dependency list.

## Setup

Python 3.10+ is recommended.

```bash
python -m venv .venv

# Windows PowerShell:
.venv\Scripts\Activate.ps1

# macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt
```

Copy `.env.example` to `.env` in the same folder as `fetch_sales_data.py` and fill in the four Petpooja credentials from the machine-test PDF.

The script loads `.env` automatically, even when the script is run from another directory.

**Do not commit `.env` or any API credentials to the repository.**

The machine-test date window is:

* From: `2025-05-03 00:00:00`
* To: `2025-05-30 23:59:19`

These are the default dates used by the script. They can be overridden using `FROM_DATE` / `TO_DATE` environment variables or CLI arguments.

## Run

Recommended: configure the credentials in `.env`, then run:

```bash
python fetch_sales_data.py
```

Alternatively, credentials can be supplied through the current PowerShell session:

```powershell
$env:PETPOOJA_APP_KEY="..."
$env:PETPOOJA_APP_SECRET="..."
$env:PETPOOJA_ACCESS_TOKEN="..."
$env:PETPOOJA_REST_ID="..."

python fetch_sales_data.py
```

The date range can also be supplied explicitly:

```bash
python fetch_sales_data.py --from-date "2025-05-03 00:00:00" --to-date "2025-05-30 23:59:19"
```

To specify a custom database path:

```bash
python fetch_sales_data.py --db sales_data.db
```

## Database schema

The `sales_data` table follows the machine-test specification:

```sql
CREATE TABLE sales_data (
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
```

## Field mapping

The source fields specified in the machine-test brief are mapped as follows:

| API/source field   | SQLite column      |
| ------------------ | ------------------ |
| Receipt Date       | sale_date          |
| Receipt number     | receipt_number     |
| Invoice amount     | sale_amount        |
| Discount amount    | discount_amount    |
| Tax amount         | tax_amount         |
| Net sale           | net_sale           |
| Transaction status | transaction_status |

The implementation also supports common naming variants for `transaction_time`, `round_off`, `payment_mode`, and `order_type` because these columns are required by the supplied schema.

## Error handling and retry behavior

* Missing credentials fail fast with a clear error.
* Non-2xx API responses are treated as failures.
* 5xx responses and transport errors are retried with exponential backoff.
* Invalid or non-JSON responses are rejected.
* JSON records that cannot be found in a supported response envelope are rejected.
* SQLite errors are surfaced and the database transaction is rolled back.

## Testing

Run:

```bash
python -m unittest discover -s tests -v
```

The test suite does not call the live Petpooja API. It uses representative API-shaped records so that transformation and database-storage logic can be verified without exposing credentials or depending on network availability.

## GitHub submission

The repository contains the following submission files:

```text
fetch_sales_data.py
sales_data.db
README.md
requirements.txt
.env.example
.gitignore
tests/test_fetch_sales_data.py
```

Do **not** commit:

```text
.env
```

The `.env` file contains the Petpooja API credentials and is excluded through `.gitignore`.

## Database result

The supplied `sales_data.db` was populated using the live Petpooja API response for the required date range.

The completed fetch returned:

```text
1,287 records
```

These records are stored in the `sales_data` SQLite table using the schema and field mappings described above.

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fetch_sales_data import (
    Config,
    extract_records,
    fetch_sales_data,
    init_db,
    replace_records,
    normalize_record,
)


class SalesDataTests(unittest.TestCase):
    def test_normalize_record(self):
        row = normalize_record({
            "Receipt Date": "2025-05-20 13:45:10",
            "Receipt number": "R-1001",
            "Invoice amount": "₹1,000.50",
            "Discount amount": "50",
            "Tax amount": "90.00",
            "Net sale": "1040.50",
            "Round Off": "-0.50",
            "Payment Mode": "UPI",
            "Order Type": "Dine-In",
            "Transaction status": "sale",
        })
        self.assertEqual(row[0], "R-1001")
        self.assertEqual(row[1], "2025-05-20")
        self.assertEqual(row[2], "13:45:10")
        self.assertEqual(row[3], 1000.50)
        self.assertEqual(row[6], -0.50)
        self.assertEqual(row[-1], "SALE")

    def test_extract_records_from_data_envelope(self):
        payload = {"data": [{"receipt_number": "R1"}, {"receipt_number": "R2"}]}
        self.assertEqual(len(extract_records(payload)), 2)

    def test_sqlite_schema_and_insert(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "sales_data.db"
            conn = init_db(db)

            inserted = replace_records(conn, [{
                "receipt_number": "R1",
                "sale_date": "2025-05-20",
                "transaction_time": "10:00:00",
                "sale_amount": 100,
                "tax_amount": 18,
                "discount_amount": 0,
                "round_off": 0,
                "net_sale": 118,
                "payment_mode": "CASH",
                "order_type": "DINE-IN",
                "transaction_status": "SALE",
            }])

            self.assertEqual(inserted, 1)

            row = conn.execute(
                "SELECT receipt_number, net_sale FROM sales_data"
            ).fetchone()

            self.assertEqual(row, ("R1", 118.0))
            conn.close()

    @patch("fetch_sales_data.time.sleep", return_value=None)
    @patch("fetch_sales_data.requests.get")
    def test_retry_on_server_error(self, mock_get, _sleep):
        first = Mock(status_code=500, text="temporary failure")
        second = Mock(status_code=200)
        second.json.return_value = {"data": []}

        mock_get.side_effect = [first, second]

        config = Config("key", "secret", "token", "rest")

        payload = fetch_sales_data(
            config,
            "2025-05-03 00:00:00",
            "2025-05-30 23:59:19",
            retries=2,
        )

        self.assertEqual(payload, {"data": []})
        self.assertEqual(mock_get.call_count, 2)


if __name__ == "__main__":
    unittest.main()
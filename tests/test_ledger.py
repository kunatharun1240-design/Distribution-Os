from concurrent.futures import ThreadPoolExecutor
import csv
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from streamlit.testing.v1 import AppTest

from distributionos.catalog import list_photos, list_products, save_product
from distributionos.inventory_screen import INVENTORY_FIELDS, inventory_export_rows
from distributionos.exports import csv_bytes
from distributionos.ledger import MigrationBlocked, current_inventory, ensure_ledger, movement_history, record_movement


def product(sku="COLA-24"):
    return {"sku": sku, "brand": "Test", "product_name": "Test Cola", "package_size": "500 mL",
            "units_per_case": 24, "packaging_type": "PET case", "barcode": "001234" if sku == "COLA-24" else None}


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "catalog.sqlite3"
        save_product(product(), path=self.path, create=True)

    def movement(self, kind, quantity, **kwargs):
        return record_movement("COLA-24", kind, quantity, path=self.path, **kwargs)

    def test_backup_preserves_catalog_and_photos_and_migration_is_repeatable(self):
        output = io.BytesIO()
        Image.new("RGB", (20, 20), "red").save(output, format="PNG")
        save_product(product(), [output.getvalue()], self.path)
        before = list_products(self.path)
        photos = list_photos("COLA-24", self.path)
        backup = ensure_ledger(self.path)
        self.assertTrue(backup.exists())
        self.assertEqual(list_products(backup), before)
        self.assertEqual(list_photos("COLA-24", backup), photos)
        with sqlite3.connect(backup) as db:
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='inventory_movements'").fetchone())
        self.assertEqual(list_products(self.path), before)
        self.assertEqual(list_photos("COLA-24", self.path), photos)
        self.assertIsNone(ensure_ledger(self.path))
        self.assertEqual(len(list((self.root / "backups").glob("*.sqlite3"))), 1)

    def test_failed_backup_stops_before_schema_changes(self):
        with patch("distributionos.ledger._backup", side_effect=OSError("disk full")):
            with self.assertRaises(MigrationBlocked):
                ensure_ledger(self.path)
        with sqlite3.connect(self.path) as db:
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='inventory_movements'").fetchone())
        self.assertEqual(len(list_products(self.path)), 1)

    def test_unexpected_schema_stops_without_changes(self):
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE inventory_movements (unexpected TEXT)")
        before = self.path.read_bytes()
        with self.assertRaises(MigrationBlocked):
            ensure_ledger(self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_all_products_start_uninitialized_and_stock_calculates(self):
        save_product(product("SPRITE-24"), path=self.path, create=True)
        rows = current_inventory(self.path)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(p["current_stock"] == 0 and not p["opening_set"] for p in rows))
        self.movement("Opening stock", 25, notes="Opening count")
        self.movement("Stock In", 15, notes="Delivery")
        self.movement("Stock Out", 10, notes="Order 123")
        self.assertEqual(current_inventory(self.path)[0]["current_stock"], 30)
        history = movement_history(self.path)
        self.assertEqual([r["movement_type"] for r in history], ["Stock Out", "Stock In", "Opening stock"])
        self.assertEqual(history[0]["notes"], "Order 123")
        self.assertTrue(all(r["recorded_at"] and r["product_name"] == "Test Cola" and r["sku"] == "COLA-24" for r in history))

    def test_zero_opening_and_single_opening(self):
        self.movement("Opening stock", 0)
        with self.assertRaises(ValueError):
            self.movement("Opening stock", 20)
        self.movement("Stock In", 5)
        self.movement("Stock Out", 5)
        self.assertEqual(current_inventory(self.path)[0]["current_stock"], 0)
        self.assertEqual(len(movement_history(self.path)), 3)

    def test_negative_stock_rejected_without_history_entry(self):
        self.movement("Opening stock", 25)
        with self.assertRaisesRegex(ValueError, "Only 25"):
            self.movement("Stock Out", 26)
        self.assertEqual(current_inventory(self.path)[0]["current_stock"], 25)
        self.assertEqual(len(movement_history(self.path)), 1)

    def test_invalid_quantities_and_missing_opening(self):
        for kind, quantity in [("Stock In", 1), ("Stock Out", 1), ("Other", 1),
                               ("Opening stock", -1), ("Opening stock", 1.5), ("Opening stock", True)]:
            with self.subTest(kind=kind, quantity=quantity):
                with self.assertRaises(ValueError):
                    self.movement(kind, quantity)
        self.movement("Opening stock", 0)
        for quantity in [0, -1, 1.5, True, 2_147_483_648]:
            with self.assertRaises(ValueError):
                self.movement("Stock In", quantity)
        with self.assertRaises(ValueError):
            record_movement("NOT-A-PRODUCT", "Opening stock", 1, path=self.path)

    def test_persistence_in_a_new_python_process(self):
        self.movement("Opening stock", 25)
        self.movement("Stock In", 15)
        self.movement("Stock Out", 10)
        result = subprocess.run([sys.executable, "-B", "-c",
            "import json,sys; from distributionos.ledger import current_inventory,movement_history; "
            "print(json.dumps([current_inventory(sys.argv[1])[0]['current_stock'],len(movement_history(sys.argv[1]))]))",
            str(self.path)], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout), [30, 3])

    def test_idempotent_save_retries(self):
        self.movement("Opening stock", 0)
        first = self.movement("Stock In", 10, request_id="same-request")
        self.assertEqual(self.movement("Stock In", 10, request_id="same-request"), first)
        with self.assertRaises(ValueError):
            self.movement("Stock In", 11, request_id="same-request")
        self.assertEqual(current_inventory(self.path)[0]["current_stock"], 10)

    def test_simultaneous_stock_out_cannot_oversell(self):
        self.movement("Opening stock", 10)
        def withdraw(_):
            try:
                self.movement("Stock Out", 7)
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(withdraw, [1, 2]))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(current_inventory(self.path)[0]["current_stock"], 3)

    def test_database_guards_and_name_history(self):
        self.movement("Opening stock", 5)
        changed = {**product(), "product_name": "Renamed Cola", "active": False}
        save_product(changed, path=self.path)
        self.assertEqual(current_inventory(self.path)[0]["product_name"], "Renamed Cola")
        self.assertEqual(current_inventory(self.path)[0]["active"], 0)
        self.assertEqual(movement_history(self.path)[0]["product_name"], "Test Cola")
        with sqlite3.connect(self.path) as db:
            for statement in ["DELETE FROM inventory_movements", "UPDATE inventory_movements SET quantity=99"]:
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(statement)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO inventory_movements(request_id,recorded_at,sku,product_name,movement_type,quantity,notes) VALUES ('raw','now','COLA-24','Cola','Stock Out',6,'')")

    def test_inventory_csv_reports_saved_balances(self):
        self.movement("Opening stock", 25)
        self.movement("Stock Out", 5)
        rows = inventory_export_rows(current_inventory(self.path))
        exported = list(csv.DictReader(io.StringIO(csv_bytes(rows, INVENTORY_FIELDS).decode())))
        self.assertEqual(exported[0]["Current stock"], "20")
        self.assertEqual(exported[0]["SKU"], "COLA-24")

    def test_dashboard_opening_in_out_export_and_restart(self):
        with patch.dict(os.environ, {"DISTRIBUTIONOS_DATA_DIR": self.temporary.name}):
            app = AppTest.from_file("app.py").run()
            self.assertFalse(app.exception)
            self.assertEqual(app.header[0].value, "Inventory dashboard")
            app.number_input[0].set_value(25)
            app.text_input[0].set_value("Opening count")
            app.button[0].click().run()
            self.assertFalse(app.exception)
            app.number_input[0].set_value(15)
            app.button[0].click().run()
            next(r for r in app.radio if r.label == "Movement type").set_value("Stock Out").run()
            app.number_input[0].set_value(10)
            with patch("streamlit.download_button") as download:
                app.button[0].click().run()
            self.assertFalse(app.exception)
            calls = [c for c in download.call_args_list if c.args[0] == "Export inventory CSV"]
            payload = calls[-1].args[1]
            self.assertEqual(list(csv.DictReader(io.StringIO(payload.decode())))[0]["Current stock"], "30")
            self.assertEqual(len(app.dataframe[1].value), 3)
            app.number_input[0].set_value(31)
            app.button[0].click().run()
            self.assertTrue(any("Not enough stock" in error.value for error in app.error))
            fresh = AppTest.from_file("app.py").run()
            self.assertFalse(fresh.exception)
            self.assertEqual(fresh.dataframe[0].value.iloc[0]["Current stock"], 30)
            self.assertEqual(len(fresh.dataframe[1].value), 3)

    def test_schema_failure_rolls_back_and_keeps_backup(self):
        from distributionos.ledger import _open
        def deny_trigger_creation(path):
            db = _open(path)
            db.set_authorizer(lambda action, *args: sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_CREATE_TRIGGER else sqlite3.SQLITE_OK)
            return db
        with patch("distributionos.ledger._open", side_effect=deny_trigger_creation):
            with self.assertRaises(MigrationBlocked):
                ensure_ledger(self.path)
        self.assertEqual(len(list_products(self.path)), 1)
        with sqlite3.connect(self.path) as db:
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='inventory_movements'").fetchone())
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='inventory_ledger_meta'").fetchone())
        self.assertEqual(len(list((self.root / "backups").glob("*.sqlite3"))), 1)

    def test_backup_includes_committed_wal_data(self):
        with sqlite3.connect(self.path) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("UPDATE products SET product_name='Committed WAL product'")
            writer.commit()
            backup = ensure_ledger(self.path)
            self.assertEqual(list_products(backup)[0]["product_name"], "Committed WAL product")

    def test_damaged_database_is_not_modified(self):
        damaged = self.root / "damaged.sqlite3"
        damaged.write_bytes(b"not a database")
        with self.assertRaises(MigrationBlocked):
            ensure_ledger(damaged)
        self.assertEqual(damaged.read_bytes(), b"not a database")

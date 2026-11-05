import csv
import io
import os
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from streamlit.testing.v1 import AppTest

from app import inventory_csv, inventory_rows, manual_rows, save_manual_inventory


class Upload(io.BytesIO):
    def __init__(self, data, name):
        super().__init__(data)
        self.name = name
        self.size = len(data)


class AppTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        environment = patch.dict(os.environ, {"DISTRIBUTIONOS_DATA_DIR": temporary.name})
        environment.start()
        self.addCleanup(environment.stop)

    def legacy_app(self):
        app = AppTest.from_file("app.py").run()
        return app.sidebar.radio[0].set_value("Inventory & image upload").run()

    def test_manual_save_and_export(self):
        app = self.legacy_app()
        self.assertFalse(app.exception)
        app.session_state["manual_inventory_editor"] = {
            "edited_rows": {0: {"Quantity": 25}, 1: {"Quantity": 15}, 2: {"Quantity": 10}},
            "added_rows": [], "deleted_rows": [],
        }
        with patch("streamlit.download_button") as download:
            app.button[0].click().run()
        self.assertFalse(app.exception)
        saved = app.session_state["manual_inventory"]
        self.assertEqual([r["Quantity"] for r in saved], [25, 15, 10])
        self.assertTrue(all(r["Last updated"] and r["Unit"] == "cases" for r in saved))
        calls = [c for c in download.call_args_list if c.args[0] == "Export CSV"]
        self.assertTrue(calls)
        self.assertFalse(calls[-1].kwargs["disabled"])
        rows = list(csv.DictReader(io.StringIO(calls[-1].kwargs["data"].decode())))
        self.assertEqual([r["Quantity"] for r in rows], ["25", "15", "10"])
        self.assertEqual([r["Product name"] for r in rows], ["Coca-Cola", "Sprite", "Fanta"])
        app.run()
        self.assertEqual([r["Quantity"] for r in app.session_state["manual_inventory"]], [25, 15, 10])
        app.session_state["manual_inventory_editor"] = {
            "edited_rows": {0: {"Quantity": 30}}, "added_rows": [], "deleted_rows": []}
        app.button[0].click().run()
        self.assertEqual([r["Quantity"] for r in app.session_state["manual_inventory"]], [30, 15, 10])
        fresh = self.legacy_app()
        self.assertEqual([r["Quantity"] for r in fresh.session_state["manual_inventory"]], [0, 0, 0])

    def test_manual_validation(self):
        for invalid in (-1, 1.5, None, True):
            rows = manual_rows()
            rows[0]["Quantity"] = invalid
            with self.assertRaises(ValueError):
                save_manual_inventory(rows)

    def test_csv_template(self):
        rows = list(csv.DictReader(io.StringIO(inventory_csv(inventory_rows("photo.png")).decode())))
        self.assertEqual([r["product"] for r in rows], ["Coca-Cola", "Sprite", "Fanta"])
        self.assertTrue(all(r["case_count"] == "" and r["status"] == "not_analyzed" for r in rows))

    def test_csv_filename_safety(self):
        rows = list(csv.DictReader(io.StringIO(inventory_csv(inventory_rows("=1+1.png")).decode())))
        self.assertEqual(rows[0]["image_name"], "'=1+1.png")

    def test_dashboard(self):
        app = self.legacy_app()
        self.assertFalse(app.exception)
        self.assertEqual([m.label for m in app.metric], ["Coca-Cola", "Sprite", "Fanta"])
        self.assertEqual(len(app.table), 1)

    def test_image_formats(self):
        for fmt, name in [("JPEG", "test.jpg"), ("JPEG", "test.jpeg"), ("PNG", "test.png")]:
            with self.subTest(name=name):
                data = io.BytesIO()
                Image.new("RGB", (16, 16), "red").save(data, format=fmt)
                with patch("streamlit.file_uploader", return_value=Upload(data.getvalue(), name)):
                    app = self.legacy_app()
                self.assertFalse(app.exception)
                self.assertEqual(len(app.success), 1)
                self.assertEqual(len(app.get("imgs")), 1)
                self.assertTrue(all(row == name for row in app.table[0].value["image_name"]))

    def test_invalid_upload(self):
        with patch("streamlit.file_uploader", return_value=Upload(b"invalid", "broken.png")):
            app = self.legacy_app()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.error), 1)
        self.assertEqual(len(app.success), 0)


if __name__ == "__main__":
    unittest.main()

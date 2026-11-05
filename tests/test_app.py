import csv
import io
import unittest
from unittest.mock import patch

from PIL import Image
from streamlit.testing.v1 import AppTest

from app import inventory_csv, inventory_rows


class Upload(io.BytesIO):
    def __init__(self, data, name):
        super().__init__(data)
        self.name = name
        self.size = len(data)


class AppTests(unittest.TestCase):
    def test_csv_template(self):
        rows = list(csv.DictReader(io.StringIO(inventory_csv(inventory_rows("photo.png")).decode())))
        self.assertEqual([r["product"] for r in rows], ["Coca-Cola", "Sprite", "Fanta"])
        self.assertTrue(all(r["case_count"] == "" and r["status"] == "not_analyzed" for r in rows))

    def test_csv_filename_safety(self):
        rows = list(csv.DictReader(io.StringIO(inventory_csv(inventory_rows("=1+1.png")).decode())))
        self.assertEqual(rows[0]["image_name"], "'=1+1.png")

    def test_dashboard(self):
        app = AppTest.from_file("app.py").run()
        self.assertFalse(app.exception)
        self.assertEqual([m.label for m in app.metric], ["Coca-Cola", "Sprite", "Fanta"])
        self.assertEqual(len(app.table), 1)

    def test_image_formats(self):
        for fmt, name in [("JPEG", "test.jpg"), ("JPEG", "test.jpeg"), ("PNG", "test.png")]:
            with self.subTest(name=name):
                data = io.BytesIO()
                Image.new("RGB", (16, 16), "red").save(data, format=fmt)
                with patch("streamlit.file_uploader", return_value=Upload(data.getvalue(), name)):
                    app = AppTest.from_file("app.py").run()
                self.assertFalse(app.exception)
                self.assertEqual(len(app.success), 1)
                self.assertEqual(len(app.get("imgs")), 1)
                self.assertTrue(all(row == name for row in app.table[0].value["image_name"]))

    def test_invalid_upload(self):
        with patch("streamlit.file_uploader", return_value=Upload(b"invalid", "broken.png")):
            app = AppTest.from_file("app.py").run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.error), 1)
        self.assertEqual(len(app.success), 0)


if __name__ == "__main__":
    unittest.main()

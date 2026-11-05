import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from streamlit.testing.v1 import AppTest

from distributionos.catalog import list_photos, list_products, save_product
from distributionos.dataset import export_dataset, validate_manifest
from distributionos.recognition import Detection, Evidence, FusionPolicy, fuse, run_pipeline


def product(sku="COLA-500-24", **changes):
    row = {"sku": sku, "brand": "Test brand", "product_name": "Test Cola", "package_size": "500 mL",
           "units_per_case": 24, "packaging_type": "PET shrink wrap", "barcode": "0012345678905", "active": True}
    row.update(changes)
    return row


def image_bytes():
    output = io.BytesIO()
    Image.new("RGB", (100, 80), "red").save(output, format="PNG")
    return output.getvalue()


class LocalCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "catalog.sqlite3"

    def test_120_skus_and_photo_persistence(self):
        for i in range(120):
            save_product(product(f"SKU-{i:03}", barcode=f"{i:013}", brand=f"Brand {i % 15}"), path=self.path, create=True)
        self.assertEqual(len(list_products(self.path)), 120)
        save_product(product("SKU-000", barcode="0000000000000", package_size="330 mL"), [image_bytes()], self.path)
        rows = list_products(self.path)
        self.assertEqual(rows[0]["package_size"], "330 mL")
        self.assertEqual(rows[0]["barcode"], "0000000000000")
        with Image.open(io.BytesIO(list_photos("SKU-000", self.path)[0]["image"])) as image:
            self.assertEqual(image.size, (100, 80))
        save_product(product("SKU-000", barcode="0000000000000", active=False), path=self.path)
        self.assertEqual(len(list_products(self.path, active_only=True)), 119)
        self.assertEqual(len(list_photos("SKU-000", self.path)), 1)

    def test_duplicates_and_bad_photos_do_not_corrupt_catalog(self):
        save_product(product(), path=self.path, create=True)
        for values, photos in [(product(), []), (product("OTHER"), []),
                               (product("NEW", barcode="222"), [b"bad image"])]:
            with self.assertRaises((ValueError, OSError)):
                save_product(values, photos, self.path, create=True)
        self.assertEqual(len(list_products(self.path)), 1)
        with self.assertRaises(ValueError):
            save_product(product(units_per_case=0), path=self.path)

    def test_catalog_screen_create_edit_and_photos(self):
        with patch.dict(os.environ, {"DISTRIBUTIONOS_DATA_DIR": self.temp.name}):
            app = AppTest.from_file("app.py").run()
            app.sidebar.radio[0].set_value("Product catalog").run()
            self.assertFalse(app.exception)
            fields = {field.label: field for field in app.text_input}
            for label, value in [("SKU / product code", "COLA-500-24"), ("Brand", "Test brand"),
                                 ("Product name", "Test Cola"), ("Package size", "500 mL"),
                                 ("Packaging type", "PET shrink wrap"),
                                 ("Barcode (optional; preserve leading zeros)", "0012345678905")]:
                fields[label].set_value(value)
            app.number_input[0].set_value(24)
            upload = io.BytesIO(image_bytes())
            with patch("streamlit.file_uploader", return_value=[upload]):
                app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(list_products(self.path)[0]["sku"], "COLA-500-24")
            self.assertEqual(len(list_photos("COLA-500-24", self.path)), 1)
            app.selectbox[0].set_value("COLA-500-24").run()
            self.assertEqual(len(app.get("imgs")), 1)
            next(field for field in app.text_input if field.label == "Package size").set_value("600 mL")
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(list_products(self.path)[0]["package_size"], "600 mL")
            self.assertEqual(len(list_photos("COLA-500-24", self.path)), 1)

    def test_photo_manual_review_does_not_change_inventory(self):
        class Upload(io.BytesIO):
            name = "synthetic.png"
            size = len(image_bytes())
        save_product(product(), path=self.path, create=True)
        with patch.dict(os.environ, {"DISTRIBUTIONOS_DATA_DIR": self.temp.name}):
            with patch("streamlit.file_uploader", return_value=Upload(image_bytes())):
                app = AppTest.from_file("app.py").run()
                next(b for b in app.button if b.label == "Send photo for manual verification").click().run()
            self.assertFalse(app.exception)
            app.sidebar.radio[0].set_value("Manual verification").run()
            app.selectbox[0].set_value("COLA-500-24")
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["review_queue"][0]["status"], "verified")
            self.assertEqual(app.session_state["review_queue"][0]["sku"], "COLA-500-24")
            self.assertEqual([r["Quantity"] for r in app.session_state["manual_inventory"]], [0, 0, 0])
            app.selectbox[0].set_value("Unknown / mixed / unreadable")
            app.button[0].click().run()
            self.assertEqual(app.session_state["review_queue"][0]["status"], "unknown")
            app.sidebar.radio[0].set_value("Dataset workflow").run()
            self.assertFalse(app.exception)


class RecognitionTests(unittest.TestCase):
    def setUp(self):
        self.products = [product(), product("COLA-330-24", package_size="330 mL", barcode="222")]

    def test_default_no_automatic_recognition(self):
        result = fuse(Evidence({"COLA-500-24": 0.99}, "Test Cola 500 mL", ("0012345678905",)), self.products)
        self.assertEqual(result.status, "needs_review")
        self.assertIsNone(result.sku)

    def test_unknown_conflict_and_low_confidence(self):
        policy = FusionPolicy(auto_accept=True)
        cases = [Evidence(), Evidence({"UNREGISTERED": 0.99}), Evidence(barcodes=("unknown",)),
                 Evidence({"COLA-500-24": 0.99}, barcodes=("222",)),
                 Evidence({"COLA-500-24": 0.6}, "Test Cola 500 mL"),
                 Evidence({"COLA-500-24": 0.99}, "Test Cola 330 mL"),
                 Evidence({"COLA-500-24": 0.91, "COLA-330-24": 0.90}, "Test Cola 500 mL")]
        for evidence in cases:
            with self.subTest(evidence=evidence):
                self.assertEqual(fuse(evidence, self.products, policy).status, "needs_review")
        match = fuse(Evidence({"COLA-500-24": 0.99}, "Test Cola 500 mL"), self.products, policy)
        self.assertEqual(match.sku, "COLA-500-24")

    def test_separate_detection_and_crop_adapters(self):
        class FakeDetector:
            def detect(self, image):
                return [Detection((0, 0, 20, 20), 0.9), Detection((20, 0, 40, 20), 0.2)]
        class FakeClassifier:
            def classify(self, crop):
                assert crop.size == (20, 20)
                return {"COLA-500-24": 0.99}
        class FakeOCR:
            def read(self, crop):
                return "Test Cola 500 mL"
        class FakeBarcode:
            def decode(self, crop):
                return ("0012345678905",)
        results = run_pipeline(Image.new("RGB", (100, 80)), self.products,
                               FakeDetector(), FakeClassifier(), FakeOCR(), FakeBarcode(), FusionPolicy(auto_accept=True))
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["decision"].sku, "COLA-500-24")
        self.assertEqual(results[1]["decision"].status, "needs_review")


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        Image.new("RGB", (100, 80)).save(self.root / "scene.png")
        self.manifest = self.root / "annotations.jsonl"
        self.row = {"image_id": "scene-001", "image": "scene.png", "width": 100, "height": 80,
                    "capture_group": "session-1", "split": "train", "reviewed": True,
                    "cases": [{"bbox_xyxy": [0, 0, 50, 40], "sku": "COLA-500-24"},
                              {"bbox_xyxy": [50, 0, 100, 40], "sku": None}]}

    def write(self, rows):
        self.manifest.write_text("".join(json.dumps(row) + "\n" for row in rows))

    def test_generic_detector_and_sku_crop_export(self):
        self.write([self.row])
        rows, warnings = validate_manifest(self.manifest, self.root, [product()])
        self.assertTrue(warnings)  # Missing validation/test data is reported, not hidden.
        export = self.root / "export"
        export_dataset(rows, self.root, [product()], export)
        labels = (export / "labels/train/000000.txt").read_text().splitlines()
        self.assertEqual(len(labels), 2)
        self.assertTrue(all(line.startswith("0 ") for line in labels))
        crops = [json.loads(line) for line in (export / "classification.jsonl").read_text().splitlines()]
        self.assertEqual([r["sku"] for r in crops], ["COLA-500-24", None])
        self.assertTrue(all((export / r["crop"]).exists() for r in crops))
        self.assertEqual(json.loads((export / "sku_vocabulary.json").read_text()), ["COLA-500-24"])
        with self.assertRaises(FileExistsError):
            export_dataset(rows, self.root, [product()], export)

    def test_invalid_annotations_rejected(self):
        for change in ({"reviewed": False}, {"image": "../outside.png"}, {"width": 999},
                       {"cases": [{"bbox_xyxy": [0, 0, 101, 40], "sku": None}]},
                       {"cases": [{"bbox_xyxy": [0, 0, 20, 20], "sku": "NOT-IN-CATALOG"}]}):
            self.write([{**self.row, **change}])
            with self.assertRaises(ValueError):
                validate_manifest(self.manifest, self.root, [product()])

    def test_capture_group_split_leakage_rejected(self):
        Image.new("RGB", (100, 80)).save(self.root / "other.png")
        self.write([self.row, {**self.row, "image_id": "scene-002", "image": "other.png", "split": "test"}])
        with self.assertRaisesRegex(ValueError, "leaks"):
            validate_manifest(self.manifest, self.root, [product()])

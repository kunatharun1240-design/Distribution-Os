"""Local catalog metadata only; this database never stores inventory counts."""

from contextlib import contextmanager
from datetime import datetime, timezone
import io
import os
from pathlib import Path
import re
import sqlite3
import warnings

from PIL import Image, ImageOps


def catalog_path():
    return Path(os.environ.get("DISTRIBUTIONOS_DATA_DIR", Path(__file__).resolve().parent.parent / "local_data")) / "catalog.sqlite3"


@contextmanager
def connect(path=None):
    path = Path(path) if path is not None else catalog_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            sku TEXT PRIMARY KEY,
            brand TEXT NOT NULL,
            product_name TEXT NOT NULL,
            package_size TEXT NOT NULL,
            units_per_case INTEGER NOT NULL CHECK(units_per_case > 0),
            packaging_type TEXT NOT NULL,
            barcode TEXT UNIQUE,
            active INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reference_photos (
            id INTEGER PRIMARY KEY,
            sku TEXT NOT NULL REFERENCES products(sku),
            image BLOB NOT NULL,
            created_at TEXT NOT NULL
        );
    """)
    try:
        yield db
        db.commit()
    finally:
        db.close()


def list_products(path=None, active_only=False):
    with connect(path) as db:
        query = "SELECT * FROM products" + (" WHERE active = 1" if active_only else "") + " ORDER BY sku"
        return [dict(row) for row in db.execute(query)]


def normalize_product(values):
    product = {}
    for field in ("sku", "brand", "product_name", "package_size", "packaging_type"):
        value = str(values.get(field, "")).strip()
        if not value or len(value) > 200:
            raise ValueError(f"{field.replace('_', ' ').title()} is required (maximum 200 characters).")
        product[field] = value
    product["sku"] = product["sku"].upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,63}", product["sku"]):
        raise ValueError("SKU must be 1–64 letters, numbers, dots, underscores or hyphens.")
    units = values.get("units_per_case")
    if isinstance(units, bool) or not isinstance(units, int) or units < 1:
        raise ValueError("Bottles/cans per case must be a positive whole number.")
    product["units_per_case"] = units
    barcode = str(values.get("barcode") or "").strip()
    if barcode and (len(barcode) > 100 or not barcode.isascii() or not barcode.isalnum()):
        raise ValueError("Barcode must contain at most 100 ASCII letters or numbers. Leave blank if unknown.")
    product["barcode"] = barcode or None  # Stored as text to preserve leading zeros.
    product["active"] = int(bool(values.get("active", True)))
    return product


def reference_jpeg(data):
    if len(data) > 20 * 1024 * 1024:
        raise ValueError("Reference images must be no larger than 20 MB.")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {"JPEG", "PNG"}:
                raise ValueError("Reference images must be JPEG or PNG.")
            image.load()
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((1600, 1600))
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=90)
            return output.getvalue()  # Normalized copy without original EXIF metadata.


def save_product(values, photos=(), path=None, *, create=False):
    product = normalize_product(values)
    photos = list(photos)
    if len(photos) > 10:
        raise ValueError("Add at most 10 reference photographs per save.")
    images = [reference_jpeg(data) for data in photos]
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    fields = tuple(product) + ("updated_at",)
    data = tuple(product.values()) + (timestamp,)
    with connect(path) as db:
        exists = db.execute("SELECT 1 FROM products WHERE sku = ?", (product["sku"],)).fetchone()
        if create and exists:
            raise ValueError("This SKU already exists. Select it to edit instead.")
        if not create and not exists:
            raise ValueError("This SKU no longer exists. Reload the catalog.")
        try:
            if create:
                db.execute(f"INSERT INTO products ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})", data)
            else:
                updates = tuple(f for f in fields if f != "sku")
                db.execute(f"UPDATE products SET {','.join(f + ' = ?' for f in updates)} WHERE sku = ?",
                           tuple(product[f] if f != "updated_at" else timestamp for f in updates) + (product["sku"],))
            db.executemany("INSERT INTO reference_photos (sku, image, created_at) VALUES (?, ?, ?)",
                           [(product["sku"], image, timestamp) for image in images])
        except sqlite3.IntegrityError as error:
            raise ValueError("A different SKU already uses that barcode. Check the catalog before saving.") from error
    return product["sku"]


def list_photos(sku, path=None):
    with connect(path) as db:
        return [dict(row) for row in db.execute(
            "SELECT id, image, created_at FROM reference_photos WHERE sku = ? ORDER BY id", (sku,))]

"""Permanent, append-only local stock ledger with backed-up additive migration."""

from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from uuid import uuid4

from distributionos.catalog import catalog_path, connect as catalog_connect


MAX_STOCK = 2_147_483_647
MOVEMENT_TYPES = ("Opening stock", "Stock In", "Stock Out")


class MigrationBlocked(ValueError):
    """Stop rather than risk changing an unexpected or damaged database."""


def _open(path):
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


@contextmanager
def _readonly(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=15)) as db:
        yield db


def _version(db):
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "inventory_movements" in tables or "inventory_ledger_meta" in tables:
        if not {"inventory_movements", "inventory_ledger_meta"} <= tables:
            raise MigrationBlocked("Unexpected partial ledger found. No upgrade was made. Ask for help before continuing.")
        try:
            rows = db.execute("SELECT version FROM inventory_ledger_meta").fetchall()
            columns = {row[1] for row in db.execute("PRAGMA table_info(inventory_movements)")}
            if len(rows) != 1 or rows[0][0] != 1 or columns != {
                "id", "request_id", "recorded_at", "sku", "product_name", "movement_type", "quantity", "notes"
            }:
                raise MigrationBlocked("Unrecognized ledger version. No upgrade was made. Ask for help before continuing.")
        except sqlite3.DatabaseError as error:
            raise MigrationBlocked("Ledger structure could not be verified. No upgrade was made.") from error
        return 1
    return 0


def _backup(source_path):
    folder = source_path.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = folder / f"{source_path.stem}-before-ledger-{stamp}-{uuid4().hex[:8]}.sqlite3"
    # Separate reader is safe while the migration connection holds a reserved
    # write lock. It snapshots committed data and prevents concurrent changes.
    with _readonly(source_path) as source, closing(sqlite3.connect(target)) as destination:
        source.backup(destination)
        if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise MigrationBlocked("Backup verification failed. Existing data was not changed.")
        for table in ("products", "reference_photos"):
            original = source.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
            copied = destination.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
            if original != copied:
                raise MigrationBlocked("Backup contents did not match. Existing data was not changed.")
    return target


def ensure_ledger(path=None):
    """No DROP, ALTER or catalog row updates. All new DDL commits atomically."""
    path = Path(path) if path is not None else catalog_path()
    if not path.exists():
        with catalog_connect(path):
            pass  # A brand-new local catalog has no pre-existing data to migrate.
    try:
        with _readonly(path) as reader:
            if _version(reader):
                return None
        db = _open(path)
        try:
            db.execute("BEGIN IMMEDIATE")
            if _version(db):  # Another session may have completed migration.
                db.rollback()
                return None
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise MigrationBlocked("Database integrity check failed. No upgrade was made.")
            required = {"sku", "brand", "product_name", "package_size", "units_per_case", "packaging_type", "barcode", "active", "updated_at"}
            if {r[1] for r in db.execute("PRAGMA table_info(products)")} != required:
                raise MigrationBlocked("Unexpected catalog structure. No upgrade was made. Ask for help before continuing.")
            if {r[1] for r in db.execute("PRAGMA table_info(reference_photos)")} != {"id", "sku", "image", "created_at"}:
                raise MigrationBlocked("Unexpected photo structure. No upgrade was made.")
            backup = _backup(path)  # Must complete BEFORE executing any DDL.
            statements = [
                "CREATE TABLE inventory_ledger_meta (version INTEGER NOT NULL, backup_path TEXT NOT NULL)",
                f"""CREATE TABLE inventory_movements (
                    id INTEGER PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE,
                    recorded_at TEXT NOT NULL,
                    sku TEXT NOT NULL REFERENCES products(sku),
                    product_name TEXT NOT NULL,
                    movement_type TEXT NOT NULL CHECK(movement_type IN ('Opening stock','Stock In','Stock Out')),
                    quantity INTEGER NOT NULL CHECK(typeof(quantity) = 'integer' AND quantity >= 0 AND quantity <= {MAX_STOCK}
                        AND (movement_type = 'Opening stock' OR quantity > 0)),
                    notes TEXT NOT NULL DEFAULT ''
                )""",
                "CREATE INDEX inventory_movement_sku ON inventory_movements(sku, id)",
                "CREATE UNIQUE INDEX inventory_one_opening ON inventory_movements(sku) WHERE movement_type = 'Opening stock'",
                """CREATE TRIGGER inventory_validate BEFORE INSERT ON inventory_movements BEGIN
                    SELECT CASE WHEN NEW.movement_type != 'Opening stock' AND NOT EXISTS
                        (SELECT 1 FROM inventory_movements WHERE sku=NEW.sku AND movement_type='Opening stock')
                        THEN RAISE(ABORT, 'Set opening stock first') END;
                    SELECT CASE WHEN NEW.movement_type = 'Opening stock' AND EXISTS
                        (SELECT 1 FROM inventory_movements WHERE sku=NEW.sku)
                        THEN RAISE(ABORT, 'Opening stock already set') END;
                    SELECT CASE WHEN NEW.movement_type = 'Stock Out' AND NEW.quantity > COALESCE(
                        (SELECT SUM(CASE WHEN movement_type='Stock Out' THEN -quantity ELSE quantity END)
                         FROM inventory_movements WHERE sku=NEW.sku), 0)
                        THEN RAISE(ABORT, 'Not enough stock') END;
                END""",
                """CREATE TRIGGER inventory_no_update BEFORE UPDATE ON inventory_movements BEGIN
                    SELECT RAISE(ABORT, 'Movement history cannot be edited'); END""",
                """CREATE TRIGGER inventory_no_delete BEFORE DELETE ON inventory_movements BEGIN
                    SELECT RAISE(ABORT, 'Movement history cannot be deleted'); END""",
            ]
            for statement in statements:
                db.execute(statement)
            db.execute("INSERT INTO inventory_ledger_meta VALUES (1, ?)", (str(backup.resolve()),))
            db.commit()
            return backup
        finally:
            db.close()  # Rolls back the whole upgrade on any failure.
    except (sqlite3.DatabaseError, OSError) as error:
        raise MigrationBlocked(f"Could not safely prepare the ledger: {error}. No catalog rows were changed.") from error


@contextmanager
def connection(path=None):
    ensure_ledger(path)
    db = _open(Path(path) if path is not None else catalog_path())
    try:
        yield db
        db.commit()
    finally:
        db.close()


def current_inventory(path=None):
    with connection(path) as db:
        return [dict(row) for row in db.execute("""
            SELECT p.sku, p.brand, p.product_name, p.package_size, p.units_per_case,
                   p.packaging_type, p.active,
                   COALESCE(SUM(CASE WHEN m.movement_type = 'Stock Out' THEN -m.quantity ELSE m.quantity END), 0) AS current_stock,
                   MAX(CASE WHEN m.movement_type = 'Opening stock' THEN 1 ELSE 0 END) AS opening_set,
                   MAX(m.recorded_at) AS last_updated
            FROM products p LEFT JOIN inventory_movements m ON m.sku = p.sku
            GROUP BY p.sku ORDER BY p.sku
        """)]


def record_movement(sku, movement_type, quantity, notes="", *, request_id=None, path=None):
    if movement_type not in MOVEMENT_TYPES:
        raise ValueError("Choose Opening stock, Stock In or Stock Out.")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or not 0 <= quantity <= MAX_STOCK:
        raise ValueError("Enter a whole number of cases, zero or greater (maximum 2,147,483,647).")
    if movement_type != "Opening stock" and quantity == 0:
        raise ValueError("Stock In and Stock Out quantities must be greater than zero.")
    if not isinstance(notes, str) or len(notes) > 2000:
        raise ValueError("Notes must be text, up to 2,000 characters.")
    notes = notes.strip()
    request_id = request_id or uuid4().hex
    if not isinstance(request_id, str) or len(request_id) > 100:
        raise ValueError("Invalid save request. Refresh and try again.")
    with connection(path) as db:
        db.execute("BEGIN IMMEDIATE")  # Serialize balance check and insert, including across app sessions.
        existing = db.execute("SELECT * FROM inventory_movements WHERE request_id = ?", (request_id,)).fetchone()
        if existing:
            if (existing["sku"], existing["movement_type"], existing["quantity"], existing["notes"]) != (sku, movement_type, quantity, notes):
                raise ValueError("This save request was already used with different values. Refresh and try again.")
            return existing["id"]  # Retried submissions cannot record the same operation twice.
        product = db.execute("SELECT product_name FROM products WHERE sku = ?", (sku,)).fetchone()
        if not product:
            raise ValueError("Select an existing catalog product.")
        opening = db.execute("SELECT 1 FROM inventory_movements WHERE sku = ? AND movement_type='Opening stock'", (sku,)).fetchone()
        if movement_type == "Opening stock" and opening:
            raise ValueError("Opening stock is already saved. Use Stock In or Stock Out for later changes.")
        if movement_type != "Opening stock" and not opening:
            raise ValueError("Save this product's opening stock first (zero is allowed).")
        balance = db.execute("SELECT COALESCE(SUM(CASE WHEN movement_type='Stock Out' THEN -quantity ELSE quantity END), 0) FROM inventory_movements WHERE sku = ?", (sku,)).fetchone()[0]
        next_balance = balance + (-quantity if movement_type == "Stock Out" else quantity)
        if next_balance < 0:
            raise ValueError(f"Not enough stock. Only {balance} cases are available.")
        if next_balance > MAX_STOCK:
            raise ValueError("The resulting stock exceeds the supported maximum.")
        cursor = db.execute("""INSERT INTO inventory_movements
            (request_id, recorded_at, sku, product_name, movement_type, quantity, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)""", (request_id, datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                                               sku, product["product_name"], movement_type, quantity, notes))
        return cursor.lastrowid


def movement_history(path=None):
    with connection(path) as db:
        return [dict(row) for row in db.execute("""SELECT id, recorded_at, sku, product_name, movement_type, quantity, notes
                                                    FROM inventory_movements ORDER BY id DESC""")]


def backup_location(path=None):
    with connection(path) as db:
        return db.execute("SELECT backup_path FROM inventory_ledger_meta").fetchone()[0]

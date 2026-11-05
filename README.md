# DistributionOS AI Case Counter v0.1

A local Python and Streamlit inventory system with a permanent SKU stock ledger. Add your products, enter opening stock, record Stock In and Stock Out, and export current inventory or movement history to CSV for Excel. **AI recognition and image-based counting are not implemented.** The original three-brand test table and image tools remain available separately.

## Permanent inventory: everyday use

1. Open **Product catalog** and add your real products. Every SKU appears automatically on **Inventory dashboard**, including inactive products.
2. On **Inventory dashboard**, select a product and enter the number of cases you have now. Click **Save opening stock**. Do this once for each product; zero is allowed. Until then, its displayed zero is marked **Not set**, not a verified count.
3. Choose **Stock In** for deliveries or **Stock Out** for dispatches. Enter a positive whole number of cases, optionally add a note, and save. Stock Out cannot exceed available stock.
4. The stock table and movement history update immediately. Use **Export inventory CSV** or **Export movement history CSV** to open the saved records in Excel. All products are included in the inventory export.

Current stock = opening stock + Stock In − Stock Out. Quantities are whole cases, not individual bottles. Opening stock cannot be replaced later. To correct a mistake, save a reversing Stock In/Stock Out movement with a clear note; history is retained. Movement dates are recorded automatically in UTC, newest first; backdating is not supported. Each movement keeps the product name used at that time. Reload the page to see changes saved from another session.

Stock is saved to disk on each successful save and survives browser refresh, a new session and app/computer restart. There is no cloud database or paid service. Run on your Mac to keep the database on your Mac. The old manual test quantities are not imported into the ledger because they were temporary brand-level examples, not SKU stock.

## Local data and safe upgrades

The local file `local_data/catalog.sqlite3` holds products, reference photos and the ledger. `local_data/` is ignored by Git. Do not delete or replace it when updating the application. An optional `DISTRIBUTIONOS_DATA_DIR` selects another local data directory; changing that directory opens a different database, not a copy of your old one.

Before the first ledger upgrade, the app locks writes, checks database integrity and the expected catalog structure, and creates a verified backup in `local_data/backups/`. It verifies both database integrity and exact product/photo contents before adding new ledger tables. Existing catalog tables and rows are not rewritten. The new tables, indexes and history-protection triggers are added in one transaction. A failed upgrade rolls back; a failed backup stops the upgrade. Unexpected/partial ledger schemas or damaged files are blocked and require review, never reset automatically. The backup location is shown under **Where is my data saved?** on the dashboard. An empty new database also gets a baseline backup.

For regular backups, stop Streamlit with Control+C and copy the entire `local_data` folder to a safe local drive. The automatic upgrade backup is a snapshot from before the ledger existed; it will not contain later movements. CSV downloads are reports, not complete backups. If an upgrade is blocked, keep the error message and ask for help; do not delete or overwrite data. This development environment cannot inspect or back up your Mac's database remotely.

If you have a Git checkout on your Mac, stop the app, then use these commands from that same checkout (keep its existing local_data folder):

```bash
cd ~/Desktop/DistributionOS-Git
git pull --ff-only origin main
.venv312/bin/python -m pip install -r requirements.txt
.venv312/bin/python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false --server.maxUploadSize 20
```

Use the same project folder where you saved your catalog. If your existing catalog is in `Desktop/DistributionOS`, updating a different checkout will not move its data; ask for help before transferring database files.

## Setup (Linux / macOS, Python 3.12)

Run these commands in a terminal:

```bash
cd /workspace/Distribution-Os
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

The virtual environment keeps this project's packages separate from other Python projects. The folder above is the location in this development environment; on your own computer, use your checkout's path.

## Run

```bash
cd /workspace/Distribution-Os
source .venv/bin/activate
STREAMLIT_BROWSER_GATHER_USAGE_STATS=false python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --server.maxUploadSize 20
```

On the computer running the app, open the local address printed by Streamlit in a browser. Stop it with Ctrl+C. These commands bind the server to the local machine only. This cloud development machine is separate from your laptop; run the project on your own computer for a fully local browser workflow.

## Use and privacy

1. Open **Inventory & image upload** in the sidebar and choose a JPG, JPEG or PNG (maximum 20 MB).
2. View the image preview. No AI analysis runs.
3. Download the inventory CSV template. It contains `image_name`, `product`, `case_count`, `status`, and `count_unit`. Blank counts mean unknown, and status is `not_analyzed`. Without a valid upload, the filename is blank.

Images uploaded on the Inventory & image upload screen are held in the local Streamlit process memory, not written to disk or sent to cloud/AI services. Reference photos explicitly saved on the Product catalog screen are stored in the local catalog file. Downloads go to your browser's download location. Closing the app releases its process memory. Package installation requires Internet access; image preview and CSV generation do not. If the app runs on a remote machine, uploading sends the image to that machine, so use your own computer for private local photos.

## Manual test inventory

The editable table has Product name, Quantity, Unit and Last updated columns. Enter nonnegative whole quantities for Coca-Cola, Sprite and Fanta; product names and the cases unit are fixed. Initial zeros are test defaults, not actual inventory.

On **Inventory & image upload**, click **Save Inventory** to store the test edits in this browser session and set the UTC update time. Click **Export CSV** to download those last saved values. Save again after editing before exporting. This legacy sandbox is temporary and remains separate from the permanent **Inventory dashboard**. A new session, browser refresh or server restart can clear only its test values. Image preview and the separate future AI template remain available.

## SKU catalog and recognition architecture

Use the sidebar **Product catalog** screen to add or edit exact variants with brand, product name, immutable SKU code, package size, bottles/cans per case, packaging type, optional barcode and multiple reference photographs. There is no 100-SKU limit. The catalog starts empty because real warehouse product codes and case packs are not known. The three original manual rows remain a separate test sandbox.

Catalog details/photos and permanent stock movements persist in `local_data/catalog.sqlite3` on your machine (ignored by Git). Only the old three-brand sandbox quantities and manual photo reviews stay temporary. Catalog photos are saved only when you click **Save SKU**. The original image uploader still previews in memory; **Send photo for manual verification** creates a session-only review item, never a detected count.

See [Architecture](docs/ARCHITECTURE.md) for separate generic YOLO case detection, SKU classification, OCR, barcode fusion and unknown review contracts. See [Dataset workflow](docs/DATASET.md) for local annotation validation and export. **No recognition models, training, external uploads or deployment are implemented.** No new dependencies are required.

## Run tests

```bash
python -m unittest discover -s tests -v
```

Tests cover ledger calculations, restart persistence, backup verification, blocked/rolled-back migrations, duplicate saves, concurrent Stock Out, negative-stock prevention, dashboard forms and CSV, plus the legacy manual quantities, image uploads, 120 catalog SKUs, reference photos, manual verification and dataset tooling. Tests use temporary synthetic data, not your actual inventory. Recognition contracts use fake adapters only; they do not demonstrate AI accuracy.

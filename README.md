# DistributionOS AI Case Counter v0.1

A local Python and Streamlit prototype for previewing inventory photos. **AI recognition and case counting are not implemented.** Coca-Cola, Sprite and Fanta are the initial categories. Counts remain blank, never estimated or set to zero.

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

1. Choose a JPG, JPEG or PNG (maximum 20 MB).
2. View the image preview. No AI analysis runs.
3. Download the inventory CSV template. It contains `image_name`, `product`, `case_count`, `status`, and `count_unit`. Blank counts mean unknown, and status is `not_analyzed`. Without a valid upload, the filename is blank.

Images uploaded on the Inventory & image upload screen are held in the local Streamlit process memory, not written to disk or sent to cloud/AI services. Reference photos explicitly saved on the Product catalog screen are stored in the local catalog file. Downloads go to your browser's download location. Closing the app releases its process memory. Package installation requires Internet access; image preview and CSV generation do not. If the app runs on a remote machine, uploading sends the image to that machine, so use your own computer for private local photos.

## Manual test inventory

The editable table has Product name, Quantity, Unit and Last updated columns. Enter nonnegative whole quantities for Coca-Cola, Sprite and Fanta; product names and the cases unit are fixed. Initial zeros are test defaults, not actual inventory.

Click **Save Inventory** to store the edits in this browser session and set the UTC update time. Click **Export CSV** to download the last saved values. Save again after editing before exporting. Data is temporary: a new session, browser refresh or server restart can clear it. No database or real inventory is connected. Image preview and the separate future AI template remain available.

## SKU catalog and recognition architecture

Use the sidebar **Product catalog** screen to add or edit exact variants with brand, product name, immutable SKU code, package size, bottles/cans per case, packaging type, optional barcode and multiple reference photographs. There is no 100-SKU limit. The catalog starts empty because real warehouse product codes and case packs are not known. The three original manual rows remain a separate test sandbox.

Catalog details/photos persist only in `local_data/catalog.sqlite3` on your machine (ignored by Git); quantities and manual review stay temporary session data. Catalog photos are saved only when you click **Save SKU**. The original image uploader still previews in memory; **Send photo for manual verification** creates a session-only review item, never a detected count.

See [Architecture](docs/ARCHITECTURE.md) for separate generic YOLO case detection, SKU classification, OCR, barcode fusion and unknown review contracts. See [Dataset workflow](docs/DATASET.md) for local annotation validation and export. **No recognition models, training, external uploads or deployment are implemented.** No new dependencies are required.

## Run tests

```bash
python -m unittest discover -s tests -v
```

Tests cover the dashboard, manual quantities and CSV, valid/invalid image uploads, 120 catalog SKUs, reference photos, catalog screens, manual verification and dataset validation/export. Recognition contracts use synthetic evidence and fake adapters only; they do not demonstrate AI accuracy.

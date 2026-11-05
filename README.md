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

Uploaded images are held in the local Streamlit process memory, not written to disk or sent to cloud/AI services. Downloads go to your browser's download location. Closing the app releases its process memory. Package installation requires Internet access; image preview and CSV generation do not. If the app runs on a remote machine, uploading sends the image to that machine, so use your own computer for private local photos.

## Validate

```bash
python -m unittest discover -s tests -v
```

Tests cover the dashboard, CSV structure, and valid/invalid image upload paths. They do not test AI detection because none exists yet.

"""Local image preview and inventory export scaffold; no AI detection yet."""

import warnings
from datetime import datetime, timezone
from numbers import Integral

from PIL import Image, ImageOps, UnidentifiedImageError
import streamlit as st

from distributionos.recognition import make_review_item
from distributionos.screens import catalog_screen, dataset_screen, review_screen
from distributionos.inventory_screen import inventory_screen
from distributionos.exports import csv_bytes

PRODUCTS = ("Coca-Cola", "Sprite", "Fanta")


def manual_rows():
    return [{"Product name": product, "Quantity": 0, "Unit": "cases", "Last updated": ""}
            for product in PRODUCTS]


def save_manual_inventory(rows):
    if len(rows) != len(PRODUCTS):
        raise ValueError("Keep the three default product rows.")
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    saved = []
    for product, row in zip(PRODUCTS, rows):
        quantity = row.get("Quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, Integral) or quantity < 0:
            raise ValueError("Enter a whole number of cases, zero or greater, for every product.")
        saved.append({"Product name": product, "Quantity": int(quantity),
                      "Unit": "cases", "Last updated": timestamp})
    return saved


def manual_inventory_section():
    st.subheader("Manual test inventory")
    st.caption("Temporary session data only. Save stores your edits for this session; it does not change real inventory. Refreshing or closing the session may clear it. Times are UTC.")
    if "manual_inventory" not in st.session_state:
        st.session_state.manual_inventory = manual_rows()
        st.session_state.manual_inventory_saved = False
    with st.form("manual_inventory_form"):
        edited = st.data_editor(
            st.session_state.manual_inventory, key="manual_inventory_editor",
            hide_index=True, num_rows="fixed", width="stretch",
            disabled=["Product name", "Unit", "Last updated"],
            column_config={"Quantity": st.column_config.NumberColumn(
                "Quantity", min_value=0, step=1, format="%d", required=True)},
        )
        if st.form_submit_button("Save Inventory"):
            try:
                st.session_state.manual_inventory = save_manual_inventory(edited)
                st.session_state.manual_inventory_saved = True
                st.rerun()
            except ValueError as error:
                st.error(str(error))
    if st.session_state.manual_inventory_saved:
        st.success("Inventory saved in this temporary session. Export CSV uses the last saved values.")
    else:
        st.caption("Starting quantities are zero for testing. Enter your quantities and click Save Inventory before exporting.")
    st.download_button("Export CSV", data=inventory_csv(st.session_state.manual_inventory),
                       file_name="distributionos_manual_inventory.csv", mime="text/csv",
                       disabled=not st.session_state.manual_inventory_saved)


def inventory_rows(image_name=""):
    return [
        {"image_name": image_name, "product": product, "case_count": "",
         "status": "not_analyzed", "count_unit": "cases"}
        for product in PRODUCTS
    ]


def inventory_csv(rows):
    return csv_bytes(rows)


def main():
    st.set_page_config(page_title="DistributionOS | AI Case Counter", page_icon="📦", layout="wide")
    st.title("DistributionOS")
    st.caption("Permanent inventory ledger · Local storage · AI recognition not implemented")
    page = st.sidebar.radio("Screen", ["Inventory dashboard", "Product catalog", "Inventory & image upload", "Manual verification", "Dataset workflow"])
    if page != "Inventory & image upload":
        {"Inventory dashboard": inventory_screen, "Product catalog": catalog_screen, "Manual verification": review_screen,
         "Dataset workflow": dataset_screen}[page]()
        return
    st.info("Manual test inventory and image preview. AI recognition and case counting are not implemented yet.")
    st.caption("The three categories below are legacy manual test rows, not recognized SKUs. Manage real variants on the Product catalog screen.")
    st.subheader("Product dashboard")
    for column, product in zip(st.columns(3), PRODUCTS):
        with column:
            st.metric(product, "—")
            st.caption("Not analyzed · case count unavailable")

    manual_inventory_section()

    st.subheader("Upload an image")
    st.caption("JPG, JPEG or PNG · up to 20 MB. Images stay in this local app's memory; they are not saved or sent to an AI service.")
    uploaded = st.file_uploader("Choose an inventory photo", type=["jpg", "jpeg", "png"])
    image_name = ""
    if uploaded is not None:
        try:
            if uploaded.size > 20 * 1024 * 1024:
                raise ValueError("Please choose an image smaller than 20 MB.")
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(uploaded) as source:
                    if source.format not in {"JPEG", "PNG"}:
                        raise ValueError("The file must contain a JPEG or PNG image.")
                    source.load()
                    preview = ImageOps.exif_transpose(source).convert("RGB")
            st.image(preview, caption=uploaded.name, width="stretch")
            image_name = uploaded.name
            st.success("Image preview ready. No detection has been run.")
            if st.button("Send photo for manual verification"):
                st.session_state.setdefault("review_queue", []).append(make_review_item(preview, uploaded.name))
                st.success("Photo added to the temporary queue. Open Manual verification in the sidebar.")
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            st.error("This image could not be opened. Use a valid JPG, JPEG or PNG under 20 MB with reasonable dimensions.")

    st.subheader("Results · future AI detection")
    rows = inventory_rows(image_name)
    st.table(rows)
    st.caption("Blank counts mean unavailable, not zero. This template is ready for future detection results.")
    st.download_button("Download inventory CSV template", data=inventory_csv(rows),
                       file_name="distributionos_inventory_template.csv", mime="text/csv")
    st.caption("The CSV contains category rows and status only; image pixels are never included.")


if __name__ == "__main__":
    main()

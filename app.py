"""Local image preview and inventory export scaffold; no AI detection yet."""

import csv
import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError
import streamlit as st

PRODUCTS = ("Coca-Cola", "Sprite", "Fanta")


def inventory_rows(image_name=""):
    return [
        {"image_name": image_name, "product": product, "case_count": "",
         "status": "not_analyzed", "count_unit": "cases"}
        for product in PRODUCTS
    ]


def inventory_csv(rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    # Image filenames are untrusted spreadsheet input.
    writer.writerows({key: "'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else value
                      for key, value in row.items()} for row in rows)
    return output.getvalue().encode("utf-8")


def main():
    st.set_page_config(page_title="DistributionOS | AI Case Counter", page_icon="📦", layout="wide")
    st.title("DistributionOS")
    st.caption("AI Case Counter · v0.1 · Local prototype")
    st.info("Image preview and CSV template only. AI recognition and case counting are not implemented yet.")
    st.subheader("Product dashboard")
    for column, product in zip(st.columns(3), PRODUCTS):
        with column:
            st.metric(product, "—")
            st.caption("Not analyzed · case count unavailable")

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

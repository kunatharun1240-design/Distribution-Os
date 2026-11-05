"""Streamlit screens for the local catalog and temporary verification queue."""

from datetime import datetime, timezone
import io
import sqlite3

from PIL import Image
import streamlit as st

from distributionos.catalog import list_photos, list_products, save_product


def catalog_screen():
    st.header("Product catalog")
    st.caption("SKU means one exact sellable variant: product + size + case pack + packaging. Catalog changes never update inventory.")
    st.info("Catalog details and reference photographs are saved on this machine in local_data/catalog.sqlite3. No model is trained here.")
    try:
        products = list_products()
        st.metric("Catalog SKUs", len(products))
        query = st.text_input("Search SKU, brand or product").strip().casefold()
        filtered = [p for p in products if query in " ".join(str(p[k]) for k in ("sku", "brand", "product_name")).casefold()]
        if filtered:
            st.dataframe(filtered, hide_index=True, width="stretch")
        else:
            st.write("No matching SKUs. Add your actual warehouse variants below; no sample SKU identities are assumed.")
        choices = ["Add new SKU"] + [p["sku"] for p in products]
        selected = st.selectbox("Add or edit a SKU", choices)
        product = next((p for p in products if p["sku"] == selected), {})
        with st.form("catalog_" + selected, clear_on_submit=False):
            sku = st.text_input("SKU / product code", value=product.get("sku", ""), disabled=bool(product))
            brand = st.text_input("Brand", value=product.get("brand", ""))
            name = st.text_input("Product name", value=product.get("product_name", ""))
            size = st.text_input("Package size", value=product.get("package_size", ""), placeholder="e.g. 500 mL per bottle")
            units = st.number_input("Bottles/cans per case", min_value=1, step=1, value=product.get("units_per_case", 1))
            packaging = st.text_input("Packaging type", value=product.get("packaging_type", ""), placeholder="e.g. PET bottles in shrink-wrapped case")
            barcode = st.text_input("Barcode (optional; preserve leading zeros)", value=product.get("barcode") or "")
            active = st.checkbox("Active SKU", value=bool(product.get("active", True)))
            photos = st.file_uploader("Reference product photographs (optional, up to 10 per save)",
                                     type=["jpg", "jpeg", "png"], accept_multiple_files=True, key="refs_" + selected)
            st.caption("Photographs are saved only when you click Save SKU. Existing reference photographs are retained. Upload different angles and readable package details.")
            if st.form_submit_button("Save SKU"):
                try:
                    saved = save_product({"sku": sku, "brand": brand, "product_name": name,
                                          "package_size": size, "units_per_case": int(units),
                                          "packaging_type": packaging, "barcode": barcode, "active": active},
                                         [photo.getvalue() for photo in photos], create=not bool(product))
                    st.session_state.catalog_notice = f"Saved SKU {saved} locally. Inventory unchanged."
                    st.rerun()
                except (ValueError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
                    st.error(f"Could not save SKU: {error}")
        if "catalog_notice" in st.session_state:
            st.success(st.session_state.pop("catalog_notice"))
        if product:
            st.subheader("Saved reference photographs")
            for photo in list_photos(product["sku"]):
                st.image(io.BytesIO(photo["image"]), caption=f"Reference {photo['id']} · {photo['created_at']}", width=240)
        st.caption("SKU codes are immutable. Add a new SKU when case pack or package identity changes; deactivate the old SKU to retain its history. Back up local_data while the app is stopped.")
    except (sqlite3.Error, OSError) as error:
        st.error(f"Local catalog unavailable: {error}. Your image preview and manual session inventory remain separate.")


def review_screen():
    st.header("Manual verification")
    st.info("Session-only review queue. Uploaded whole-photo reviews are not detected cases and do not change inventory. No AI model has run.")
    queue = st.session_state.setdefault("review_queue", [])
    if not queue:
        st.write("Open Inventory & image upload, preview a photo, then choose Send photo for manual verification.")
        return
    products = list_products(active_only=True)
    skus = [p["sku"] for p in products]
    for item in queue:
        with st.expander(f"{item['image_name']} · {item['status']}", expanded=item["status"] == "pending"):
            st.image(item["image"], width=360)
            st.write(item["reason"])
            st.caption("Assign a SKU only if this review image represents a single unambiguous variant. Otherwise leave it unknown.")
            with st.form("review_" + item["id"]):
                choice = st.selectbox("Verified SKU", ["Unknown / mixed / unreadable"] + skus,
                                      index=skus.index(item["sku"]) + 1 if item["sku"] in skus else 0)
                if st.form_submit_button("Save verification"):
                    item["sku"] = None if choice == "Unknown / mixed / unreadable" else choice
                    item["status"] = "unknown" if item["sku"] is None else "verified"
                    item["reviewed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    st.rerun()
            if item["reviewed_at"]:
                st.caption(f"Saved review: {item['sku'] or 'Unknown'} · {item['reviewed_at']}")


def dataset_screen():
    st.header("Dataset preparation")
    st.warning("No warehouse dataset or trained SKU model exists yet. Collect and label real images before training.")
    st.markdown("""
1. Add every actual variant to **Product catalog**, with a unique SKU code and reference photographs.
2. Collect warehouse scenes across lighting, angles, occlusion, stacks and similar packaging. Include unknown products and empty scenes.
3. Draw one bounding box per visible case using a local annotation tool. Use generic `case` for detection and a separate catalog SKU (or unknown) for classification.
4. Record capture groups and train/validation/test splits, keeping the same scene/session and reference-photo duplicates in one split.
5. Validate annotations and export generic YOLO labels plus SKU crop labels using the local dataset tool.

See `docs/DATASET.md`, `dataset_templates/`, and `docs/ARCHITECTURE.md` for formats and commands. Training is intentionally not implemented.
""")

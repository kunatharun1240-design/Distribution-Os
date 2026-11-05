"""Simple warehouse inventory dashboard, separate from the old test sandbox."""

import sqlite3
from uuid import uuid4

import streamlit as st

from distributionos.catalog import catalog_path
from distributionos.exports import csv_bytes
from distributionos.ledger import MAX_STOCK, MigrationBlocked, backup_location, current_inventory, movement_history, record_movement


INVENTORY_FIELDS = ["SKU", "Brand", "Product", "Package size", "Bottles/cans per case", "Current stock", "Unit", "Opening stock", "Status", "Last updated (UTC)"]
HISTORY_FIELDS = ["Movement ID", "Date (UTC)", "SKU", "Product", "Movement type", "Quantity", "Unit", "Notes"]


def inventory_export_rows(products):
    return [{"SKU": p["sku"], "Brand": p["brand"], "Product": p["product_name"],
             "Package size": p["package_size"], "Bottles/cans per case": p["units_per_case"],
             "Current stock": p["current_stock"], "Unit": "cases",
             "Opening stock": "Saved" if p["opening_set"] else "Not set",
             "Status": "Active" if p["active"] else "Inactive",
             "Last updated (UTC)": p["last_updated"] or ""} for p in products]


def history_export_rows(movements):
    return [{"Movement ID": m["id"], "Date (UTC)": m["recorded_at"], "SKU": m["sku"],
             "Product": m["product_name"], "Movement type": m["movement_type"],
             "Quantity": m["quantity"], "Unit": "cases", "Notes": m["notes"]} for m in movements]


def inventory_screen():
    st.header("Inventory dashboard")
    st.caption("Your saved warehouse stock. Add products in Product catalog, set opening stock once, then record Stock In or Stock Out.")
    try:
        products = current_inventory()
        if "ledger_notice" in st.session_state:
            st.success(st.session_state.pop("ledger_notice"))
        with st.expander("Where is my data saved?"):
            st.write("Products, photographs and stock movements are saved on this computer, even after closing or restarting the app. Keep this data folder when updating the code.")
            st.code(str(catalog_path().resolve()))
            st.write("A verified backup was created before the ledger tables were added:")
            st.code(backup_location())
            st.caption("For ongoing backups, stop the app and copy the entire local_data folder to a safe local drive. CSV files are reports, not full database backups.")
        if not products:
            st.info("No products yet. Open Product catalog in the sidebar and add your first product. Then return here to enter its opening stock.")
            return
        missing = sum(not p["opening_set"] for p in products)
        for column, label, value in zip(st.columns(3), ("Products", "Total cases", "Need opening stock"),
                                         (len(products), sum(p["current_stock"] for p in products), missing)):
            column.metric(label, value)
        if missing:
            st.info(f"{missing} product(s) need opening stock. Their displayed zero is a starting placeholder until you save the actual opening quantity.")
        rows = inventory_export_rows(products)
        st.subheader("Current stock")
        st.dataframe(rows, hide_index=True, width="stretch")
        st.download_button("Export inventory CSV", csv_bytes(rows, INVENTORY_FIELDS),
                           file_name="distributionos_current_inventory.csv", mime="text/csv")
        st.caption("CSV files open in Excel. Inactive products are included so their stock remains visible. Refresh this page to see movements saved by another session.")

        st.subheader("Update stock")
        selected = st.selectbox("Product", [p["sku"] for p in products],
                                format_func=lambda sku: next(f"{p['product_name']} · {p['package_size']} · {p['units_per_case']}/case · {sku}" for p in products if p["sku"] == sku))
        product = next(p for p in products if p["sku"] == selected)
        st.write(f"Available now: **{product['current_stock']} cases**")
        if not product["active"]:
            st.caption("This product is inactive in the catalog. Its stock and history are retained; any movement you save still changes its balance.")
        if not product["opening_set"]:
            action = "Opening stock"
            st.write("**Set opening stock** — enter the number of cases you have now. Zero is allowed. You can do this once per product.")
        else:
            action = st.radio("Movement type", ["Stock In", "Stock Out"], horizontal=True)
            st.caption("Stock In adds cases. Stock Out removes cases. Saved movements stay in history; record a reversing movement with a note to correct a mistake.")
        key = f"ledger_request_{selected}_{action}"
        st.session_state.setdefault(key, uuid4().hex)
        with st.form(f"ledger_form_{selected}_{action}", clear_on_submit=True):
            quantity = st.number_input("Quantity (cases)", min_value=0 if action == "Opening stock" else 1,
                                       max_value=MAX_STOCK, value=0 if action == "Opening stock" else 1, step=1)
            notes = st.text_input("Notes (optional)", max_chars=2000)
            if st.form_submit_button("Save opening stock" if action == "Opening stock" else f"Save {action}"):
                try:
                    record_movement(selected, action, int(quantity), notes, request_id=st.session_state[key])
                    st.session_state[key] = uuid4().hex
                    st.session_state.ledger_notice = f"{action} saved: {quantity} cases for {product['product_name']}. Your stock is saved on this computer."
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))

        st.subheader("Movement history")
        history = history_export_rows(movement_history())
        if history:
            st.dataframe(history, hide_index=True, width="stretch")
            st.download_button("Export movement history CSV", csv_bytes(history, HISTORY_FIELDS),
                               file_name="distributionos_movement_history.csv", mime="text/csv")
            st.caption("Newest saved movements first. Dates are recorded automatically in UTC. Product names reflect the name at the time of each movement.")
        else:
            st.write("No movements yet. Save an opening stock quantity to begin.")
    except MigrationBlocked as error:
        st.error(f"Inventory upgrade stopped: {error}")
        st.warning("Do not replace or delete your local data. Ask for help with this message before trying a migration.")
    except (sqlite3.Error, OSError) as error:
        st.error(f"Could not read or save local inventory: {error}. Check disk space and access to the data folder, then retry.")

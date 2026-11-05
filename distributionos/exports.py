"""CSV downloads readable by Excel, with spreadsheet formula protection."""

import csv
import io


def csv_bytes(rows, fieldnames=None):
    rows = list(rows)
    fields = fieldnames or (list(rows[0]) if rows else [])
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows({key: "'" + value if isinstance(value, str) and value.startswith(
        ("=", "+", "-", "@", "\t", "\r", "\n")) else value for key, value in row.items()} for row in rows)
    return output.getvalue().encode("utf-8")

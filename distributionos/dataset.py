"""Local annotation validation and export. Never downloads or trains a model."""

import argparse
from collections import Counter
import json
import math
from pathlib import Path

from PIL import Image

from distributionos.catalog import list_products


SPLITS = {"train", "val", "test"}


def validate_manifest(manifest, image_root, products):
    root = Path(image_root).resolve()
    catalog = {p["sku"] for p in products}  # Inactive SKUs retain historical labels.
    records, errors, groups, seen, seen_paths = [], [], {}, set(), set()
    counts = Counter()
    with Path(manifest).open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                image_id = row["image_id"]
                if not isinstance(image_id, str) or not image_id or image_id in seen:
                    raise ValueError("image_id must be a unique nonempty string")
                seen.add(image_id)
                group, split = row["capture_group"], row["split"]
                if not isinstance(group, str) or not group or split not in SPLITS:
                    raise ValueError("capture_group and train/val/test split required")
                if group in groups and groups[group] != split:
                    raise ValueError("capture group leaks across dataset splits")
                groups[group] = split
                relative = Path(row["image"])
                path = (root / relative).resolve()
                if relative.is_absolute() or not path.is_relative_to(root):
                    raise ValueError("image must be inside the dataset image root")
                if path in seen_paths:
                    raise ValueError("same image path appears more than once")
                seen_paths.add(path)
                with Image.open(path) as image:
                    image.verify()
                with Image.open(path) as image:
                    if image.getexif().get(274, 1) != 1:
                        raise ValueError("normalize EXIF orientation before annotation")
                    width, height = image.size
                if row.get("width") != width or row.get("height") != height:
                    raise ValueError("manifest dimensions differ from the source image")
                if row.get("reviewed") is not True:
                    raise ValueError("annotation must be manually reviewed before export")
                if not isinstance(row["cases"], list):
                    raise ValueError("cases must be a list (empty is allowed)")
                for case in row["cases"]:
                    box = case["bbox_xyxy"]
                    if len(box) != 4 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in box):
                        raise ValueError("bbox_xyxy requires four finite pixel coordinates")
                    x1, y1, x2, y2 = box
                    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
                        raise ValueError("case bounding box is outside image bounds")
                    sku = case["sku"]
                    if sku is not None and sku not in catalog:
                        raise ValueError(f"unknown catalog SKU {sku}; use null for unknown")
                    if not isinstance(case.get("ocr_text", ""), str):
                        raise ValueError("ocr_text must be text")
                    if not isinstance(case.get("barcodes", []), list) or any(not isinstance(b, str) for b in case.get("barcodes", [])):
                        raise ValueError("barcodes must be strings to preserve leading zeros")
                    counts[(split, sku)] += 1
                records.append(row)
            except (ValueError, KeyError, TypeError, OSError) as error:
                errors.append(f"Line {line_number}: {error}")
    if not records and not errors:
        errors.append("No reviewed image records found.")
    if errors:
        raise ValueError("\n".join(errors))
    warnings = []
    for sku in sorted(catalog):
        for split in sorted(SPLITS):
            if not counts[(split, sku)]:
                warnings.append(f"{sku}: no labeled cases in {split}")
    return records, warnings


def export_dataset(records, image_root, products, output):
    """New directory only: preserve originals and every existing export."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    root = Path(image_root).resolve()
    # SKU strings are the classifier labels; no hardcoded three-brand class IDs.
    vocabulary = sorted(p["sku"] for p in products)
    (output / "sku_vocabulary.json").write_text(json.dumps(vocabulary, indent=2), encoding="utf-8")
    (output / "catalog_snapshot.json").write_text(json.dumps(products, indent=2), encoding="utf-8")
    (output / "data.yaml").write_text(f"path: {json.dumps(str(output.resolve()))}\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: case\n", encoding="utf-8")
    crop_records = []
    for split in sorted(SPLITS):
        for folder in ("images", "labels", "crops"):
            (output / folder / split).mkdir(parents=True, exist_ok=True)
    for index, row in enumerate(records):
        split = row["split"]
        with Image.open(root / row["image"]) as source:
            image = source.convert("RGB")
            image.save(output / "images" / split / f"{index:06d}.jpg")
            labels = []
            for case_index, case in enumerate(row["cases"]):
                x1, y1, x2, y2 = case["bbox_xyxy"]
                labels.append(f"0 {(x1+x2)/2/image.width:.8f} {(y1+y2)/2/image.height:.8f} {(x2-x1)/image.width:.8f} {(y2-y1)/image.height:.8f}")
                relative = f"crops/{split}/{index:06d}_{case_index:04d}.jpg"
                image.crop((math.floor(x1), math.floor(y1), math.ceil(x2), math.ceil(y2))).save(output / relative)
                crop_records.append({"crop": relative, "image_id": row["image_id"], "capture_group": row["capture_group"],
                                     "split": split, "sku": case["sku"], "ocr_text": case.get("ocr_text", ""),
                                     "barcodes": case.get("barcodes", [])})
            (output / "labels" / split / f"{index:06d}.txt").write_text("\n".join(labels), encoding="utf-8")
    (output / "classification.jsonl").write_text("".join(json.dumps(r) + "\n" for r in crop_records), encoding="utf-8")
    (output / "annotations.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest")
    parser.add_argument("--images", required=True)
    parser.add_argument("--catalog", help="Optional local catalog SQLite path")
    parser.add_argument("--export", help="Create a new export directory; never overwrite an existing one")
    args = parser.parse_args()
    try:
        products = list_products(args.catalog)
        records, warnings = validate_manifest(args.manifest, args.images, products)
        print(f"Validated {len(records)} reviewed images, {sum(len(r['cases']) for r in records)} case boxes.")
        for warning in warnings:
            print("DATA COVERAGE WARNING:", warning)
        if args.export:
            export_dataset(records, args.images, products, args.export)
            print("Exported local annotations and crops; no training performed.")
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()

# Local warehouse dataset and annotation workflow

Do not train yet. We have no actual labeled warehouse images. The example manifest contains placeholders, not warehouse evidence, and is expected to fail validation until replaced.

## Collect and identify every variant

Use Product catalog to record all 50–60 actual variants (and future additions) with stable SKU codes. Photograph front, sides, top, outer-case branding, package size, case pack and readable barcodes. Reference photos alone are not a warehouse test set. Include similar variants of the same brand, reflective wrap, stacked cases, partial occlusion, difficult lighting and viewpoints. Capture unknown brands, confusing non-case objects and scenes containing no cases.

Create local `datasets/raw/` for warehouse images and `datasets/annotations.jsonl` for labels. These paths are ignored by Git. Do not commit private photos, catalog databases, datasets or trained weights. Respect privacy and obtain permission for warehouse photography. Keep original images intact; save EXIF-oriented, upright annotation copies without GPS metadata. Coordinates refer to those copies, never an auto-rotated preview of a differently oriented source.

## Annotate and review

Use a local annotation tool such as LabelImg or a locally hosted CVAT/Label Studio instance (optional tools, not installed here). Configure **one detector class, case**. Draw pixel `bbox_xyxy` boxes around every visible case, not each bottle. Store the exact SKU as a separate crop classification label. Use JSON `null` for unknown, mixed or unreadable cases; do not invent a brand-based SKU or use unknown as a known classifier class. Unknown crops are retained for rejection evaluation, excluded from supervised known-SKU classification training. Empty `cases` lists are valid reviewed negative scenes.

Copy the format in `dataset_templates/annotations.example.jsonl`. Each line is one image record with unique image_id, image path relative to raw/, actual width and height, capture_group, split (`train`, `val`, `test`), reviewed boolean and cases. A case has bbox_xyxy, sku, optional ocr_text, optional barcodes (strings), and optional occluded metadata. Transcribe only visible text; missing barcode means `[]`. A second person should review ambiguous SKU labels against physical packaging, photographs and case-pack details. Set reviewed=true only after checking the actual image and all boxes. UI photo verification is not a substitute for bounding-box annotation.

Split by capture session/scene/stack before augmentation, e.g. target 70/15/15 while ensuring enough independent groups for each SKU. Keep near duplicates, reference-photo derivatives and crops from the same scene in the same split. The validator checks group and path overlap, but cannot detect perceptual duplicates or decide that labels are correct; inspect those manually. Avoid leakage from reference views into held-out evaluation. Collect multiple independent examples of every SKU in all splits; coverage warnings are not permission to train. There is no magic minimum sample count—measure validation performance, especially for look-alike variants and unknowns.

## Validate and export (no training)

Activate your existing Python environment. From the project directory:

```bash
python -m distributionos.dataset datasets/annotations.jsonl --images datasets/raw
python -m distributionos.dataset datasets/annotations.jsonl --images datasets/raw --export datasets/export-001
```

Optional `--catalog /path/to/catalog.sqlite3` selects a catalog file. Validation fails on missing images, bad dimensions, unsafe paths, duplicate IDs/paths, cross-split capture groups, invalid boxes, unreviewed annotations or SKUs absent from the catalog. Missing SKU/split coverage is printed explicitly. Exports refuse to overwrite an existing directory. Re-run with a new export name after corrections; do not edit frozen exports in place.

Outputs:

- `images/{train,val,test}` and `labels/{train,val,test}`: copied/re-encoded scenes with normalized YOLO boxes and **class 0 = case** only. `data.yaml` records the export's absolute local path; update that path if you move the export to another computer.
- `classification.jsonl` and `crops/`: individual crop images, exact SKU string or null, original image/group IDs, text and barcode labels.
- `sku_vocabulary.json`: every catalog SKU, with no fixed class count. Future trainers must freeze this mapping with the model; never reconstruct class indices from a changed catalog.
- `catalog_snapshot.json` and `annotations.jsonl`: metadata and original labels for reproducibility. Inactive SKUs remain available for historical annotations; inference excludes them.

Do not train directly from UI reference thumbnails; they are resized catalog aids. Use full-resolution upright dataset images. Keep catalog snapshots and export versions together; reviewed training examples must be explicitly approved, not silently generated from model predictions. Future evaluation should report generic case detection, per-SKU classification/confusion, unknown rejection, review rate and final case-count accuracy separately.

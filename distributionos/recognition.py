"""Testable recognition contracts, not installed models or recognition claims."""

from dataclasses import dataclass, field
from math import isfinite
from typing import Protocol
from uuid import uuid4

from PIL import Image


@dataclass(frozen=True)
class Detection:
    box: tuple[int, int, int, int]  # Pixel xyxy in the EXIF-oriented source image.
    confidence: float


@dataclass(frozen=True)
class Evidence:
    sku_scores: dict[str, float] = field(default_factory=dict)
    ocr_text: str = ""
    barcodes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Decision:
    sku: str | None
    status: str
    reason: str
    candidate_sku: str | None = None


class CaseDetector(Protocol):
    """Future YOLO adapter: one generic `case` class, independent of SKU count."""
    def detect(self, image: Image.Image) -> list[Detection]: ...


class SKUClassifier(Protocol):
    """Future crop classifier: calibrated scores keyed by stable SKU code."""
    def classify(self, crop: Image.Image) -> dict[str, float]: ...


class TextReader(Protocol):
    def read(self, crop: Image.Image) -> str: ...


class BarcodeReader(Protocol):
    def decode(self, crop: Image.Image) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class FusionPolicy:
    auto_accept: bool = False  # Enable only after warehouse validation/calibration.
    classifier_threshold: float = 0.90
    classifier_margin: float = 0.15
    detector_threshold: float = 0.50


def fuse(evidence, products, policy=FusionPolicy()):
    catalog = {p["sku"]: p for p in products if p.get("active", True)}
    if not catalog:
        return Decision(None, "needs_review", "No active catalog SKUs.")
    scores = evidence.sku_scores
    if any(not isfinite(v) or not 0 <= v <= 1 for v in scores.values()):
        return Decision(None, "needs_review", "Invalid classifier scores.")
    if any(sku not in catalog for sku in scores):
        return Decision(None, "needs_review", "Classifier vocabulary differs from active catalog.")
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    candidate, score = ranked[0] if ranked else (None, 0)
    margin = score - (ranked[1][1] if len(ranked) > 1 else 0)
    barcode_map = {p["barcode"]: p["sku"] for p in catalog.values() if p.get("barcode")}
    matched = {barcode_map[b] for b in evidence.barcodes if b in barcode_map}
    if any(b not in barcode_map for b in evidence.barcodes):
        return Decision(None, "needs_review", "Unknown barcode; check inner-unit versus outer-case code.", candidate)
    if len(matched) > 1:
        return Decision(None, "needs_review", "Multiple SKU barcodes in one case crop.", candidate)
    barcode_sku = next(iter(matched), None)
    if barcode_sku and candidate and barcode_sku != candidate:
        return Decision(None, "needs_review", "Barcode and classifier disagree.", candidate)
    # OCR is supporting evidence, never a SKU guess from a brand name alone.
    text = evidence.ocr_text.casefold()
    text_matches = {sku for sku, p in catalog.items()
                    if p["product_name"].casefold() in text and p["package_size"].casefold() in text}
    candidate = barcode_sku or candidate
    if text_matches and (len(text_matches) > 1 or candidate not in text_matches):
        return Decision(None, "needs_review", "Packaging text is ambiguous or conflicts with other evidence.", candidate)
    if not policy.auto_accept:
        return Decision(None, "needs_review", "Automatic acceptance disabled pending warehouse validation.", candidate)
    if barcode_sku:
        return Decision(barcode_sku, "accepted", "Exact catalog barcode with no conflicting evidence.", barcode_sku)
    if candidate and score >= policy.classifier_threshold and margin >= policy.classifier_margin and text_matches == {candidate}:
        return Decision(candidate, "accepted", "Classifier and product/size text agree.", candidate)
    return Decision(None, "needs_review", "Unknown or insufficient SKU evidence.", candidate)


def run_pipeline(image, products, detector, classifier, text_reader, barcode_reader, policy=FusionPolicy()):
    """Dependency-injected future orchestration; never called by the current UI."""
    results = []
    for detection in detector.detect(image):
        x1, y1, x2, y2 = detection.box
        if not (0 <= x1 < x2 <= image.width and 0 <= y1 < y2 <= image.height):
            raise ValueError("Detector returned an invalid case box.")
        crop = image.crop(detection.box)
        evidence = Evidence(classifier.classify(crop), text_reader.read(crop), barcode_reader.decode(crop))
        decision = fuse(evidence, products, policy)
        if not isfinite(detection.confidence) or not 0 <= detection.confidence <= 1 or detection.confidence < policy.detector_threshold:
            decision = Decision(None, "needs_review", "Low or invalid case detection confidence.", decision.candidate_sku)
        results.append({"id": uuid4().hex, "detection": detection, "evidence": evidence,
                        "decision": decision, "crop": crop})
    return results


def make_review_item(image, image_name, reason="User requested verification; no AI has run."):
    """A whole-image review is a placeholder, never an inferred case count."""
    return {"id": uuid4().hex, "image": image.copy(), "image_name": image_name,
            "reason": reason, "status": "pending", "sku": None, "reviewed_at": ""}

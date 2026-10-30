"""Phase 1: Data cleaning pipeline for Thelawala Search Engine.

Reads catalog.csv and inventory.csv, produces clean_catalog.jsonl with all
original SKUs preserved. Detects suspected paise prices using the
category-median 10x-100x rule and records all candidates for manual review.

No corrections are applied automatically. Raw prices are preserved.

The evaluation date is an explicit parameter; when omitted it defaults to
the original hard-coded value for backward compatibility but can be
overridden in tests.
"""

from __future__ import annotations

import csv
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path

PAISE_RATIO_LOW = 10.0
PAISE_RATIO_HIGH = 100.0

UNIT_CONVERSIONS = {
    "kg": ("kg", 1.0),
    "g": ("kg", 0.001),
    "ltr": ("L", 1.0),
    "l": ("L", 1.0),
    "ml": ("L", 0.001),
    "pcs": ("count", 1.0),
    "pack": ("count", 1.0),
    "nos": ("count", 1.0),
}

UNIT_ALIASES = {
    "gm": "g",
    "ltr": "l",
    "pack": "pcs",
    "nos": "pcs",
}

SUPPORTED_UNITS = set(UNIT_CONVERSIONS.keys()) | set(UNIT_ALIASES.keys())


def normalize_name(name: str) -> dict[str, str]:
    """Normalize a product name while preserving the original.

    Returns a dict with:
        original:  raw name from catalog
        normalized: stripped, lowercased, (New) removed, whitespace collapsed
    """
    original = name
    normalized = original.strip()
    normalized = re.sub(r"\s*\(New\)\s*$", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s+", " ", normalized).strip().lower()
    return {"original": original, "normalized": normalized}


def parse_size(size: str) -> dict:
    """Parse a size string into base quantity and unit.

    Returns a dict with:
        original:           raw size string
        parseable:          bool
        base_unit:          'kg' | 'L' | 'count' | None
        quantity:           float | None
        unit_token:         str | None
    """
    original = size.strip() if size else ""
    if not original:
        return {
            "original": original,
            "parseable": False,
            "base_unit": None,
            "quantity": None,
            "unit_token": None,
            "reason": "empty size",
        }

    m = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([a-zA-Z]+)\s*$", original)
    if not m:
        return {
            "original": original,
            "parseable": False,
            "base_unit": None,
            "quantity": None,
            "unit_token": None,
            "reason": "no numeric-unit match",
        }

    value = float(m.group(1))
    if value <= 0:
        return {
            "original": original,
            "parseable": False,
            "base_unit": None,
            "quantity": None,
            "unit_token": None,
            "reason": "invalid quantity",
        }

    token = m.group(2).lower()
    token = UNIT_ALIASES.get(token, token)

    if token not in UNIT_CONVERSIONS:
        return {
            "original": original,
            "parseable": False,
            "base_unit": None,
            "quantity": None,
            "unit_token": token,
            "reason": f"unsupported unit token: {token}",
        }

    base_unit, multiplier = UNIT_CONVERSIONS[token]
    return {
        "original": original,
        "parseable": True,
        "base_unit": base_unit,
        "quantity": value * multiplier,
        "unit_token": token,
        "reason": None,
    }


def extract_product_type(name: str, brand: str, size: str) -> str:
    """Extract product type by removing brand and size tokens from name."""
    text = name.lower().strip()
    if brand:
        for token in re.split(r"\s+", brand.strip().lower()):
            if token:
                text = re.sub(rf"\b{re.escape(token)}\b", " ", text)
    text = re.sub(r"\d+(?:\.\d+)?", " ", text)
    text = re.sub(r"\b(kg|g|l|ml|ltr|pcs|pack|nos|gm)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def assign_stock_state(
    catalog_row: dict,
    inventory_row: dict | None,
    evaluation_date: str | None = None,
) -> dict:
    """Assign stock state based on inventory row.

    Parameters
    ----------
    evaluation_date: str | None
        Date used to determine if restock_eta is stale. When None, defaults
        to the internal default (2026-10-12) for backward compatibility.
    """
    if inventory_row is None:
        return {
            "stock_state": "unknown",
            "stock_qty": None,
            "restock_eta": None,
            "restock_stale": None,
            "reason": "no inventory row",
        }

    status = (inventory_row.get("status") or "").strip().lower()
    try:
        stock_qty = int(inventory_row.get("stock_qty") or 0)
    except (ValueError, TypeError):
        stock_qty = 0

    restock_eta = (inventory_row.get("restock_eta") or "").strip() or None

    if status == "discontinued":
        return {
            "stock_state": "discontinued",
            "stock_qty": stock_qty,
            "restock_eta": restock_eta,
            "restock_stale": None,
            "reason": "discontinued status",
        }

    if status == "active":
        if stock_qty > 0:
            return {
                "stock_state": "in_stock",
                "stock_qty": stock_qty,
                "restock_eta": restock_eta,
                "restock_stale": None,
                "reason": "active with quantity",
            }
        # Determine staleness using the evaluation date
        if evaluation_date is None:
            evaluation_date = _default_evaluation_date()
        stale = restock_eta < evaluation_date if restock_eta else None
        return {
            "stock_state": "out_of_stock",
            "stock_qty": stock_qty,
            "restock_eta": restock_eta if not stale else None,
            "restock_stale": stale,
            "reason": "active but zero quantity",
        }

    return {
        "stock_state": "unknown",
        "stock_qty": stock_qty,
        "restock_eta": restock_eta,
        "restock_stale": None,
        "reason": f"unrecognized status: {status}",
    }


def _default_evaluation_date() -> str:
    """Return the default evaluation date.

    This is kept as a separate function so tests can patch it without
    affecting the module-level namespace.
    """
    return "2026-10-12"


def compute_category_medians(products: list[dict]) -> dict[tuple[str, str], float]:
    """Compute median unit price per (category, base_unit) from uncorrected data."""
    groups: dict[tuple[str, str], list[float]] = defaultdict(list)
    for p in products:
        if not p["size"]["parseable"]:
            continue
        key = (p["category"], p["size"]["base_unit"])
        groups[key].append(p["unit_price"])

    medians: dict[tuple[str, str], float] = {}
    for key, values in groups.items():
        medians[key] = statistics.median(values)
    return medians


def detect_paise_candidates(products: list[dict], medians: dict[tuple[str, str], float]) -> list[dict]:
    """Flag products whose unit price / category median ratio is 10x-100x."""
    candidates = []
    for p in products:
        if not p["size"]["parseable"]:
            continue
        key = (p["category"], p["size"]["base_unit"])
        median = medians.get(key)
        if median is None or median <= 0:
            continue
        ratio = p["unit_price"] / median
        if PAISE_RATIO_LOW <= ratio <= PAISE_RATIO_HIGH:
            candidates.append(
                {
                    "sku_id": p["sku_id"],
                    "name": p["name"]["original"],
                    "category": p["category"],
                    "supplier": p["supplier"],
                    "raw_price": p["price_raw"],
                    "size": p["size"]["original"],
                    "quantity": p["size"]["quantity"],
                    "base_unit": p["size"]["base_unit"],
                    "unit_price": round(p["unit_price"], 4),
                    "category_median": round(median, 4),
                    "ratio": round(ratio, 4),
                    "proposed_corrected_price": round(p["price_raw"] / 100, 4),
                    "reason": "paise suspected via category-median ratio",
                }
            )
    return candidates


def classify_boundary(candidates: list[dict]) -> list[dict]:
    """Add boundary flags to candidates."""
    for c in candidates:
        r = c["ratio"]
        if r == 100.0:
            c["boundary"] = "exact_100x"
        elif r >= 90.0:
            c["boundary"] = "near_100x"
        elif r <= 11.0:
            c["boundary"] = "near_10x"
        else:
            c["boundary"] = "none"
    return candidates


def mark_likely_false_positives(candidates: list[dict]) -> list[dict]:
    """Add secondary warning for likely false positives."""
    for c in candidates:
        name_lower = c["name"].lower()
        corr = c["proposed_corrected_price"]
        warning = None
        if "ghee" in name_lower and corr < 10:
            warning = "likely_false_positive: ghee corrected under 10 per pack"
        elif "milk powder" in name_lower and corr < 50:
            warning = "likely_false_positive: milk powder corrected under 50 per pack"
        elif "shampoo" in name_lower and corr < 30:
            warning = "likely_false_positive: shampoo corrected under 30 per pack"
        elif "soap" in name_lower and corr < 5:
            warning = "likely_false_positive: soap corrected under 5 per pack"
        elif "floor cleaner" in name_lower and corr < 50:
            warning = "likely_false_positive: floor cleaner corrected under 50 per pack"
        elif "butter" in name_lower and corr < 20:
            warning = "likely_false_positive_uncertain: butter substring match; corrected price plausible for buttermilk"
        c["false_positive_warning"] = warning
    return candidates


def load_catalog(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_inventory(path: Path) -> dict[str, dict]:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {row["sku_id"]: row for row in rows}


def clean_catalog(
    catalog_path: Path,
    inventory_path: Path,
    output_path: Path,
    corrections_path: Path,
    exclusions_path: Path,
    evaluation_date: str | None = None,
) -> dict:
    """Run the full cleaning pipeline.

    Parameters
    ----------
    evaluation_date: str | None
        Date used to determine if restock_eta is stale. When None, defaults
        to 2026-10-12 for backward compatibility.
    """
    catalog_rows = load_catalog(catalog_path)
    inventory_by_sku = load_inventory(inventory_path)

    products = []
    for row in catalog_rows:
        sku = row["sku_id"].strip()
        name_info = normalize_name(row["name"])
        size_info = parse_size(row["size"])
        try:
            raw_price = float(row["price"])
        except (ValueError, TypeError):
            raw_price = 0.0

        inv_row = inventory_by_sku.get(sku)
        stock = assign_stock_state(
            row, inv_row, evaluation_date=evaluation_date
        )

        product = {
            "sku_id": sku,
            "name": name_info,
            "brand": (row.get("brand") or "").strip(),
            "category": (row.get("category") or "").strip(),
            "size": size_info,
            "price_raw": raw_price,
            "price": raw_price,
            "supplier": (row.get("supplier") or "").strip(),
            "description": (row.get("description") or "").strip(),
            "product_type": extract_product_type(
                row["name"], row.get("brand", ""), row.get("size", "")
            ),
            "stock_state": stock["stock_state"],
            "stock_qty": stock["stock_qty"],
            "restock_eta": stock["restock_eta"],
            "restock_stale": stock["restock_stale"],
            "stock_reason": stock["reason"],
            "needs_price_review": False,
            "price_correction_ratio": None,
            "price_correction_proposed": None,
            "price_correction_reason": None,
        }
        products.append(product)

    for p in products:
        if p["size"]["parseable"] and p["size"]["quantity"] > 0:
            p["unit_price"] = p["price_raw"] / p["size"]["quantity"]
        else:
            p["unit_price"] = None

    medians = compute_category_medians(products)

    candidates = detect_paise_candidates(products, medians)
    candidates = classify_boundary(candidates)
    candidates = mark_likely_false_positives(candidates)

    candidate_skus = {c["sku_id"] for c in candidates}
    for p in products:
        if p["sku_id"] in candidate_skus:
            cand = next(c for c in candidates if c["sku_id"] == p["sku_id"])
            p["needs_price_review"] = True
            p["price_correction_ratio"] = cand["ratio"]
            p["price_correction_proposed"] = cand["proposed_corrected_price"]
            p["price_correction_reason"] = cand["reason"]
            p["price_correction_boundary"] = cand["boundary"]
            p["price_false_positive_warning"] = cand["false_positive_warning"]

    oils_ghi_key = ("Oils & Ghee", "L")
    oils_ghi_median = medians.get(oils_ghi_key)
    oils_ghi_count = sum(
        1
        for p in products
        if p["category"] == "Oils & Ghee" and p["size"]["base_unit"] == "L"
    )

    with open(output_path, "w", encoding="utf-8") as f:
        for p in products:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    with open(corrections_path, "w", encoding="utf-8") as f:
        for c in candidates:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    with open(exclusions_path, "w", encoding="utf-8") as f:
        f.write("")

    summary = {
        "total_products": len(products),
        "parseable_sizes": sum(1 for p in products if p["size"]["parseable"]),
        "unparseable_sizes": sum(1 for p in products if not p["size"]["parseable"]),
        "total_candidates": len(candidates),
        "boundary_exact_100x": sum(1 for c in candidates if c["boundary"] == "exact_100x"),
        "boundary_near_100x": sum(1 for c in candidates if c["boundary"] == "near_100x"),
        "boundary_near_10x": sum(1 for c in candidates if c["boundary"] == "near_10x"),
        "standard_candidate": sum(1 for c in candidates if c["boundary"] == "none"),
        "false_positive_warnings": sum(
            1 for c in candidates if c["false_positive_warning"]
        ),
        "oils_ghee_l_count": oils_ghi_count,
        "oils_ghee_l_median": round(oils_ghi_median, 4) if oils_ghi_median else None,
        "oils_ghee_l_high_risk": True,
        "skus_excluded": 0,
        "all_skus_preserved": True,
    }
    return summary


if __name__ == "__main__":
    base = Path(__file__).resolve().parent.parent
    summary = clean_catalog(
        catalog_path=base / "data" / "catalog.csv",
        inventory_path=base / "data" / "inventory.csv",
        output_path=base / "data" / "clean_catalog.jsonl",
        corrections_path=base / "logs" / "price_corrections.jsonl",
        exclusions_path=base / "logs" / "exclusions.jsonl",
    )
    print(json.dumps(summary, indent=2))
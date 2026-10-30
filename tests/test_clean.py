"""Unit tests for Phase 1 cleaning pipeline."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / ".." / "src"))

from clean import (
    assign_stock_state,
    classify_boundary,
    clean_catalog,
    detect_paise_candidates,
    extract_product_type,
    load_catalog,
    load_inventory,
    mark_likely_false_positives,
    normalize_name,
    parse_size,
    compute_category_medians,
)

BASE = Path(__file__).resolve().parent.parent


def test_normalize_name():
    assert normalize_name("  Thela Select Milk (New)  ")["normalized"] == "thela select milk"
    assert normalize_name("Sona Masoori Rice")["normalized"] == "sona masoori rice"
    assert normalize_name("  Ltremon  ")["normalized"] == "ltremon"


def test_parse_size_kg():
    r = parse_size("1 KG")
    assert r["parseable"] is True
    assert r["base_unit"] == "kg"
    assert r["quantity"] == 1.0


def test_parse_size_g():
    r = parse_size("500G")
    assert r["parseable"] is True
    assert r["base_unit"] == "kg"
    assert r["quantity"] == 0.5


def test_parse_size_ml():
    r = parse_size("500ML")
    assert r["parseable"] is True
    assert r["base_unit"] == "L"
    assert r["quantity"] == 0.5


def test_parse_size_ltr():
    r = parse_size("1LTR")
    assert r["parseable"] is True
    assert r["base_unit"] == "L"
    assert r["quantity"] == 1.0


def test_parse_size_pcs():
    r = parse_size("4 pcs")
    assert r["parseable"] is True
    assert r["base_unit"] == "count"
    assert r["quantity"] == 4.0


def test_parse_size_unparseable():
    r = parse_size("Pack of 1")
    assert r["parseable"] is False


def test_parse_size_empty():
    r = parse_size("")
    assert r["parseable"] is False


def test_parse_size_whitespace_only():
    r = parse_size("   ")
    assert r["parseable"] is False
    assert r["reason"] == "empty size"


def test_parse_size_gm_alias():
    r = parse_size("500 GM")
    assert r["parseable"] is True
    assert r["base_unit"] == "kg"
    assert r["quantity"] == 0.5
    assert r["unit_token"] == "g"


def test_parse_size_nos_alias():
    r = parse_size("4 NOS")
    assert r["parseable"] is True
    assert r["base_unit"] == "count"
    assert r["quantity"] == 4.0
    assert r["unit_token"] == "pcs"


def test_parse_size_pieces_unsupported():
    r = parse_size("100 pieces")
    assert r["parseable"] is False
    assert r["reason"] == "unsupported unit token: pieces"


def test_parse_size_trailing_junk():
    r = parse_size("1 KG extra")
    assert r["parseable"] is False
    assert r["reason"] == "no numeric-unit match"


def test_parse_size_zero_quantity():
    r = parse_size("0 KG")
    assert r["parseable"] is False
    assert r["reason"] == "invalid quantity"


def test_parse_size_negative_quantity():
    r = parse_size("-1 KG")
    assert r["parseable"] is False
    assert r["reason"] == "no numeric-unit match"


def test_parse_size_preserves_original_on_unparseable():
    r = parse_size("1 KG extra")
    assert r["original"] == "1 KG extra"
    assert r["parseable"] is False


def test_unit_price_excludes_invalid_quantity():
    products = [
        {
            "sku_id": "TEST001",
            "name": {"original": "Valid Product"},
            "category": "Test Cat",
            "supplier": "test",
            "price_raw": 5000,
            "size": {"original": "1 KG", "parseable": True, "base_unit": "kg", "quantity": 1.0},
            "unit_price": 5000.0,
        },
        {
            "sku_id": "TEST002",
            "name": {"original": "Zero Qty Product"},
            "category": "Test Cat",
            "supplier": "test",
            "price_raw": 5000,
            "size": {"original": "0 KG", "parseable": False, "base_unit": None, "quantity": None},
            "unit_price": None,
        },
        {
            "sku_id": "TEST003",
            "name": {"original": "Unparseable Product"},
            "category": "Test Cat",
            "supplier": "test",
            "price_raw": 5000,
            "size": {"original": "Pack of 1", "parseable": False, "base_unit": None, "quantity": None},
            "unit_price": None,
        },
    ]
    medians = compute_category_medians(products)
    # Only TEST001 should contribute to the median
    assert medians == {("Test Cat", "kg"): 5000.0}


def test_detect_paise_excludes_invalid_quantity():
    products = [
        {
            "sku_id": "TEST001",
            "name": {"original": "Valid Product"},
            "category": "Test Cat",
            "supplier": "test",
            "price_raw": 5000,
            "size": {"original": "1 KG", "parseable": True, "base_unit": "kg", "quantity": 1.0},
            "unit_price": 5000.0,
        },
        {
            "sku_id": "TEST002",
            "name": {"original": "Zero Qty Product"},
            "category": "Test Cat",
            "supplier": "test",
            "price_raw": 5000,
            "size": {"original": "0 KG", "parseable": False, "base_unit": None, "quantity": None},
            "unit_price": None,
        },
    ]
    medians = {("Test Cat", "kg"): 500.0}
    candidates = detect_paise_candidates(products, medians)
    assert len(candidates) == 1
    assert candidates[0]["sku_id"] == "TEST001"


def test_extract_product_type():
    result = extract_product_type("Thela Select Sona Masoori Rice 1 KG", "Thela Select", "1 KG")
    assert "sona masoori rice" in result


def test_assign_stock_state_in_stock():
    state = {
        "sku_id": "TW00001",
        "stock_qty": "10",
        "status": "active",
        "restock_eta": "",
        "updated_at": "2026-10-01",
    }
    result = assign_stock_state({}, state)
    assert result["stock_state"] == "in_stock"


def test_assign_stock_state_out_of_stock():
    state = {
        "sku_id": "TW00002",
        "stock_qty": "0",
        "status": "active",
        "restock_eta": "2026-10-15",
        "updated_at": "2026-10-01",
    }
    result = assign_stock_state({}, state)
    assert result["stock_state"] == "out_of_stock"
    assert result["restock_stale"] is False


def test_assign_stock_state_discontinued():
    state = {
        "sku_id": "TW00003",
        "stock_qty": "0",
        "status": "discontinued",
        "restock_eta": None,
        "updated_at": "2026-10-01",
    }
    result = assign_stock_state({}, state)
    assert result["stock_state"] == "discontinued"


def test_assign_stock_state_unknown():
    result = assign_stock_state({}, None)
    assert result["stock_state"] == "unknown"


def test_load_catalog_count():
    rows = load_catalog(BASE / "data" / "catalog.csv")
    assert len(rows) == 1102


def test_load_inventory_count():
    inv = load_inventory(BASE / "data" / "inventory.csv")
    assert len(inv) == 1070


def test_compute_category_medians_grouped_by_unit():
    products = [
        {"category": "Atta, Rice & Dal", "size": {"parseable": True, "base_unit": "kg", "quantity": 1.0}, "unit_price": 100.0},
        {"category": "Atta, Rice & Dal", "size": {"parseable": True, "base_unit": "kg", "quantity": 1.0}, "unit_price": 200.0},
        {"category": "Atta, Rice & Dal", "size": {"parseable": True, "base_unit": "L", "quantity": 1.0}, "unit_price": 50.0},
    ]
    medians = compute_category_medians(products)
    assert medians[("Atta, Rice & Dal", "kg")] == 150.0
    assert medians[("Atta, Rice & Dal", "L")] == 50.0


def test_detect_paise_candidates_ratio_rule():
    products = [
        {
            "sku_id": "TEST001",
            "name": {"original": "Test Product"},
            "category": "Test Cat",
            "supplier": "test",
            "price_raw": 5000,
            "size": {"original": "1 KG", "parseable": True, "base_unit": "kg", "quantity": 1.0},
            "unit_price": 5000.0,
        }
    ]
    medians = {("Test Cat", "kg"): 500.0}
    candidates = detect_paise_candidates(products, medians)
    assert len(candidates) == 1
    assert candidates[0]["ratio"] == 10.0
    assert candidates[0]["proposed_corrected_price"] == 50.0


def test_classify_boundary_exact_100x():
    candidates = [{"ratio": 100.0}]
    classify_boundary(candidates)
    assert candidates[0]["boundary"] == "exact_100x"


def test_classify_boundary_near_100x():
    candidates = [{"ratio": 95.0}]
    classify_boundary(candidates)
    assert candidates[0]["boundary"] == "near_100x"


def test_classify_boundary_near_10x():
    candidates = [{"ratio": 10.5}]
    classify_boundary(candidates)
    assert candidates[0]["boundary"] == "near_10x"


def test_classify_boundary_standard():
    candidates = [{"ratio": 50.0}]
    classify_boundary(candidates)
    assert candidates[0]["boundary"] == "none"


def test_mark_likely_false_positive_ghee():
    candidates = [{"name": "Test Ghee 200 ml", "proposed_corrected_price": 5.0}]
    mark_likely_false_positives(candidates)
    assert candidates[0]["false_positive_warning"] is not None
    assert "ghee" in candidates[0]["false_positive_warning"]


def test_end_to_end_summary():
    summary = clean_catalog(
        catalog_path=BASE / "data" / "catalog.csv",
        inventory_path=BASE / "data" / "inventory.csv",
        output_path=BASE / "data" / "clean_catalog.jsonl",
        corrections_path=BASE / "logs" / "price_corrections.jsonl",
        exclusions_path=BASE / "logs" / "exclusions.jsonl",
    )
    assert summary["total_products"] == 1102
    assert summary["all_skus_preserved"] is True
    assert summary["skus_excluded"] == 0
    assert summary["oils_ghee_l_high_risk"] is True
    assert summary["oils_ghee_l_count"] == 32


def test_clean_catalog_row_count():
    with open(BASE / "data" / "clean_catalog.jsonl", encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]
    assert len(lines) == 1102


def test_clean_catalog_raw_price_preserved():
    with open(BASE / "data" / "clean_catalog.jsonl", encoding="utf-8") as f:
        for line in f:
            p = json.loads(line)
            assert p["price"] == p["price_raw"]


def test_clean_catalog_no_duplicate_skus():
    skus = []
    with open(BASE / "data" / "clean_catalog.jsonl", encoding="utf-8") as f:
        for line in f:
            p = json.loads(line)
            skus.append(p["sku_id"])
    assert len(skus) == len(set(skus))


def test_corrections_log_has_candidates():
    with open(BASE / "logs" / "price_corrections.jsonl", encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]
    assert len(lines) >= 72


def test_exclusions_log_empty():
    content = (BASE / "logs" / "exclusions.jsonl").read_text(encoding="utf-8")
    assert content == ""


# --- Evaluation date tests ---

def test_assign_stock_state_past_eta():
    """ETA in the past should make restock_stale True."""
    state = {
        "sku_id": "TW00002",
        "stock_qty": "0",
        "status": "active",
        "restock_eta": "2020-01-01",
        "updated_at": "2026-10-01",
    }
    result = assign_stock_state({}, state)
    assert result["stock_state"] == "out_of_stock"
    assert result["restock_stale"] is True


def test_assign_stock_state_future_eta():
    """ETA in the future should make restock_stale False."""
    state = {
        "sku_id": "TW00002",
        "stock_qty": "0",
        "status": "active",
        "restock_eta": "2030-01-01",
        "updated_at": "2026-10-01",
    }
    result = assign_stock_state({}, state)
    assert result["stock_state"] == "out_of_stock"
    assert result["restock_stale"] is False


def test_assign_stock_state_missing_eta():
    """Missing ETA should make restock_stale None."""
    state = {
        "sku_id": "TW00002",
        "stock_qty": "0",
        "status": "active",
        "restock_eta": None,
        "updated_at": "2026-10-01",
    }
    result = assign_stock_state({}, state)
    assert result["stock_state"] == "out_of_stock"
    assert result["restock_stale"] is None
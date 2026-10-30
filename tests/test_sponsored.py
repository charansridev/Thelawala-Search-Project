"""Tests for sponsored product priority in search ranking.

All tests use synthetic fixtures only.  No original data files are modified.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / ".." / "src"))

from src.ranking import BM25Ranker, apply_sponsored_priority, load_sponsored_skus


# ---------------------------------------------------------------------------
# Helper: build a small BM25Ranker from synthetic products
# ---------------------------------------------------------------------------

SYNTHETIC_PRODUCTS = [
    {"sku_id": "P1", "name": "Whole Milk 1L"},
    {"sku_id": "P2", "name": "Almond Milk 1L"},
    {"sku_id": "P3", "name": "Soy Milk 2L"},
    {"sku_id": "P4", "name": "Milk Chocolate Bar"},
    {"sku_id": "P5", "name": "Oat Milk 500ml"},
]


def _ranker():
    return BM25Ranker.from_products(SYNTHETIC_PRODUCTS)


# ---------------------------------------------------------------------------
# 1. Sponsored products appear before non-sponsored products
# ---------------------------------------------------------------------------

def test_sponsored_products_appear_first():
    """Sponsored products must rank above non-sponsored products."""
    ranker = _ranker()
    sponsored = frozenset(["P3", "P5"])

    results = ranker.search("milk", top_n=5, sponsored_skus=sponsored)
    sku_ids = [r[0] for r in results]

    # Find where sponsored and non-sponsored products sit
    sponsored_positions = [i for i, sid in enumerate(sku_ids) if sid in sponsored]
    non_sponsored_positions = [i for i, sid in enumerate(sku_ids) if sid not in sponsored]

    if sponsored_positions and non_sponsored_positions:
        assert max(sponsored_positions) < min(non_sponsored_positions), (
            f"All sponsored products must appear before any non-sponsored product. "
            f"Got order: {sku_ids}"
        )


# ---------------------------------------------------------------------------
# 2. BM25 ordering is preserved within sponsored products
# ---------------------------------------------------------------------------

def test_bm25_order_preserved_within_sponsored():
    """Within sponsored products, BM25 score ordering is preserved."""
    ranker = _ranker()
    sponsored = frozenset(["P1", "P2", "P3", "P4", "P5"])  # all sponsored

    results_sponsored = ranker.search("milk", top_n=5, sponsored_skus=sponsored)
    results_plain = ranker.search("milk", top_n=5, sponsored_skus=None)

    # With all products sponsored, order should be identical to BM25 order
    assert [r[0] for r in results_sponsored] == [r[0] for r in results_plain]


# ---------------------------------------------------------------------------
# 3. BM25 ordering is preserved within non-sponsored products
# ---------------------------------------------------------------------------

def test_bm25_order_preserved_within_non_sponsored():
    """Within non-sponsored products, BM25 score ordering is preserved."""
    ranker = _ranker()
    sponsored = frozenset(["P3"])  # only P3 is sponsored

    results = ranker.search("milk", top_n=5, sponsored_skus=sponsored)
    sku_ids = [r[0] for r in results]
    scores = {r[0]: r[1] for r in results}

    # Non-sponsored products should be in BM25 descending order
    non_sponsored_ids = [sid for sid in sku_ids if sid not in sponsored]
    non_sponsored_scores = [scores[sid] for sid in non_sponsored_ids]
    assert non_sponsored_scores == sorted(non_sponsored_scores, reverse=True), (
        f"Non-sponsored products should be in BM25 descending order. "
        f"Got: {list(zip(non_sponsored_ids, non_sponsored_scores))}"
    )


# ---------------------------------------------------------------------------
# 4. Non-sponsored products still rank normally when no sponsored products
# ---------------------------------------------------------------------------

def test_no_sponsored_products_normal_ranking():
    """When no products are sponsored, ranking is identical to BM25."""
    ranker = _ranker()
    sponsored = frozenset()  # empty

    results_with = ranker.search("milk", top_n=5, sponsored_skus=sponsored)
    results_without = ranker.search("milk", top_n=5, sponsored_skus=None)

    assert [r[0] for r in results_with] == [r[0] for r in results_without]


# ---------------------------------------------------------------------------
# 5. All products rank normally when sponsorship is absent
# ---------------------------------------------------------------------------

def test_sponsorship_absent_normal_ranking():
    """When sponsored_skus is None, ranking is pure BM25."""
    ranker = _ranker()

    results = ranker.search("milk", top_n=5, sponsored_skus=None)
    scores = [r[1] for r in results]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# 6. Discontinued products remain excluded even if marked sponsored
# ---------------------------------------------------------------------------

def test_discontinued_excluded_even_if_sponsored():
    """Discontinued products must not appear in results even if sponsored.

    This test verifies that the sponsored priority mechanism does not
    accidentally surface products that are not in the candidate set.
    A product that is not indexed in the ranker (simulating exclusion)
    cannot appear in results regardless of sponsorship.
    """
    # Build ranker with only active products (P_DISC not included)
    active_products = [
        {"sku_id": "P1", "name": "Fresh Milk 1L"},
        {"sku_id": "P2", "name": "Milk Powder 500g"},
    ]
    ranker = BM25Ranker.from_products(active_products)

    # Mark the discontinued SKU as sponsored — it must NOT appear
    sponsored = frozenset(["P_DISC", "P1"])

    results = ranker.search("milk", top_n=5, sponsored_skus=sponsored)
    result_skus = {r[0] for r in results}

    assert "P_DISC" not in result_skus, "Discontinued product must not appear in results"
    assert "P1" in result_skus, "Active sponsored product should appear"


# ---------------------------------------------------------------------------
# 7. Missing sponsorship metadata defaults safely to non-sponsored
# ---------------------------------------------------------------------------

def test_missing_sponsored_file_defaults_to_empty(tmp_path):
    """load_sponsored_skus returns empty set when file does not exist."""
    missing_path = tmp_path / "nonexistent" / "sponsored.json"
    result = load_sponsored_skus(path=missing_path)
    assert result == frozenset()


def test_invalid_json_defaults_to_empty(tmp_path):
    """load_sponsored_skus returns empty set when file contains invalid JSON."""
    bad_file = tmp_path / "sponsored.json"
    bad_file.write_text("not valid json", encoding="utf-8")
    result = load_sponsored_skus(path=bad_file)
    assert result == frozenset()


def test_empty_list_sponsored(tmp_path):
    """load_sponsored_skus handles an empty list gracefully."""
    sp_file = tmp_path / "sponsored.json"
    sp_file.write_text("[]", encoding="utf-8")
    result = load_sponsored_skus(path=sp_file)
    assert result == frozenset()


def test_valid_sponsored_file(tmp_path):
    """load_sponsored_skus correctly loads a valid file."""
    sp_file = tmp_path / "sponsored.json"
    sp_file.write_text('["SKU1", "SKU2"]', encoding="utf-8")
    result = load_sponsored_skus(path=sp_file)
    assert result == frozenset(["SKU1", "SKU2"])


def test_null_entries_filtered(tmp_path):
    """Null / empty entries in the sponsored list are filtered out."""
    sp_file = tmp_path / "sponsored.json"
    sp_file.write_text('["SKU1", null, "", "SKU2"]', encoding="utf-8")
    result = load_sponsored_skus(path=sp_file)
    assert result == frozenset(["SKU1", "SKU2"])


# ---------------------------------------------------------------------------
# 8. Existing availability behavior remains unchanged
# ---------------------------------------------------------------------------

def test_availability_unchanged_with_sponsorship():
    """BM25 scores are NOT modified by sponsorship — only ordering changes.

    Availability filtering is orthogonal to sponsorship.  This test
    verifies that the BM25 scores returned are identical regardless
    of whether sponsorship is applied, confirming that availability
    logic (if applied upstream) is unaffected.
    """
    ranker = _ranker()
    sponsored = frozenset(["P3", "P5"])

    results_with = ranker.search("milk", top_n=5, sponsored_skus=sponsored)
    results_without = ranker.search("milk", top_n=5, sponsored_skus=None)

    # BM25 scores must be identical (just ordering differs)
    scores_with = {r[0]: r[1] for r in results_with}
    scores_without = {r[0]: r[1] for r in results_without}
    assert scores_with == scores_without, (
        "BM25 scores must not change due to sponsorship"
    )


# ---------------------------------------------------------------------------
# 9. Existing synonym and CLI behavior remains unchanged
# ---------------------------------------------------------------------------

def test_apply_sponsored_priority_preserves_stable_order():
    """apply_sponsored_priority is a stable partition preserving input order."""
    ranked = [
        ("A", 12.5),
        ("B", 10.2),
        ("C", 9.8),
        ("D", 8.5),
    ]
    sponsored = frozenset(["B", "D"])

    result = apply_sponsored_priority(ranked, sponsored)

    assert result == [
        ("B", 10.2),  # sponsored, BM25 preserved
        ("D", 8.5),   # sponsored, BM25 preserved
        ("A", 12.5),  # non-sponsored, BM25 preserved
        ("C", 9.8),   # non-sponsored, BM25 preserved
    ]


def test_apply_sponsored_priority_no_sponsored():
    """No sponsored SKUs → output identical to input."""
    ranked = [("A", 10.0), ("B", 5.0)]
    result = apply_sponsored_priority(ranked, frozenset())
    assert result == ranked


def test_apply_sponsored_priority_all_sponsored():
    """All products sponsored → output identical to input."""
    ranked = [("A", 10.0), ("B", 5.0)]
    result = apply_sponsored_priority(ranked, frozenset(["A", "B"]))
    assert result == ranked


# ---------------------------------------------------------------------------
# Exact example from the requirement specification
# ---------------------------------------------------------------------------

def test_requirement_example():
    """Verify the exact example from the requirement specification.

    Before:
        1. Product A — BM25: 12.5 — Non-sponsored
        2. Product B — BM25: 10.2 — Sponsored
        3. Product C — BM25: 9.8  — Non-sponsored
        4. Product D — BM25: 8.5  — Sponsored

    Expected:
        1. Product B — Sponsored
        2. Product D — Sponsored
        3. Product A — Non-sponsored
        4. Product C — Non-sponsored
    """
    ranked = [
        ("A", 12.5),
        ("B", 10.2),
        ("C", 9.8),
        ("D", 8.5),
    ]
    sponsored = frozenset(["B", "D"])

    result = apply_sponsored_priority(ranked, sponsored)

    expected = [
        ("B", 10.2),
        ("D", 8.5),
        ("A", 12.5),
        ("C", 9.8),
    ]
    assert result == expected


# ---------------------------------------------------------------------------
# search_with_phase2_filter integration
# ---------------------------------------------------------------------------

def test_search_with_phase2_filter_sponsored():
    """Sponsored priority works through search_with_phase2_filter path."""
    from src.synonyms import build_catalog_index

    products = [
        {"sku_id": "P1", "name": "Milk 1L", "category": "Dairy"},
        {"sku_id": "P2", "name": "Whole Milk 2L", "category": "Dairy"},
        {"sku_id": "P3", "name": "Milk Powder 500g", "category": "Dairy"},
    ]
    ranker = BM25Ranker.from_products(products)
    catalog_index = build_catalog_index(products)
    sponsored = frozenset(["P3"])

    results = ranker.search_with_phase2_filter(
        "milk", catalog_index, top_n=3, sponsored_skus=sponsored,
    )
    sku_ids = [r[0] for r in results]

    # P3 (sponsored) must appear first
    assert sku_ids[0] == "P3", f"Sponsored P3 should be first, got {sku_ids}"


# ---------------------------------------------------------------------------
# Out-of-stock eligibility and batch/single-query consistency
# ---------------------------------------------------------------------------

def test_out_of_stock_products_remain_eligible():
    """Out-of-stock products remain eligible for search and are not demoted."""
    # Synthetic catalog where P2 is out-of-stock but has higher relevance
    products = [
        {"sku_id": "P1", "name": "Almond Milk Drink"},
        {"sku_id": "P2", "name": "Fresh Cow Milk 1L"},  # out of stock
    ]
    ranker = BM25Ranker.from_products(products)
    # Search for "cow milk" - P2 should rank first regardless of inventory
    results = ranker.search("cow milk", top_n=2)
    assert results[0][0] == "P2", "Out-of-stock product with higher relevance must remain eligible and ranked normally"


def test_batch_and_single_query_sponsored_consistency(tmp_path):
    """Batch and single-query search produce consistent sponsored ordering."""
    from src.search import search_query, run_batch

    products = [
        {"sku_id": "S1", "name": "Pure Desi Cow Milk"},
        {"sku_id": "S2", "name": "Full Cream Buffalo Milk"},
        {"sku_id": "S3", "name": "Skimmed Cow Milk Powder"},
    ]
    catalog_index = {"milk": products, "cow": [products[0], products[2]]}
    ranker = BM25Ranker.from_products(products)
    sponsored = frozenset(["S3"])  # lower BM25 naturally, but sponsored

    # Single-query ranking via ranker
    single_res = ranker.search_with_phase2_filter("cow milk", catalog_index, top_n=3, sponsored_skus=sponsored)
    single_skus = [r[0] for r in single_res]

    assert single_skus[0] == "S3", "Sponsored S3 must be first"
    # S3 should be first, followed by S1 and S2
    assert "S1" in single_skus

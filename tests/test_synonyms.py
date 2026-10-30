#!/usr/bin/env python3
"""Phase 2: Focused tests for search-log mining and synonym discovery logic."""

import csv
import json
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent / ".." / "src"))

from src.synonyms import (
    HIGH,
    MEDIUM,
    LOW,
    normalize_query,
    edit_distance,
    load_search_log,
    load_catalog,
    extract_session_transitions,
    extract_search_source_engagement,
    build_catalog_index,
    find_catalog_matches,
    queries_are_related,
    generate_candidates,
    write_candidates,
    summarize,
    run_pipeline,
    SEARCH_LOG,
    CATALOG_CSV,
    SYNONYM_CANDIDATES,
)


# ---------------------------------------------------------------------------
# normalize_query
# ---------------------------------------------------------------------------

def test_normalize_query_lowercases():
    assert normalize_query("MILK CHOCOLAATE") == "milk chocolaate"


def test_normalize_query_collapses_whitespace():
    assert normalize_query("  milk   chocolate  ") == "milk chocolate"


def test_normalize_query_strips_non_alnum():
    assert normalize_query("MILK-CHOCOLAATE!") == "milk chocolaate"


def test_normalize_query_empty():
    assert normalize_query("") == ""
    assert normalize_query("   ") == ""


# ---------------------------------------------------------------------------
# edit_distance
# ---------------------------------------------------------------------------

def test_edit_distance_identical():
    assert edit_distance("milk", "milk") == 0


def test_edit_distance_empty():
    assert edit_distance("", "abc") == 3
    assert edit_distance("abc", "") == 3


def test_edit_distance_substitution():
    assert edit_distance("panner", "paneer") == 1


def test_edit_distance_insertion():
    assert edit_distance("milk", "milks") == 1


def test_edit_distance_deletion():
    assert edit_distance("tomatos", "tomato") == 1


# ---------------------------------------------------------------------------
# load_search_log / load_catalog
# ---------------------------------------------------------------------------

def test_load_search_log_returns_records():
    records = load_search_log(SEARCH_LOG)
    assert len(records) > 0
    assert "query" in records[0]
    assert "session_id" in records[0]
    assert "results_count" in records[0]
    assert "events" in records[0]


def test_load_catalog_returns_products():
    products = load_catalog(CATALOG_CSV)
    assert len(products) > 0
    assert "sku_id" in products[0]
    assert "name" in products[0]
    assert "category" in products[0]


# ---------------------------------------------------------------------------
# extract_session_transitions
# ---------------------------------------------------------------------------

def test_extract_session_transitions_basic():
    records = [
        {"session_id": "s1", "query": "a", "results_count": 0, "ts": "2026-01-01T00:00:00+05:30"},
        {"session_id": "s1", "query": "b", "results_count": 5, "ts": "2026-01-01T00:01:00+05:30"},
        {"session_id": "s1", "query": "c", "results_count": 3, "ts": "2026-01-01T00:02:00+05:30"},
        {"session_id": "s2", "query": "x", "results_count": 0, "ts": "2026-01-01T00:00:00+05:30"},
        {"session_id": "s2", "query": "y", "results_count": 0, "ts": "2026-01-01T00:01:00+05:30"},
    ]
    transitions = extract_session_transitions(records)
    # Only zero-to-nonzero transitions are counted
    assert transitions[("a", "b")] == 1  # 0 -> non-zero
    assert transitions[("b", "c")] == 0  # non-zero -> non-zero, excluded
    assert transitions[("x", "y")] == 0  # zero -> zero, excluded


def test_extract_session_transitions_excludes_nonzero_to_nonzero():
    """Unrelated non-zero-to-nonzero transitions are excluded per the new rule."""
    records = [
        {"session_id": "s1", "query": "apple", "results_count": 3, "ts": "2026-01-01T00:00:00+05:30"},
        {"session_id": "s1", "query": "banana", "results_count": 5, "ts": "2026-01-01T00:01:00+05:30"},
    ]
    transitions = extract_session_transitions(records)
    # Both queries have results > 0, so this transition is excluded
    assert transitions[("apple", "banana")] == 0


def test_extract_session_transitions_skips_duplicates():
    records = [
        {"session_id": "s1", "query": "milk", "results_count": 0, "ts": "2026-01-01T00:00:00+05:30"},
        {"session_id": "s1", "query": "milk", "results_count": 0, "ts": "2026-01-01T00:01:00+05:30"},
    ]
    transitions = extract_session_transitions(records)
    assert transitions == {}


def test_extract_session_transitions_orders_by_timestamp():
    records = [
        {"session_id": "s1", "query": "b", "results_count": 5, "ts": "2026-01-01T00:01:00+05:30"},
        {"session_id": "s1", "query": "a", "results_count": 0, "ts": "2026-01-01T00:00:00+05:30"},
    ]
    transitions = extract_session_transitions(records)
    assert transitions[("a", "b")] == 1


# ---------------------------------------------------------------------------
# extract_search_source_engagement
# ---------------------------------------------------------------------------

def test_extract_search_source_engagement_counts_search_events():
    records = [
        {
            "session_id": "s1",
            "query": "milk",
            "results_count": 5,
            "events": [
                {"sku_id": "p1", "action": "click", "source": "search", "position": 1, "sponsored": False},
                {"sku_id": "p2", "action": "add_to_cart", "source": "search", "position": 2, "sponsored": False},
            ],
        },
    ]
    engagement = extract_search_source_engagement(records)
    assert engagement["milk"] == 2


def test_extract_search_source_engagement_excludes_browse():
    records = [
        {
            "session_id": "s1",
            "query": "milk",
            "results_count": 5,
            "events": [
                {"sku_id": "p1", "action": "click", "source": "browse", "position": None, "sponsored": False},
                {"sku_id": "p2", "action": "click", "source": "search", "position": 1, "sponsored": False},
            ],
        },
    ]
    engagement = extract_search_source_engagement(records)
    assert engagement["milk"] == 1  # only search-source counted


def test_extract_search_source_engagement_ignores_other_actions():
    records = [
        {
            "session_id": "s1",
            "query": "milk",
            "results_count": 5,
            "events": [
                {"sku_id": "p1", "action": "impression", "source": "search", "position": 1, "sponsored": False},
            ],
        },
    ]
    engagement = extract_search_source_engagement(records)
    assert engagement == {}


# ---------------------------------------------------------------------------
# build_catalog_index / find_catalog_matches
# ---------------------------------------------------------------------------

def test_build_catalog_index():
    products = [
        {"sku_id": "p1", "name": "Godavari Milk 1L", "category": "Dairy & Eggs"},
        {"sku_id": "p2", "name": "Curd 500g", "category": "Dairy & Eggs"},
    ]
    index = build_catalog_index(products)
    assert "godavari" in index
    assert "milk" in index
    assert len(index["milk"]) == 1
    assert index["milk"][0]["sku_id"] == "p1"


def test_find_catalog_matches_exact_token():
    products = [
        {"sku_id": "p1", "name": "Godavari Milk 1L", "category": "Dairy & Eggs"},
        {"sku_id": "p2", "name": "Curd 500g", "category": "Dairy & Eggs"},
    ]
    index = build_catalog_index(products)
    matches = find_catalog_matches("milk", index, max_distance=2)
    assert len(matches) == 1
    assert matches[0][0] == "Godavari Milk 1L"
    assert matches[0][2] == 0


def test_find_catalog_matches_typo():
    products = [
        {"sku_id": "p1", "name": "Paneer 200g", "category": "Dairy & Eggs"},
    ]
    index = build_catalog_index(products)
    matches = find_catalog_matches("panner", index, max_distance=2, all_products=products)
    assert len(matches) == 1
    assert matches[0][0] == "Paneer 200g"
    assert matches[0][2] == 1


def test_find_catalog_matches_no_match():
    products = [
        {"sku_id": "p1", "name": "Milk 1L", "category": "Dairy & Eggs"},
    ]
    index = build_catalog_index(products)
    matches = find_catalog_matches("cigarette", index, max_distance=2)
    assert matches == []


def test_find_catalog_matches_multi_word_all_tokens():
    """All query tokens must appear in product name (no single-token false positives)."""
    products = [
        {"sku_id": "p1", "name": "SPARKLE FACE WASH - NEEM 100ML", "category": "Personal Care"},
    ]
    index = build_catalog_index(products)
    matches = find_catalog_matches("dish wash", index, max_distance=10)
    assert matches == []


# ---------------------------------------------------------------------------
# queries_are_related
# ---------------------------------------------------------------------------

def test_queries_are_related_shared_token():
    assert queries_are_related("refined oil", "sunflower oil") is True


def test_queries_are_related_containment():
    assert queries_are_related("atta", "whole wheat atta") is True
    assert queries_are_related("whole wheat atta", "atta") is True


def test_queries_are_related_edit_distance():
    assert queries_are_related("panner", "paneer") is True
    assert queries_are_related("tomatos", "tomato") is True


def test_queries_are_related_not_related():
    assert queries_are_related("chips under 20", "tomato") is False
    assert queries_are_related("cigarette", "coffee") is False


def test_queries_are_related_normalizes_case():
    assert queries_are_related("PANEER", "paneer") is True


# ---------------------------------------------------------------------------
# generate_candidates
# ---------------------------------------------------------------------------

def test_generate_candidates_session_transition_high():
    records = []
    for i in range(7):
        records.append(
            {"session_id": "s1", "query": "venna", "results_count": 0,
             "ts": f"2026-01-01T00:{i:02d}:00+05:30"}
        )
        records.append(
            {"session_id": "s1", "query": "butter", "results_count": 5,
             "ts": f"2026-01-01T00:{i:02d}:30+05:30",
             "events": [{"sku_id": "p1", "action": "click", "source": "search",
                        "position": 1, "sponsored": False}]}
        )
    products = [{"sku_id": "p1", "name": "Butter 200g", "category": "Dairy & Eggs"}]
    candidates = generate_candidates(records, products)
    high = [c for c in candidates if c["confidence"] == HIGH]
    assert any(c["query"] == "venna" and c["synonym"] == "butter" for c in high)


def test_generate_candidates_spelling_variant():
    records = [
        {"session_id": "s1", "query": "panner", "results_count": 0, "ts": "2026-01-01T00:00:00+05:30"},
        {"session_id": "s2", "query": "panner", "results_count": 0, "ts": "2026-01-01T00:01:00+05:30"},
    ]
    products = [{"sku_id": "p1", "name": "Paneer 200g", "category": "Dairy & Eggs"}]
    candidates = generate_candidates(records, products)
    assert any(
        c["query"] == "panner" and c["synonym"] == "Paneer 200g"
        and c["evidence_type"] == "spelling_variant_catalog_match"
        for c in candidates
    )


def test_generate_candidates_excludes_browse_as_evidence():
    """Browse events must not create synonym evidence."""
    records = [
        {
            "session_id": "s1",
            "query": "milk chocolate",
            "results_count": 0,
            "ts": "2026-01-01T00:00:00+05:30",
            "events": [
                {"sku_id": "p1", "action": "click", "source": "browse", "position": None, "sponsored": False},
                {"sku_id": "p1", "action": "add_to_cart", "source": "browse", "position": None, "sponsored": False},
            ],
        },
        {
            "session_id": "s1",
            "query": "chocolate",
            "results_count": 5,
            "ts": "2026-01-01T00:01:00+05:30",
            "events": [],
        },
    ]
    products = [{"sku_id": "p1", "name": "Chocolate Bar", "category": "Bakery & Snacks"}]
    candidates = generate_candidates(records, products)
    high = [c for c in candidates if c["confidence"] == HIGH]
    assert not any(c["query"] == "milk chocolate" for c in high)


def test_generate_candidates_zero_result_no_match():
    records = [
        {"session_id": "s1", "query": "cigarette", "results_count": 0, "ts": "2026-01-01T00:00:00+05:30"},
        {"session_id": "s2", "query": "cigarette", "results_count": 0, "ts": "2026-01-01T00:01:00+05:30"},
    ]
    products = [{"sku_id": "p1", "name": "Milk 1L", "category": "Dairy & Eggs"}]
    candidates = generate_candidates(records, products)
    no_match = [c for c in candidates if c["evidence_type"] == "zero_result_no_match"]
    assert any(c["query"] == "cigarette" for c in no_match)


def test_generate_candidates_does_not_mutate_inputs():
    records = [
        {"session_id": "s1", "query": "a", "results_count": 0, "ts": "t1"},
        {"session_id": "s1", "query": "b", "results_count": 5, "ts": "t2"},
    ]
    original = [dict(r) for r in records]
    products = [{"sku_id": "p1", "name": "B", "category": "X"}]
    generate_candidates(records, products)
    assert records == original


# ---------------------------------------------------------------------------
# write_candidates / summarize
# ---------------------------------------------------------------------------

def test_write_candidates_creates_file(tmp_path):
    out = tmp_path / "test_candidates.jsonl"
    candidates = [
        {"query": "a", "synonym": "b", "confidence": HIGH, "evidence_type": "t",
         "evidence_count": 1, "query_zero_result": True, "catalog_supported": True,
         "explanation": "test"}
    ]
    write_candidates(candidates, out)
    assert out.exists()
    with open(out, encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["query"] == "a"


def test_summarize_counts():
    candidates = [
        {"confidence": HIGH, "evidence_type": "session_transition_zero_to_nonzero",
         "query_zero_result": True, "catalog_supported": True, "evidence_count": 1},
        {"confidence": MEDIUM, "evidence_type": "session_transition_zero_to_nonzero",
         "query_zero_result": True, "catalog_supported": False, "evidence_count": 1},
        {"confidence": LOW, "evidence_type": "zero_result_no_match",
         "query_zero_result": True, "catalog_supported": False, "evidence_count": 1},
    ]
    summary = summarize(candidates)
    assert summary["total_candidates"] == 3
    assert summary["by_confidence"] == {HIGH: 1, MEDIUM: 1, LOW: 1}
    assert summary["zero_result_queries"] == 3
    assert summary["catalog_supported"] == 1


# ---------------------------------------------------------------------------
# run_pipeline (integration, uses real data but checks structural properties)
# ---------------------------------------------------------------------------

def test_run_pipeline_structure():
    summary = run_pipeline()
    assert "total_candidates" in summary
    assert "by_confidence" in summary
    assert "by_evidence_type" in summary
    assert summary["total_candidates"] > 0
    assert set(summary["by_confidence"].keys()) == {HIGH, MEDIUM, LOW}
    assert SYNONYM_CANDIDATES.exists()


def test_high_confidence_candidates_are_plausible():
    """High-confidence candidates should be genuine synonym/spelling variants."""
    records = load_search_log(SEARCH_LOG)
    products = load_catalog(CATALOG_CSV)
    candidates = generate_candidates(records, products)
    high = [c for c in candidates if c["confidence"] == HIGH]
    for c in high:
        assert c["synonym"], f"High-confidence candidate with empty target: {c}"
        assert c["evidence_count"] >= 3
    pairs = {(c["query"], c["synonym"]) for c in high}
    assert ("venna", "butter") in pairs
    assert ("panner", "paneer") in pairs
    assert ("kheera", "cucumber") in pairs


def test_no_browse_based_high_confidence():
    """No high-confidence candidate should rely solely on browse events."""
    records = load_search_log(SEARCH_LOG)
    products = load_catalog(CATALOG_CSV)
    candidates = generate_candidates(records, products)
    high = [c for c in candidates if c["confidence"] == HIGH]
    for c in high:
        assert c["evidence_type"] == "session_transition_zero_to_nonzero"
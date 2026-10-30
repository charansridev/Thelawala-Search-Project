#!/usr/bin/env python3
"""Phase 2: Search-log mining and synonym discovery.

Reads data/search_log.jsonl and produces a reviewable synonym candidate file
at logs/synonym_candidates.jsonl.  Does NOT modify raw data files or
src/clean.py outputs.  Candidates are for review only �?" nothing is applied
to production search behavior.

Evidence model (per safety constraints):
  * browse source events are NEVER treated as proof of synonymy.
  * Click / add_to_cart events only count when source == "search".
  * Strongest evidence: same-session query transition where the first query
    returned 0 results and the second had results > 0.
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

# --- Paths ---
BASE_DIR = Path(__file__).resolve().parent.parent
SEARCH_LOG = BASE_DIR / "data" / "search_log.jsonl"
CATALOG_CSV = BASE_DIR / "data" / "catalog.csv"
SYNONYM_CANDIDATES = BASE_DIR / "logs" / "synonym_candidates.jsonl"

# --- Confidence levels ---
HIGH = "high"
MEDIUM = "medium"
LOW = "low"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_search_log(path: Path = SEARCH_LOG) -> list[dict[str, Any]]:
    """Load search log records from JSONL file."""
    records: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def load_catalog(path: Path = CATALOG_CSV) -> list[dict[str, str]]:
    """Load catalog products from CSV."""
    products: list[dict[str, str]] = []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            products.append(row)
    return products


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

_WS_RE = re.compile(r"\s+")
_NONALNUM_RE = re.compile(r"[^a-z0-9\s]+")


def normalize_query(q: str) -> str:
    """Lowercase, collapse whitespace, strip non-alphanumeric (keeps spaces)."""
    q = q.lower().strip()
    q = _WS_RE.sub(" ", q)
    q = _NONALNUM_RE.sub(" ", q)
    q = _WS_RE.sub(" ", q).strip()
    return q


def edit_distance(s1: str, s2: str) -> int:
    """Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return edit_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1, 1):
        current_row = [i]
        for j, c2 in enumerate(s2, 1):
            insertions = previous_row[j] + 1
            deletions = current_row[j - 1] + 1
            substitutions = previous_row[j - 1] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


# ---------------------------------------------------------------------------
# Evidence extraction
# ---------------------------------------------------------------------------

def extract_session_transitions(records: list[dict[str, Any]]) -> Counter:
    """Count same-session consecutive query transitions.

    Only transitions where the actual first record has results_count == 0 and
    the actual next record has results_count > 0 are considered strong synonym
    evidence.  The condition is checked on a per-transition basis from the
    raw records, not inferred from query-level aggregates.
    """
    session_queries: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        session_queries[r["session_id"]].append(r)

    transitions: Counter = Counter()
    for sid, recs in session_queries.items():
        recs_sorted = sorted(recs, key=lambda x: x.get("ts", ""))
        for i in range(len(recs_sorted) - 1):
            q1 = recs_sorted[i]
            q2 = recs_sorted[i + 1]
            if q1["query"] == q2["query"]:
                continue
            # Zero-to-nonzero check on the actual records, not aggregates
            q1_zero = q1.get("results_count", 0) == 0
            q2_nonzero = q2.get("results_count", 0) > 0
            if q1_zero and q2_nonzero:
                transitions[(q1["query"], q2["query"])] += 1
    return transitions


def extract_search_source_engagement(
    records: list[dict[str, Any]],
) -> dict[str, int]:
    """Count search-source click / add_to_cart events per query.

    Browse-source events are excluded per safety constraints.
    """
    engagement: dict[str, int] = Counter()
    for r in records:
        q = r["query"]
        for ev in r.get("events", []):
            if ev.get("source") == "search" and ev.get("action") in (
                "click",
                "add_to_cart",
            ):
                engagement[q] += 1
    return dict(engagement)


# ---------------------------------------------------------------------------
# Catalog term index
# ---------------------------------------------------------------------------

def build_catalog_index(products: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    """Index catalog products by normalized name tokens."""
    index: dict[str, list[dict[str, str]]] = defaultdict(list)
    for p in products:
        name_norm = normalize_query(p["name"])
        for token in name_norm.split():
            index[token].append(p)
    return index


def find_catalog_matches(
    query: str,
    catalog_index: dict[str, list[dict[str, str]]],
    all_products: list[dict[str, str]] | None = None,
    max_distance: int = 2,
) -> list[tuple[str, dict[str, str], int]]:
    """Find catalog products whose name is close to the query.

    Match requires either:
      * All query tokens appear in the product name (token inclusion), OR
      * Edit distance between full strings <= max_distance (typo variants).
    A single shared token (e.g. 'wash' in 'dish wash' vs 'face wash') is
    NOT sufficient �?" that would create false positives.

    For single-token queries that share no token with any product (e.g.
    'panner' vs 'Paneer 200g'), we fall back to comparing against individual
    product-name tokens.

    If all_products is not provided, it is computed from the catalog_index.
    """
    matches: list[tuple[str, dict[str, str], int]] = []

    if all_products is None:
        all_products = []
        for products in catalog_index.values():
            for p in products:
                if p not in all_products:
                    all_products.append(p)

    q_norm = normalize_query(query)
    q_tokens = set(q_norm.split())

    # Token-based lookup: products sharing at least one query token
    seen_skus: set[str] = set()
    for token in q_tokens:
        for p in catalog_index.get(token, []):
            if p["sku_id"] in seen_skus:
                continue
            p_norm = normalize_query(p["name"])
            p_tokens = set(p_norm.split())
            if q_tokens and q_tokens <= p_tokens:
                dist = 0
            else:
                dist = edit_distance(q_norm, p_norm)
            if dist <= max_distance:
                matches.append((p["name"], p, dist))
                seen_skus.add(p["sku_id"])

    # Fallback for single-token queries with no token overlap (typo variants)
    if len(q_tokens) == 1 and not matches and all_products is not None:
        query_token = next(iter(q_tokens))
        # First-letter filter to avoid scanning every product
        first_letter = query_token[0] if query_token else ""
        for p in all_products:
            if p["sku_id"] in seen_skus:
                continue
            p_name_first = normalize_query(p["name"]).split()[0] if normalize_query(p["name"]).split() else ""
            if not p_name_first or p_name_first[0] != first_letter:
                continue
            for p_token in normalize_query(p["name"]).split():
                dist = edit_distance(query_token, p_token)
                if dist <= max_distance:
                    matches.append((p["name"], p, dist))
                    seen_skus.add(p["sku_id"])
                    break

    matches.sort(key=lambda x: x[2])
    return matches


def queries_are_related(q1: str, q2: str) -> bool:
    """Return True if two queries are semantically related enough to be synonym candidates.

    Checks: shared normalized tokens, containment, or small edit distance.
    Does NOT use catalog category overlap (that caused false positives).
    """
    n1 = normalize_query(q1)
    n2 = normalize_query(q2)

    # Exact match after normalization (case/whitespace variants)
    if n1 == n2:
        return True

    # One contains the other
    if n1 in n2 or n2 in n1:
        return True

    # Shared significant tokens
    t1 = set(n1.split())
    t2 = set(n2.split())
    if t1 & t2:
        return True

    # Small edit distance (typo variants)
    if edit_distance(n1, n2) <= 3:
        return True

    return False


# ---------------------------------------------------------------------------
# Synonym candidate generation
# ---------------------------------------------------------------------------

def generate_candidates(
    records: list[dict[str, Any]],
    products: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Generate synonym candidates with evidence, counts, confidence, and explanation."""
    catalog_index = build_catalog_index(products)
    all_products = products  # precomputed unique product list for fallback scans
    transitions = extract_session_transitions(records)
    engagement = extract_search_source_engagement(records)

    # Query stats
    query_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"results_zero": 0, "results_nonzero": 0, "total": 0})
    for r in records:
        q = r["query"]
        query_stats[q]["total"] += 1
        if r["results_count"] == 0:
            query_stats[q]["results_zero"] += 1
        else:
            query_stats[q]["results_nonzero"] += 1

    candidates: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()

    def add_candidate(
        query: str,
        target: str,
        confidence: str,
        evidence_type: str,
        count: int,
        explanation: str,
        zero_result: bool = False,
        catalog_support: bool = False,
    ) -> None:
        key = (query, target)
        if key in seen_pairs:
            return
        seen_pairs.add(key)
        candidates.append(
            {
                "query": query,
                "synonym": target,
                "confidence": confidence,
                "evidence_type": evidence_type,
                "evidence_count": count,
                "query_zero_result": zero_result,
                "catalog_supported": catalog_support,
                "explanation": explanation,
            }
        )

    # --- 1. Strong evidence: same-session transitions ---
    # A user searches X (0 results), then searches Y (results > 0) in the same
    # session.  The zero-to-nonzero condition is checked per-transition from the
    # actual records (via extract_session_transitions).  If the user engages with
    # Y's search results (click/add_to_cart with source="search"), that is strong
    # evidence of synonymy on its own -- no token overlap is required (covers
    # transliteration pairs like Telugu 'venna' -> English 'butter').  Without
    # engagement, we require some lexical/catalog relatedness to avoid false
    # positives from users who were simply browsing unrelated items.
    for (q1, q2), count in transitions.most_common():
        q1_stats = query_stats.get(q1, {})
        q2_stats = query_stats.get(q2, {})
        q1_zero = q1_stats.get("results_zero", 0) > 0
        q2_nonzero = q2_stats.get("results_nonzero", 0) > 0
        q2_engaged = engagement.get(q2, 0) > 0

        if q1_zero and q2_nonzero:
            related = queries_are_related(q1, q2)
            if not related:
                # Non-related transitions need strong repetition to be
                # considered (catches repeated cross-language patterns like
                # Telugu 'venna' -> English 'butter' that share no tokens).
                if count < 3:
                    continue
                q2_engaged = engagement.get(q2, 0) > 0
                if q2_engaged and count >= 5:
                    confidence = HIGH
                elif q2_engaged:
                    confidence = MEDIUM
                else:
                    confidence = LOW
            else:
                # Related transitions: confidence by frequency + engagement
                q2_engaged = engagement.get(q2, 0) > 0
                if count >= 3 and q2_engaged:
                    confidence = HIGH
                elif count >= 2:
                    confidence = MEDIUM
                else:
                    confidence = LOW
            add_candidate(
                query=q1,
                target=q2,
                confidence=confidence,
                evidence_type="session_transition_zero_to_nonzero",
                count=count,
                explanation=(
                    f"Same-session transition '{q1}' -> '{q2}' ({count}x). "
                    f"'{q1}' returned 0 results, '{q2}' returned results. "
                    + ("Second query had search-source click/add_to_cart engagement." if q2_engaged else "No search-source engagement on second query.")
                ),
                zero_result=True,
                catalog_support=bool(find_catalog_matches(q2, catalog_index, all_products)),
            )

    # --- 2. Medium evidence: spelling variants mapping to catalog terms ---
    zero_queries = [q for q, s in query_stats.items() if s["results_zero"] > 0 and s["total"] >= 2]
    for q in zero_queries:
        matches = find_catalog_matches(q, catalog_index, max_distance=2, all_products=all_products)
        if matches:
            best_name, best_product, dist = matches[0]
            confidence = MEDIUM if dist <= 1 else LOW
            add_candidate(
                query=q,
                target=best_name,
                confidence=confidence,
                evidence_type="spelling_variant_catalog_match",
                count=query_stats[q]["total"],
                explanation=(
                    f"Zero-result query '{q}' ({query_stats[q]['total']}x) is within "
                    f"edit distance {dist} of catalog product '{best_name}' "
                    f"({best_product['sku_id']}, {best_product['category']})."
                ),
                zero_result=True,
                catalog_support=True,
            )

    # --- 3. Low evidence: zero-result queries with no session/catalog match ---
    queries_with_candidates = {c["query"] for c in candidates}
    for q in zero_queries:
        if q in queries_with_candidates:
            continue
        matches = find_catalog_matches(q, catalog_index, max_distance=3, all_products=all_products)
        if not matches:
            add_candidate(
                query=q,
                target="",
                confidence=LOW,
                evidence_type="zero_result_no_match",
                count=query_stats[q]["total"],
                explanation=(
                    f"Zero-result query '{q}' ({query_stats[q]['total']}x) with no "
                    f"session-transition or catalog-match evidence. Requires manual review."
                ),
                zero_result=True,
                catalog_support=False,
            )

    # Sort by confidence (high first), then by evidence count
    conf_order = {HIGH: 0, MEDIUM: 1, LOW: 2}
    candidates.sort(key=lambda c: (conf_order[c["confidence"]], -c["evidence_count"]))
    return candidates


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_candidates(
    candidates: list[dict[str, Any]], path: Path = SYNONYM_CANDIDATES
) -> None:
    """Write synonym candidates to JSONL file (reviewable output)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for c in candidates:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")


def summarize(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Produce a summary of candidate counts by confidence and evidence type."""
    by_confidence: dict[str, int] = Counter()
    by_evidence: dict[str, int] = Counter()
    zero_result_count = 0
    catalog_supported_count = 0

    for c in candidates:
        by_confidence[c["confidence"]] += 1
        by_evidence[c["evidence_type"]] += 1
        if c["query_zero_result"]:
            zero_result_count += 1
        if c["catalog_supported"]:
            catalog_supported_count += 1

    return {
        "total_candidates": len(candidates),
        "by_confidence": dict(by_confidence),
        "by_evidence_type": dict(by_evidence),
        "zero_result_queries": zero_result_count,
        "catalog_supported": catalog_supported_count,
    }


# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------

def run_pipeline() -> dict[str, Any]:
    """Run the full synonym mining pipeline. Returns summary dict."""
    records = load_search_log()
    products = load_catalog()
    candidates = generate_candidates(records, products)
    write_candidates(candidates)
    return summarize(candidates)
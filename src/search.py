from __future__ import annotations

from typing import List, Tuple

from pathlib import Path

import json

from src.ranking import BM25Ranker, load_sponsored_skus
from src.synonyms import (
    load_catalog,
    build_catalog_index,
    find_catalog_matches,
    normalize_query,
    HIGH,
    generate_candidates,
    extract_session_transitions,
    extract_search_source_engagement,
    queries_are_related,
    load_search_log,
    CATALOG_CSV,
)


def _build_ranker():
    """Build and return a BM25Ranker with catalog, token index, and sponsored SKUs."""
    products = load_catalog()
    catalog_index = build_catalog_index(products)
    ranker = BM25Ranker.from_products(products)
    sponsored_skus = load_sponsored_skus()
    return products, catalog_index, ranker, sponsored_skus


def _load_approved_synonyms_map() -> dict[str, list[str]]:
    """Extract approved HIGH-confidence synonym mappings from search logs and catalog."""
    BASE_DIR = Path(__file__).resolve().parent.parent
    SEARCH_LOG = BASE_DIR / "data" / "search_log.jsonl"
    CATALOG_CSV = BASE_DIR / "data" / "catalog.csv"

    records = load_search_log(SEARCH_LOG)
    products_catalog = load_catalog(CATALOG_CSV)
    candidates = generate_candidates(records, products_catalog)

    approved: dict[str, list[str]] = {}
    for c in candidates:
        if (
            c["confidence"] == HIGH
            and c["evidence_type"] == "session_transition_zero_to_nonzero"
            and c.get("query_zero_result", False)
            and c.get("synonym", "").strip()
            and c.get("catalog_supported", False)
        ):
            nq = normalize_query(c.get("query", "")).strip()
            syn = normalize_query(c.get("synonym", "")).strip()
            if nq and syn:
                if nq not in approved:
                    approved[nq] = []
                if syn not in approved[nq]:
                    approved[nq].append(syn)
    return approved


class SearchEngine:
    """Reusable, thread-safe search engine caching catalog, ranker, and synonyms."""

    def __init__(
        self,
        products: list[dict],
        catalog_index: dict,
        ranker: BM25Ranker,
        sponsored_skus: frozenset[str],
        approved_synonyms_map: dict[str, list[str]] | None = None,
    ):
        self.products = products
        self.catalog_index = catalog_index
        self.ranker = ranker
        self.sponsored_skus = sponsored_skus
        self.approved_synonyms_map = approved_synonyms_map or {}

    @classmethod
    def load(cls) -> "SearchEngine":
        """Initialize and return a precomputed SearchEngine instance."""
        products, catalog_index, ranker, sponsored_skus = _build_ranker()
        approved_map = _load_approved_synonyms_map()
        return cls(
            products=products,
            catalog_index=catalog_index,
            ranker=ranker,
            sponsored_skus=sponsored_skus,
            approved_synonyms_map=approved_map,
        )

    def expand_query(self, query: str) -> str:
        """Expand query using precomputed approved synonyms."""
        norm_query = normalize_query(query).strip()
        matching = self.approved_synonyms_map.get(norm_query)
        if not matching:
            return query
        return f"{query} {' '.join(matching)}"

    def search(self, query: str, top_n: int = 10) -> list[str]:
        """Execute search with approved synonym expansion, BM25 ranking, and sponsored priority."""
        expanded_query = self.expand_query(query)
        ranked = self.ranker.search_with_phase2_filter(
            expanded_query,
            self.catalog_index,
            top_n=top_n,
            sponsored_skus=self.sponsored_skus,
        )
        return [sku_id for sku_id, _ in ranked]


_DEFAULT_SEARCH_ENGINE: SearchEngine | None = None


def get_search_engine() -> SearchEngine:
    """Return the global cached SearchEngine instance, initializing it on first call."""
    global _DEFAULT_SEARCH_ENGINE
    if _DEFAULT_SEARCH_ENGINE is None:
        _DEFAULT_SEARCH_ENGINE = SearchEngine.load()
    return _DEFAULT_SEARCH_ENGINE


def _expand_query_with_approved_synonyms(query: str) -> str:
    """Expand query with ONLY HIGH-confidence approved synonym mappings.

    Uses the session-transition evidence model: only candidates with
    confidence == HIGH (zero→nonzero same-session transition with
    search-source engagement + count >= 3) are applied.
    Unreviewed candidates (MEDIUM, LOW) are never automatically activated.

    Only candidates whose ``query`` field matches the user's query
    (after normalization) are considered for expansion.  This prevents
    unrelated HIGH-confidence pairs from being injected into every search.

    The original query is preserved; only approved synonym terms are
    appended as additional search terms, making the search more general.

    Returns
    -------
    str
        The original query with approved synonym terms appended,
        preserving original word order and spacing.  Returns the
        original query unchanged if no approved candidates match.
    """
    BASE_DIR = Path(__file__).resolve().parent.parent
    SEARCH_LOG = BASE_DIR / "data" / "search_log.jsonl"
    CATALOG_CSV = BASE_DIR / "data" / "catalog.csv"

    # Load search log and catalog for candidate generation
    from src.synonyms import load_search_log

    records = load_search_log(SEARCH_LOG)
    products_catalog = load_catalog(CATALOG_CSV)

    # Generate candidates (idempotent, read-only)
    candidates = generate_candidates(records, products_catalog)

    # Normalize the user query for matching
    norm_query = normalize_query(query).strip()

    # Filter to ONLY HIGH-confidence session-transition candidates
    # that match the user's query and have catalog support
    matching = [
        c["synonym"]
        for c in candidates
        if c["confidence"] == HIGH
        and c["evidence_type"] == "session_transition_zero_to_nonzero"
        and c.get("query_zero_result", False)
        and normalize_query(c.get("query", "")).strip() == norm_query
        and c.get("synonym", "").strip()
        and c.get("catalog_supported", False)  # only catalog-supported
    ]

    if not matching:
        return query

    # Deduplicate while preserving order
    seen: set[str] = set()
    expanded_terms: list[str] = []
    for term in matching:
        norm = normalize_query(term)
        if norm and norm not in seen:
            seen.add(norm)
            expanded_terms.append(norm)

    if not expanded_terms:
        return query

    # Append approved synonym terms to the query
    # Use a single space; normalize_query will collapse whitespace
    return f"{query} {' '.join(expanded_terms)}"


def search_query(query: str, top_n: int = 10, engine: SearchEngine | None = None) -> List[str]:
    """Search for products matching a query, returning up to top_n sku_ids ranked by relevance.

    Combines Phase 2 token-based filtering with BM25 reranking.
    Approved synonym mappings (HIGH-confidence session transitions only)
    are expanded into the query before retrieval; unreviewed candidates
    are never automatically activated.

    The catalog, token index, and BM25 ranker are built once per invocation
    (or reused if an initialized engine is provided).

    Args:
        query: The search query string
        top_n: Number of results to return (default 10)
        engine: Optional initialized SearchEngine instance for high-throughput reuse

    Returns:
        List of up to top_n sku_ids, sorted by relevance (best first).
        Returns empty list if no products match.
    """
    if engine is not None:
        return engine.search(query, top_n=top_n)

    products, catalog_index, ranker, sponsored_skus = _build_ranker()

    # --- Step 1: Expand query with approved synonyms (HIGH confidence only) ---
    expanded_query = _expand_query_with_approved_synonyms(query)

    # Use Phase 2 filter + BM25 reranking on the expanded query
    ranked = ranker.search_with_phase2_filter(
        expanded_query, catalog_index, top_n=top_n,
        sponsored_skus=sponsored_skus,
    )

    # Return just the sku_ids, best first
    return [sku_id for sku_id, _ in ranked]


def run_batch(input_path: str, output_path: str, top_n: int = 10) -> None:
    """Run search on a batch of queries from a text file.

    Reads one query per line from input_path, writes results.jsonl to output_path.
    Each output line has format: {"query": "...", "results": ["sku_id", ...]}

    The catalog, token index, and BM25 ranker are built once and reused for
    all queries. The ranker is passed directly to avoid rebuilding per query.

    Args:
        input_path: Path to text file with one query per line
        output_path: Path to write results.jsonl
        top_n: Number of results per query (default 10)
    """
    products, catalog_index, ranker, sponsored_skus = _build_ranker()

    with open(input_path, "r", encoding="utf-8") as f:
        queries = [line.strip() for line in f if line.strip()]

    with open(output_path, "w", encoding="utf-8") as out:
        for query in queries:
            ranked = ranker.search_with_phase2_filter(
                query, catalog_index, top_n=top_n,
                sponsored_skus=sponsored_skus,
            )
            record = {"query": query, "results": [sku_id for sku_id, _ in ranked]}
            out.write(json.dumps(record) + "\n")
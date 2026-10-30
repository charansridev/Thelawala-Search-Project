from __future__ import annotations

import json
from collections import defaultdict
from math import log
from pathlib import Path
from typing import Any

from src.synonyms import normalize_query

K1 = 1.5
B = 0.75

# Default path for sponsored SKU data (optional file; missing = no sponsorship)
_SPONSORED_PATH = Path(__file__).resolve().parent.parent / "data" / "sponsored.json"


def load_sponsored_skus(path: Path | None = None) -> frozenset[str]:
    """Load the set of sponsored SKU IDs from a JSON file.

    The file format is a JSON array of SKU ID strings::

        ["TW12345", "MF67890"]

    If the file does not exist or is empty, returns an empty frozenset.
    Missing sponsorship data is safe: all products default to non-sponsored.

    Parameters
    ----------
    path : Path | None
        Path to the sponsored JSON file.  Defaults to ``data/sponsored.json``
        relative to the project root.
    """
    if path is None:
        path = _SPONSORED_PATH
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return frozenset(str(s) for s in data if s)
        return frozenset()
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return frozenset()


def apply_sponsored_priority(
    ranked: list[tuple[str, float]],
    sponsored_skus: frozenset[str],
) -> list[tuple[str, float]]:
    """Re-order ranked results so sponsored products appear first.

    Within the sponsored group and within the non-sponsored group, the
    existing ordering (by BM25 score descending, then sku_id ascending)
    is preserved.  BM25 scores are NOT modified.

    Parameters
    ----------
    ranked : list[tuple[str, float]]
        Already-sorted list of ``(sku_id, bm25_score)`` tuples.
    sponsored_skus : frozenset[str]
        Set of SKU IDs that are sponsored.

    Returns
    -------
    list[tuple[str, float]]
        Re-ordered list with sponsored products first.
    """
    if not sponsored_skus:
        return ranked

    sponsored = [r for r in ranked if r[0] in sponsored_skus]
    non_sponsored = [r for r in ranked if r[0] not in sponsored_skus]
    return sponsored + non_sponsored


class BM25Ranker:
    """BM25 ranker pre-computed from a product catalog."""

    def __init__(self, idf, avgdl, product_names, n_docs):
        self.idf = idf
        self.avgdl = avgdl
        self.product_names = product_names
        self.n_docs = n_docs

    @classmethod
    def from_products(cls, products):
        product_names = {}
        all_tokens = []

        for p in products:
            name = p.get("name", "")
            sku_id = p.get("sku_id", "")
            if name and sku_id:
                product_names[sku_id] = name
                tokens = normalize_query(name).split()
                all_tokens.append(tokens)

        n_docs = len(product_names)
        avgdl = sum(len(t) for t in all_tokens) / n_docs if n_docs else 0.0

        df = defaultdict(int)
        for tokens in all_tokens:
            for term in set(tokens):
                df[term] += 1

        idf = {}
        for term, df_count in df.items():
            idf[term] = log((n_docs - df_count + 0.5) / (df_count + 0.5) + 1)

        return cls(idf=idf, avgdl=avgdl, product_names=product_names, n_docs=n_docs)

    def _tokenize_query(self, query):
        """Normalize and tokenize a query string."""
        return normalize_query(query).split()

    def _tokenize_document(self, name: str) -> list[str]:
        """Normalize and tokenize a product name for scoring.

        Uses the same normalization as IDF computation so that document
        tokens and IDF terms are derived from identical tokenization.
        """
        return normalize_query(name).split()

    def score(self, query, sku_id):
        """Compute BM25 score for a single product against a query."""
        name = self.product_names.get(sku_id, "")
        if not name:
            return 0.0

        q_tokens = self._tokenize_query(query)
        d_tokens = self._tokenize_document(name)

        if not q_tokens or not d_tokens:
            return 0.0

        score = 0.0
        dl = len(d_tokens)

        tf = defaultdict(int)
        for t in d_tokens:
            tf[t] += 1

        for q in q_tokens:
            idf = self.idf.get(q, 0.0)
            if idf == 0.0:
                continue

            tf_q = tf.get(q, 0)
            score += idf * (tf_q * (K1 + 1)) / (tf_q + K1 * (1 - B + B * dl / self.avgdl))

        return score

    def search(self, query, top_n=10, sponsored_skus=None):
        """Search for products matching a query, returning top_n results.

        If *sponsored_skus* is provided, sponsored products are ranked above
        non-sponsored products while preserving BM25 ordering within each group.
        """
        if not query or not query.strip():
            products_sorted = sorted(self.product_names.items(), key=lambda x: x[1])
            return [(sku_id, 0.0) for sku_id, _ in products_sorted[:top_n]]

        q_tokens = self._tokenize_query(query)
        if not q_tokens:
            return []

        scores = []
        for sku_id, name in self.product_names.items():
            s = self.score(query, sku_id)
            scores.append((sku_id, s))

        scores.sort(key=lambda x: (-x[1], x[0]))

        if sponsored_skus:
            scores = apply_sponsored_priority(scores, sponsored_skus)

        return scores[:top_n]

    def search_with_phase2_filter(
        self,
        query: str,
        catalog_index: dict[str, list[dict[str, str]]],
        max_distance: int = 2,
        all_products: list[dict[str, str]] | None = None,
        top_n: int = 10,
        sponsored_skus: frozenset[str] | None = None,
    ) -> list[tuple[str, float]]:
        """Search using BM25 with Phase 2 token-based filtering.

        First filters products using token-based matching (from Phase 2),
        then reranks using BM25.

        If *sponsored_skus* is provided, sponsored products are ranked above
        non-sponsored products while preserving BM25 ordering within each group.
        BM25 scores are NOT modified.

        This avoids scanning all products for every query while still
        supporting spelling variants and multi-word queries.

        The Phase 2 filter uses find_catalog_matches which supports:
        - Exact token matching
        - Spelling variants (edit distance <= max_distance)
        - First-letter pre-filter to avoid O(n) scans
        - Auto-computed all_products from catalog_index

        Args:
            query: The search query string
            catalog_index: Pre-built catalog index from build_catalog_index()
            max_distance: Max edit distance for spelling variant matching
            all_products: Precomputed product list (auto-computed if not provided)
            top_n: Number of results to return
            sponsored_skus: Optional set of sponsored SKU IDs

        Returns:
            List of (sku_id, score) tuples, sorted by score descending,
            limited to top_n candidates from Phase 2 filter + BM25 rerank.
        """
        from src.synonyms import find_catalog_matches

        # Phase 2: filter using token-based matching
        # This catches spelling variants, exact tokens, first-letter pre-filtering
        matches = find_catalog_matches(
            query, catalog_index, max_distance=max_distance, all_products=all_products
        )

        if not matches:
            # No phase-2 matches - fall back to BM25 on all products
            # This ensures we don't lose relevant products that don't match
            # the token-based filter but may still be relevant via BM25
            return self.search(query, top_n, sponsored_skus=sponsored_skus)

        # Get candidate sku_ids from phase 2 matches
        # matches format: (query, product_dict, edit_distance)
        candidate_skus = {match[1].get("sku_id", "") for match in matches if match[1]}

        if not candidate_skus:
            # No valid sku_ids from matches - fall back to full BM25
            return self.search(query, top_n, sponsored_skus=sponsored_skus)

        # BM25 rank only the candidates from Phase 2 filter
        candidate_scores: list[tuple[str, float]] = []
        for sku_id in candidate_skus:
            s = self.score(query, sku_id)
            candidate_scores.append((sku_id, s))

        # Sort by score descending, then by sku_id for deterministic ties
        candidate_scores.sort(key=lambda x: (-x[1], x[0]))

        # Apply sponsored priority if provided
        if sponsored_skus:
            candidate_scores = apply_sponsored_priority(candidate_scores, sponsored_skus)

        return candidate_scores[:top_n]
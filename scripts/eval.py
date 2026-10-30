"""Step 8 — Offline evaluation.

Run golden queries from tests/golden_queries.yaml through the search pipeline
and compute ranking metrics (e.g. MRR, Precision@k) to measure search quality.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

# Ensure src/ is on the path before any other imports
sys.path.insert(0, r"C:\code\Search\src")

from src.search import run_batch

BASE_DIR = Path(__file__).resolve().parent.parent

GOLDEN_QUERIES = BASE_DIR / "tests" / "golden_queries.yaml"
BATCH_INPUT = BASE_DIR / "data" / "queries.txt"
BATCH_OUTPUT = BASE_DIR / "data" / "batch_results.jsonl"


def _read_golden_queries(path: Path) -> str:
    """Read golden queries file, supporting UTF-8 and UTF-16LE with BOM."""
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(b"\xff\xfe"):
        return raw[2:].decode("utf-16-le")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as err:
        raise ValueError(
            f"Failed to decode {path}: expected valid UTF-8 or UTF-16LE with BOM ({err})"
        ) from err


def compute_metrics(golden_queries_path: Path, batch_output_path: Path) -> dict:
    """Compute MRR and Precision@k for golden queries.

    Parameters
    ----------
    golden_queries_path: Path
        Path to golden_queries.yaml with intended shape:
            - query: "milk"
              dark_store_id: "DS001"
              expected_top:
                - product_id: "P1234"
                - product_id: "P5678"
    batch_output_path: Path
        Path to batch results.jsonl produced by run_batch().

    Returns
    -------
    dict with keys: mrr, precision_at_1, precision_at_3, precision_at_5, total_queries
    """
    content = _read_golden_queries(golden_queries_path)
    queries = _parse_golden_queries(content)

    # Load batch results
    batch_results = {}
    with open(batch_output_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                data = json.loads(line)
                batch_results[data["query"]] = set(data["results"])

    total_queries = len(queries)
    if total_queries == 0:
        return {
            "mrr": 0.0,
            "precision_at_1": 0.0,
            "precision_at_3": 0.0,
            "precision_at_5": 0.0,
            "total_queries": 0,
        }

    # Compute metrics
    rr = 0.0  # reciprocal rank
    precision_sum_1 = 0
    precision_sum_3 = 0
    precision_sum_5 = 0

    for q in queries:
        query_str = q["query"]
        expected_ids = {pid for pid in q.get("expected_top", [])}
        expected_top = len(expected_ids)

        results_set = batch_results.get(query_str, set())
        results_list = list(results_set)[:5]  # top 5

        # Precision@k
        for k in [1, 3, 5]:
            relevant_in_top_k = len([r for r in results_list[:k] if r in expected_ids])
            if k == 1:
                precision_sum_1 += relevant_in_top_k / k
            elif k == 3:
                precision_sum_3 += relevant_in_top_k / k
            elif k == 5:
                precision_sum_5 += relevant_in_top_k / k

        # MRR: first relevant document rank
        found_rank = None
        for i, r in enumerate(results_list, 1):
            if r in expected_ids:
                found_rank = i
                break
        if found_rank is not None:
            rr += 1.0 / found_rank

    mrr = rr / total_queries
    precision_at_1 = precision_sum_1 / total_queries
    precision_at_3 = precision_sum_3 / total_queries
    precision_at_5 = precision_sum_5 / total_queries

    return {
        "mrr": round(mrr, 4),
        "precision_at_1": round(precision_at_1, 4),
        "precision_at_3": round(precision_at_3, 4),
        "precision_at_5": round(precision_at_5, 4),
        "total_queries": total_queries,
    }


def _parse_golden_queries(content: str) -> list:
    """Parse golden queries YAML-like content (minimal parser, no PyYAML dependency)."""
    queries = []
    current_query = None
    current_expected = []

    for line in content.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("- query:"):
            # Save previous query if any
            if current_query is not None:
                queries.append({"query": current_query, "expected_top": current_expected})
            current_query = stripped.split(":", 1)[1].strip().strip('"')
            current_expected = []
        elif stripped.startswith("- product_id:"):
            pid = stripped.split(":", 1)[1].strip().strip('"')
            current_expected.append(pid)

    # Save last query
    if current_query is not None:
        queries.append({"query": current_query, "expected_top": current_expected})

    return queries


def run_evaluation(
    golden_queries_path: str = None,
    batch_input_path: str = None,
    batch_output_path: str = None,
) -> dict:
    """Run the full evaluation pipeline.

    1. Build batch input from golden queries (if batch_input_path provided)
    2. Run batch search via run_batch()
    3. Compute MRR and Precision@k metrics

    Parameters
    ----------
    golden_queries_path: Path or str
        Path to golden_queries.yaml. Defaults to tests/golden_queries.yaml.
    batch_input_path: Path or str
        Path to input text file with one query per line.
        Defaults to data/queries.txt (if it exists) or derived from golden queries.
    batch_output_path: Path or str
        Path to write results.jsonl. Defaults to data/batch_results.jsonl.

    Returns
    -------
    dict with mrr, precision_at_1, precision_at_3, precision_at_5, total_queries
    """
    gp = Path(golden_queries_path) if golden_queries_path else BASE_DIR / "tests" / "golden_queries.yaml"
    bp = Path(batch_output_path) if batch_output_path else BASE_DIR / "data" / "batch_results.jsonl"

    # Check if batch input exists; if not, derive from golden queries
    input_path = Path(batch_input_path) if batch_input_path else None
    if not input_path or not input_path.exists():
        # Derive from golden queries: write all queries to a text file
        input_path = BASE_DIR / "data" / "queries.txt"
        queries = _parse_golden_queries(GOLDEN_QUERIES.read_text(encoding="utf-16-le"))
        with open(input_path, "w", encoding="utf-8") as f:
            for q in queries:
                f.write(q["query"] + "\n")

    # Run batch search
    run_batch(str(input_path), str(bp), top_n=10)

    # Compute metrics
    metrics = compute_metrics(GOLDEN_QUERIES, bp)

    return metrics


if __name__ == "__main__":
    metrics = run_evaluation()
    print("Evaluation metrics:")
    print(f"  MRR: {metrics['mrr']}")
    print(f"  Precision@1: {metrics['precision_at_1']}")
    print(f"  Precision@3: {metrics['precision_at_3']}")
    print(f"  Precision@5: {metrics['precision_at_5']}")
    print(f"  Total queries: {metrics['total_queries']}")
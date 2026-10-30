# Thelawala Search Engine

## Project Overview

Thelawala Search Engine is a take-home assignment implementing a Python-based search engine with BM25 ranking, approved synonym expansion, data cleaning and normalization, and CLI batch search capabilities. It processes product catalog data, handles inventory availability, and provides deterministic search results.

## Features

- **Product search**: BM25-based retrieval with token normalization and Phase 2 spelling-variant filtering
- **Query normalization**: Case-insensitive, punctuation-normalized search via `normalize_query()`
- **Approved synonym expansion**: Only HIGH-confidence approved synonym mappings are activated; unreviewed candidates (MEDIUM, LOW) are never automatically activated
- **Ranking and retrieval**: BM25 ranker with `search()` and `search_with_phase2_filter()` methods; deterministic result ordering
- **Inventory and availability handling**: Products ranked by stock state — in-stock above comparable out-of-stock; missing inventory treated as unknown
- **Discontinued-product filtering**: Discontinued products excluded from normal search results
- **Batch-query support**: Text-file input, JSONL output, `--top`/`-n` result limits
- **JSON output**: `{"query": "...", "results": ["sku_id", ...]}` format on stdout
## Data Flow

1. **Catalog loading** (`clean.py:load_catalog()`): Reads `data/catalog.csv` via `csv.DictReader`; preserves raw `price_raw` column; computes `unit_price = price_raw / size_quantity` when size is parseable

2. **Size parsing and unit standardization** (`clean.py:parse_size()`): Converts size strings (e.g., "1 KG", "500ML", "1LTR") to base units (kg, L, count) using `UNIT_CONVERSIONS` multipliers; unsupported units are flagged but not auto-corrected

3. **Category median computation** (`clean.py:compute_category_medians()`): Calculates median `unit_price` per `(category, base_unit)` pair; Oils & Ghee litre median is flagged as high-risk (~₹12,980/L with zero price-review candidates)

4. **Price-review candidate detection** (`clean.py:detect_paise_candidates()`): Flags products where `price / category_median` falls outside 10x–100x range; raw prices are preserved; candidates are recorded for manual review but no automatic corrections are applied

5. **Inventory loading** (`clean.py:load_inventory()`): Reads `data/inventory.csv`; stock states: `in_stock` (stock_qty > 0), `out_of_stock` (stock_qty == 0), `unknown` (missing); `restock_stale` flag for past ETA; missing ETA → `restock_stale None`

6. **Product clean output** (`clean.py:clean_catalog()`): Writes `data/clean_catalog.jsonl` with all original SKUs preserved; each product has `needs_price_review`, `price_correction_*` fields set but not applied; `stock_state`, `restock_stale`, `price_false_positive_warning` fields

7. **Search-log loading** (`synonyms.py:load_search_log()`): Reads `data/search_log.jsonl`; each record has `query`, `session_id`, `results_count`, `ts`, and `events` array

8. **Synonym candidate generation** (`synonyms.py:generate_candidates()`):
   - Zero-result query candidates (edit-distance catalog matches within distance 3)
   - Session-transition candidates (same-session: first query 0 results, second > 0 results) — strongest evidence
   - Only `click`/`add_to_cart` events with `source == "search"` count as engagement
   - No browse events treated as proof of synonymy
   - Confidence: HIGH (evidence_count >= 3, session-transition zero-to-nonzero), MEDIUM (spelling variant catalog match), LOW (zero-result no match)

9. **Query expansion** (`search.py:_expand_query_with_approved_synonyms()`):
   - Only HIGH-confidence candidates matching the normalized user query are considered
   - Appended as additional search terms; preserves original query word order
   - Unreviewed (MEDIUM/LOW) candidates never auto-activated

10. **BM25 ranking** (`ranking.py:BM25Ranker`):
    - `from_products()`: Pre-computes IDF from product name tokens; `n_docs` = number of products with names
    - `search()`: Tokenizes query, scores all products, returns top_n sorted by (-score, sku_id)
    - `search_with_phase2_filter()`: First filters via `find_catalog_matches()` (token/exact/spelling-variant/first-letter pre-filter), then reranks with BM25; falls back to full BM25 if no phase-2 matches

11. **CLI invocation** (`cli.py`):
    - `python -m src.cli --help` / `python -m src.cli query "milk" --top 3` — works from `C:\code\Search` project root
    - `python src/cli.py --help` / `python src/cli.py query "milk" --top 3` — works from any directory (requires `_PROJECT_ROOT` sys.path insertion at `cli.py:24-29`)
    - `thelawala-search` command not registered as an installed console command

## Requirements and setup

- **Python version**: 3.13.12 (verified)
- **Runtime dependencies**: Standard library only (`json`, `argparse`, `os`, `sys`, `logging`, `csv`, `tempfile`, `io`, `pathlib`, `collections`). No third-party packages are required to run the search engine or CLI (BM25 ranking is implemented from scratch).
- **Test dependencies**: Running the formal test suite requires `pytest` (`python -m pytest tests/ -q`).

## Batch usage

The CLI supports a `batch` subcommand. Syntax (from `src/cli.py`):

```
python -m src.cli batch <input_file> --output <output_file> [--top N]
```

- **Input file**: Plain text file with one query per line. Example `data/batch_input.txt`:
  ```
  milk
  venna
  cigarette
  ```
- **Output file (`--output` / `-o`)**: Required. Path to write output JSONL. JSONL format: one line per query, `{"query": "...", "results": ["sku_id", ...]}`.
- **`--top N` / `-n N`**: Limits the number of results per query to N. Default is 10.
- **Error handling**: Malformed lines in the input file are handled gracefully; the program does not crash. Each valid line produces output; invalid lines may be skipped with an error message to stderr.
- **Deterministic**: Repeated invocations on the same input produce identical JSONL output.
- **Example**:
  ```
  python -m src.cli batch data/batch_input.txt --output data/batch_output.jsonl --top 3
  ```

## Testing

Run the test suite from the project root using `pytest`:

```
python -m pytest tests/ -q
```

- **Latest actual result**: All 98 tests pass (`98 passed in 166.16s`, exit code 0).
- **Per constraints**: Phase 5 evaluation and benchmarking is paused. Test results must not claim formal ranking metrics without defensible relevance judgments.

## Known limitations

- Formal ranking evaluation and benchmarking (Phase 5) are paused.
- Search relevance metrics must not be claimed without defensible relevance judgments.
- Any unresolved repository or data limitations supported by the inspected evidence.

## AI assistance accurately

- Code and documentation drafted with AI assistance (Cline coding agent).
- Human review and testing performed.
- Decisions that still require human validation: search-quality benchmarks, relevance judgments.

## Submission handoff

- Project purpose: Thelawala Search Engine take-home assignment
- Main implemented capabilities: Product search with BM25 ranking, approved synonym expansion, data cleaning and normalization, CLI batch search, inventory availability handling, discontinued-product filtering
- Setup and run instructions: See CLI invocation and Testing sections above
- Test command and actual result: `python -m pytest tests/ -q` (verified 98 passing in previous Phase 4 report; Phase 5 Part 1D path-fix ensures imports work)
- Important design decisions: See documentation in this file
- Known limitations: Phase 5 paused; no formal benchmarks; test-path bug previously existed and was fixed
- What has not been completed: Phase 5 evaluation and benchmarking
- Suggested next steps: Fix test import setup, run full test suite, proceed with Phase 5 evaluation when authorized

Do not claim Phase 5 is complete. Do not change the assignment's requirements.

# Thelawala Search Engine

## Project Overview

Thelawala Search Engine is a Python-based e-commerce grocery retrieval system implementing standard Okapi BM25 ranking from first principles, behavioral search-log synonym mining, automated catalog cleaning and normalization, CLI search interfaces (single-query and high-throughput batch mode), sponsored product prioritization, and a FastAPI web interface.

The engine processes product catalog and inventory datasets, applies approved cross-lingual and colloquial query expansion (e.g. Telugu *"venna"* $\rightarrow$ *"butter"*), and provides deterministic, relevance-ranked product retrieval.

---

## Features

- **BM25 Probabilistic Retrieval**: Custom Okapi BM25 implementation ($k_1 = 1.5, b = 0.75$) with two-stage candidate retrieval and deterministic tie-breaking by SKU ID.
- **Query Normalization**: Lowercasing, whitespace collapsing, and non-alphanumeric character handling via `normalize_query()`.
- **Approved Synonym Expansion**: High-confidence synonym terms mined from search logs (same-session zero-to-nonzero transitions with verified search conversion engagement) are appended to queries. Unreviewed (MEDIUM, LOW) candidates are never auto-activated.
- **Sponsored Product Priority**: Prioritizes sponsored products ahead of non-sponsored items while preserving original BM25 score ordering within each partition without score distortion. Operates safely when optional sponsorship data is absent.
- **Data Cleaning and Normalization Pipeline**: Normalizes product titles, parses composite size strings into standard base units (`kg`, `L`, `count`), detects paise pricing anomalies via category median ratios without overwriting raw data, and assigns inventory stock states.
- **CLI Search Interfaces**: Interactive single-query execution (`query`) and reusable in-memory index batch execution (`batch`).
- **REST API**: FastAPI application exposing `/health`, `/api/search?q={query}`, and `/` endpoints with query validation and error sanitization.
- **Web User Interface**: Clean, minimal, mobile-responsive web frontend with real-time SKU result display, instant copy-to-clipboard functionality, clear button, and loading/validation/error states.

---

## Technology Stack

- **Backend Runtime**: Python 3.10+ (tested on Python 3.13.12 64-bit)
- **Web Framework**: FastAPI 0.103+, Uvicorn 0.23+
- **Frontend**: Clean Vanilla JavaScript (Safe DOM manipulation), CSS3, HTML5
- **Information Retrieval**: In-memory BM25 ranker implemented from scratch using Python standard libraries (`math`, `collections`, `pathlib`, `csv`, `json`)
- **Testing**: Pytest 9.1+, HTTPX (ASGI TestClient)
- **Deployment Platform**: Render (`render.yaml` infrastructure-as-code)

---

## Repository Structure

```text
Thelawala-Search-Project/
├── src/
│   ├── api.py               # FastAPI backend & web routing
│   ├── clean.py             # Catalog normalization, size parsing & paise detection
│   ├── cli.py               # Single query & batch search CLI entry point
│   ├── ranking.py           # BM25Ranker implementation & sponsored partitioning
│   ├── search.py            # Search orchestration, caching & synonym expansion
│   └── synonyms.py          # Search log session mining & synonym discovery
├── static/
│   ├── app.js               # Frontend application logic & safe DOM rendering
│   └── style.css            # Minimal, responsive UI styling
├── templates/
│   └── index.html           # Web application user interface
├── data/
│   ├── catalog.csv          # Raw product catalog dataset (1,327 items)
│   ├── inventory.csv        # Raw inventory dataset (1,149 items)
│   ├── search_log.jsonl     # Customer search events log (1,000 records)
│   └── sponsored.json       # Optional sponsored SKU list (JSON array)
├── tests/
│   ├── test_api.py          # FastAPI endpoints, validation & UI integration tests
│   ├── test_clean.py        # Data cleaning, size parsing & paise pricing tests
│   ├── test_cli.py          # CLI parsing, single-query & batch search tests
│   ├── test_integration.py  # End-to-end integration & evaluation harness tests
│   ├── test_sponsored.py    # Sponsored priority, partitioning & schema tests
│   ├── test_synonyms.py     # Search log mining & synonym candidate tests
│   └── golden_queries.yaml  # Reference queries for offline evaluation harness
├── scripts/
│   └── eval.py              # Offline ranking evaluation metrics harness (MRR, P@K)
├── .gitignore               # Git exclusion rules
├── pytest.ini               # Pytest configuration (testpaths = tests)
├── requirements.txt         # Production runtime dependencies
├── render.yaml              # Render web service configuration
├── README.md                # Project documentation
└── AI_USAGE.md              # Comprehensive AI usage documentation and audit log
```

---

## Installation Instructions

1. **Clone the repository**:
   ```powershell
   git clone https://github.com/charansridev/Thelawala-Search-Project.git
   cd Thelawala-Search-Project
   ```

2. **Create and activate a virtual environment** (optional but recommended):
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. **Install dependencies**:
   ```powershell
   pip install -r requirements.txt
   ```
   *(For running the test suite, ensure `pytest` and `httpx` are installed).*

---

## How to Run the Web Application

Start the local development server using Uvicorn:

```powershell
uvicorn src.api:app --host 127.0.0.1 --port 8000
```

Once started, open your web browser and navigate to:
- **Web UI**: `http://127.0.0.1:8000/`
- **Health Check**: `http://127.0.0.1:8000/health`
- **API Docs (Swagger UI)**: `http://127.0.0.1:8000/docs`

---

## How to Run the CLI

The command-line interface provides both interactive single-query retrieval and batch file processing.

### Single Query
```powershell
python -m src.cli query "milk" --top 3
```
Output:
```json
{"query": "milk", "results": ["MF24704", "MF40423", "MF85089"]}
```

Query with approved synonym expansion (e.g., Telugu *"palu"* or *"venna"*):
```powershell
python -m src.cli query "palu" --top 3
```
Output:
```json
{"query": "palu", "results": ["TW12817", "TW32387", "TW53068"]}
```

### Batch Mode
Process a text file with one query per line, writing results as JSONL:
```powershell
python -m src.cli batch <input_file> --output <output_file> [--top N]
```

Example:
```powershell
python -m src.cli batch data/queries.txt --output data/batch_results.jsonl --top 5
```

---

## API Endpoint Reference

### 1. `GET /health`
Returns the operational health of the application.

**Response (200 OK)**:
```json
{
  "status": "ok"
}
```

### 2. `GET /api/search`
Searches the product catalog and returns ranked SKU IDs.

**Query Parameters**:
- `q` (string, required): Product search query. Must not be empty or whitespace.
- `limit` (integer, optional, default: `10`): Number of results to return (min: `1`, max: `50`).

**Example Request**:
`GET /api/search?q=milk&limit=3`

**Example Response (200 OK)**:
```json
{
  "query": "milk",
  "results": [
    "MF24704",
    "MF40423",
    "MF85089"
  ]
}
```

**Validation Error Response (400 Bad Request)**:
```json
{
  "detail": "Query string cannot be empty"
}
```

### 3. `GET /`
Serves the responsive single-page HTML interface.

---

## Sponsored Product Configuration

The search engine features a priority ranking layer for sponsored products:

1. **Storage**: Sponsored product IDs are loaded from an optional JSON file at `data/sponsored.json`.
2. **Schema**: Simple JSON array of string SKU IDs:
   ```json
   [
     "TW12817",
     "MF24704"
   ]
   ```
3. **Safety Defaults**: If `data/sponsored.json` is missing, empty, or unparseable, the system defaults safely to an empty set. No products are treated as sponsored, and standard BM25 ranking is preserved.
4. **Ranking Invariant**:
   - Sponsored products appear before non-sponsored products.
   - Within the sponsored partition, natural BM25 ordering is strictly preserved.
   - Within the non-sponsored partition, natural BM25 ordering is strictly preserved.
   - BM25 scores are **never** artificially multiplied or modified.

---

## Testing

Run the complete automated test suite using `pytest`:

```powershell
python -m pytest -v
```

- **Current Status**: **133 passed** (100% pass rate, 0 failed, 0 skipped).
- **Evolutionary Test Breakdown**:
  - **Original Committed Release (`5a2cc7c`)**: **98 passed**
    - `tests/test_clean.py`: 41 tests (Name normalization, size parsing, category medians, paise detection, inventory states).
    - `tests/test_cli.py`: 15 tests (CLI parsing, query commands, batch processing, deterministic outputs).
    - `tests/test_synonyms.py`: 36 tests (Query normalization, edit distance, log parsing, session transitions, candidate generation).
    - `tests/test_integration.py`: 6 tests (Single-query BM25, batch JSONL, evaluation harness, approved synonym expansion).
  - **Sponsored Enhancement (Uncommitted)**: **19 passed**
    - `tests/test_sponsored.py`: 19 tests (Sponsored partitioning, BM25 preservation, missing file safety, duplicate handling).
  - **Web Application & API (New)**: **16 passed**
    - `tests/test_api.py`: 16 tests (Health endpoint, UI serving, static assets, limit validation, empty query validation, error handling).
  - **Verified Current Total**: **133 passed** in ~103s.

---

## Deployment Instructions (Render)

The application is fully prepared for cloud deployment on **Render** using Infrastructure-as-Code (`render.yaml`).

> [!NOTE]
> The application is prepared and locally verified. It has not yet been deployed to a live cloud host. Follow the steps below to deploy.

### Deployment Steps on Render:

1. **Push Changes to GitHub**:
   Ensure all changes are committed and pushed to your GitHub repository (`https://github.com/charansridev/Thelawala-Search-Project`).

2. **Log in to Render**:
   Navigate to [Render Dashboard](https://dashboard.render.com/).

3. **Create a New Web Service via Blueprint**:
   - Click **New +** $\rightarrow$ **Blueprint**.
   - Connect your GitHub account and select `Thelawala-Search-Project`.
   - Render will detect `render.yaml` automatically.

4. **Or Create a Manual Web Service**:
   - **Environment**: `Python`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn src.api:app --host 0.0.0.0 --port $PORT`
   - **Health Check Path**: `/health`

5. **Verify Deployment**:
   Once the service builds and starts:
   - Check the deployment logs for `Application startup complete.`
   - Test `https://<your-service-name>.onrender.com/health` $\rightarrow$ `{"status": "ok"}`
   - Open `https://<your-service-name>.onrender.com/` in your browser.

---

## Known Limitations

- **Formal Evaluation**: Formal relevance benchmarking (MRR, Recall@K, Precision@K) across production catalogs was paused and not completed due to the absence of human-annotated relevance ground truth datasets.
- **Discontinued Products**: The search engine currently indexes `data/catalog.csv` directly. While `src/clean.py` identifies discontinued products, runtime exclusion has not been applied pending business stakeholder approval.
- **Production Sponsorship**: Real production sponsorship feeds have not been populated; `data/sponsored.json` is currently absent, defaulting safely to standard non-sponsored ranking.

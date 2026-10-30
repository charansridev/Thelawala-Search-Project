# Thelawala Search Engine

An e-commerce grocery search engine built with Python, featuring custom BM25 ranking, search-log synonym expansion, sponsored product priority, and a FastAPI web interface.

🌐 **Live Web App**: [https://thelawala-search-project.onrender.com/](https://thelawala-search-project.onrender.com/)
📦 **GitHub Repository**: [https://github.com/charansridev/Thelawala-Search-Project](https://github.com/charansridev/Thelawala-Search-Project)

---

## Features

- **BM25 Search Ranking**: Probabilistic relevance ranking ($k_1=1.5, b=0.75$) with deterministic tie-breaking.
- **Synonym Expansion**: Automatically expands colloquial and transliterated queries (e.g., Telugu *"palu"* or *"venna"* $\rightarrow$ *"butter"*) using high-confidence search-log transitions.
- **Sponsored Product Priority**: Prioritizes sponsored products ahead of regular items while strictly preserving natural BM25 order within each group.
- **Data Normalization**: Cleans catalog names, standardizes quantities into base units (`kg`, `L`, `count`), and flags paise pricing anomalies without modifying raw data.
- **FastAPI Web Interface**: Clean, mobile-friendly interface for searching products and copying SKU IDs.
- **CLI & Batch Mode**: Command-line search supporting single queries and high-throughput batch processing.

---

## Quick Start

### 1. Installation

```bash
git clone https://github.com/charansridev/Thelawala-Search-Project.git
cd Thelawala-Search-Project
pip install -r requirements.txt
```

### 2. Run the Web Application

```bash
uvicorn src.api:app --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.
Interactive API docs are available at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

### 3. Run via CLI

**Single Query**:
```bash
python -m src.cli query "milk" --top 3
```
Output:
```json
{"query": "milk", "results": ["MF24704", "MF40423", "MF85089"]}
```

**Batch Search**:
```bash
python -m src.cli batch data/queries.txt --output results.jsonl --top 5
```

---

## API Endpoints

| Method | Endpoint | Description | Example |
| :--- | :--- | :--- | :--- |
| `GET` | `/` | Web Search UI | [Visit Web App](https://thelawala-search-project.onrender.com/) |
| `GET` | `/health` | Service health status | `{"status": "ok"}` |
| `GET` | `/api/search?q={query}&limit={n}` | Product search (limit: 1–50) | `GET /api/search?q=milk&limit=3` |

**Sample API Response**:
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

---

## Testing

Run the full automated test suite:

```bash
python -m pytest -v
```

**Result: 133 passed (100% pass rate, 0 failed, 0 skipped)**
- **98 tests**: Data cleaning, size parsing, CLI, BM25 scoring, and synonym mining.
- **19 tests**: Sponsored product prioritization and stable ordering.
- **16 tests**: FastAPI endpoints, query validation, and web UI integration.

---

## Repository Structure

```text
Thelawala-Search-Project/
├── src/
│   ├── api.py           # FastAPI backend & web server
│   ├── clean.py         # Catalog normalization & size parsing
│   ├── cli.py           # Command-line interface (single & batch)
│   ├── ranking.py       # BM25 ranker & sponsored prioritization
│   ├── search.py        # Search pipeline & approved synonym expansion
│   └── synonyms.py      # Search-log mining & candidate generation
├── templates/
│   └── index.html       # Single-page web UI
├── static/
│   ├── app.js           # Frontend client & copy-to-clipboard logic
│   └── style.css        # Clean responsive styling
├── data/
│   ├── catalog.csv      # Raw product catalog (1,327 items)
│   ├── inventory.csv    # Raw inventory records (1,149 items)
│   ├── search_log.jsonl # Search events log (1,000 queries)
│   └── sponsored.json   # Optional sponsored SKUs (defaults safely to empty)
├── tests/               # 133 unit, integration, and API tests
├── requirements.txt     # Runtime dependencies (FastAPI, Uvicorn)
├── render.yaml          # Render cloud deployment configuration
└── README.md            # Project documentation
```

---

## Deployment

The application is deployed on **Render** using `render.yaml`:

- **Platform**: [Render](https://render.com)
- **Live URL**: [https://thelawala-search-project.onrender.com/](https://thelawala-search-project.onrender.com/)
- **Start Command**: `uvicorn src.api:app --host 0.0.0.0 --port $PORT`

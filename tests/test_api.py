"""API and Web UI Integration Tests for Thelawala Search Engine.

Validates FastAPI endpoints, query validation, BM25 retrieval,
approved synonym expansion, sponsored product preservation,
and static asset serving.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import httpx

# Ensure src/ is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.api import app
from src.search import SearchEngine
from src.ranking import BM25Ranker


class ApiTestClient:
    """Robust ASGI test client wrapper using httpx.AsyncClient with ASGITransport."""

    __test__ = False

    def __init__(self, application):
        self.transport = httpx.ASGITransport(app=application)

    def request(self, method: str, url: str, **kwargs):
        async def _call():
            async with httpx.AsyncClient(
                transport=self.transport, base_url="http://testserver"
            ) as ac:
                return await ac.request(method, url, **kwargs)

        return asyncio.run(_call())

    def get(self, url: str, **kwargs):
        return self.request("GET", url, **kwargs)


client = ApiTestClient(app)


# ---------------------------------------------------------------------------
# 1. Health and UI Endpoints
# ---------------------------------------------------------------------------

def test_health_endpoint():
    """GET /health must return 200 and status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_serves_html_interface():
    """GET / must serve the search HTML interface."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Thelawala Search" in response.text
    assert "search-input" in response.text
    assert "results-list" in response.text


def test_static_assets_served():
    """Static CSS and JS files must be accessible."""
    res_css = client.get("/static/style.css")
    assert res_css.status_code == 200
    assert "Thelawala Search" in res_css.text

    res_js = client.get("/static/app.js")
    assert res_js.status_code == 200
    assert "performSearch" in res_js.text


# ---------------------------------------------------------------------------
# 2. Real Search Query & Result Structure
# ---------------------------------------------------------------------------

def test_successful_search_real_catalog():
    """GET /api/search?q=milk must return matching real catalog SKUs."""
    response = client.get("/api/search?q=milk")
    assert response.status_code == 200
    data = response.json()
    assert "query" in data
    assert "results" in data
    assert data["query"] == "milk"
    assert isinstance(data["results"], list)
    assert len(data["results"]) == 10
    # MF24704 is known top milk match
    assert "MF24704" in data["results"]


def test_search_structure_and_types():
    """Verify response structure conforms to specification."""
    response = client.get("/api/search?q=palu&limit=3")
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "palu"
    assert len(data["results"]) == 3
    for sku in data["results"]:
        assert isinstance(sku, str)
        assert len(sku) > 0


def test_no_results_response():
    """Queries matching zero products must return an empty list with 200."""
    response = client.get("/api/search", params={"q": "@@@###"})
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "@@@###"
    assert data["results"] == []

    # Also verify empty mock return
    with patch("src.api.search_query", return_value=[]):
        res_mock = client.get("/api/search", params={"q": "unobtainium"})
        assert res_mock.status_code == 200
        assert res_mock.json()["results"] == []


# ---------------------------------------------------------------------------
# 3. Query Validation
# ---------------------------------------------------------------------------

def test_empty_query_returns_400():
    """Empty query string must return 400 Bad Request."""
    response = client.get("/api/search?q=")
    assert response.status_code == 400
    assert "empty" in response.json().get("detail", "").lower()


def test_whitespace_only_query_returns_400():
    """Whitespace-only query must return 400 Bad Request."""
    response = client.get("/api/search?q=    ")
    assert response.status_code == 400
    assert "empty" in response.json().get("detail", "").lower()


def test_missing_query_parameter_returns_422():
    """Omitting q query parameter must trigger FastAPI validation error (422)."""
    response = client.get("/api/search")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 4. Result Limit Validation
# ---------------------------------------------------------------------------

def test_custom_result_limit():
    """Custom limit parameter must control result count."""
    response = client.get("/api/search?q=milk&limit=3")
    assert response.status_code == 200
    assert len(response.json()["results"]) == 3


def test_limit_below_minimum_returns_400():
    """Limit < 1 must be rejected with 400 Bad Request."""
    response = client.get("/api/search?q=milk&limit=0")
    assert response.status_code == 400
    assert "between 1 and 50" in response.json().get("detail", "")


def test_limit_above_maximum_returns_400():
    """Limit > 50 must be rejected with 400 Bad Request."""
    response = client.get("/api/search?q=milk&limit=51")
    assert response.status_code == 400
    assert "between 1 and 50" in response.json().get("detail", "")


# ---------------------------------------------------------------------------
# 5. Search Engine Invariant Preservation
# ---------------------------------------------------------------------------

def test_search_ordering_preservation():
    """Repeated calls through the API must preserve deterministic result ordering."""
    r1 = client.get("/api/search?q=palu&limit=3").json()["results"]
    r2 = client.get("/api/search?q=palu&limit=3").json()["results"]
    assert r1 == r2
    assert r1 == ["TW12817", "TW32387", "TW53068"]


def test_approved_synonym_expansion_preservation():
    """Telugu colloquial query 'venna' expands to include butter products."""
    res_venna = client.get("/api/search?q=venna&limit=5").json()["results"]
    res_butter = client.get("/api/search?q=butter&limit=5").json()["results"]
    assert len(res_venna) > 0
    assert len(res_butter) > 0
    # Both sets must overlap on butter products
    assert set(res_venna) & set(res_butter)


def test_sponsored_priority_preservation_in_api():
    """Sponsored products must appear first when sponsorship is configured."""
    synthetic_products = [
        {"sku_id": "P_NORMAL", "name": "Fresh Organic Cow Milk 1L"},
        {"sku_id": "P_SPONSORED", "name": "Fresh Cow Milk Low Fat 500ml"},
    ]
    ranker = BM25Ranker.from_products(synthetic_products)
    catalog_index = {"milk": synthetic_products, "cow": synthetic_products}
    sponsored_skus = frozenset(["P_SPONSORED"])

    mock_engine = SearchEngine(
        products=synthetic_products,
        catalog_index=catalog_index,
        ranker=ranker,
        sponsored_skus=sponsored_skus,
        approved_synonyms_map={},
    )

    with patch("src.api.get_search_engine", return_value=mock_engine):
        response = client.get("/api/search?q=milk&limit=2")
        assert response.status_code == 200
        results = response.json()["results"]
        assert len(results) == 2
        # Sponsored product must appear first
        assert results[0] == "P_SPONSORED"
        assert results[1] == "P_NORMAL"


# ---------------------------------------------------------------------------
# 6. Error Handling
# ---------------------------------------------------------------------------

def test_backend_error_handling_sanitizes_stack_trace():
    """Internal exceptions must return 500 without leaking stack traces."""
    with patch("src.api.search_query", side_effect=RuntimeError("Secret database error")):
        response = client.get("/api/search?q=milk")
        assert response.status_code == 500
        data = response.json()
        assert "Secret database error" not in str(data)
        assert "Internal server error" in data.get("detail", "") or "failure" in data.get("detail", "").lower()

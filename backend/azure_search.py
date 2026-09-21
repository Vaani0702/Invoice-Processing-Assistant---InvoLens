"""
Thin wrapper around Azure AI Search for indexing processed invoices so the
team can add a "search past invoices" feature (the RAG-ish piece the
rubric rewards under 'Application of AI-103 concepts').

Uses the standard Search REST API:
  PUT  {endpoint}/indexes/{indexName}?api-version=2024-07-01           (create index, once)
  POST {endpoint}/indexes/{indexName}/docs/index?api-version=2024-07-01 (upload docs)
  POST {endpoint}/indexes/{indexName}/docs/search?api-version=2024-07-01 (query)
"""

import os
import requests

API_VERSION = "2024-07-01"
INDEX_NAME = "invoices-index"

ENDPOINT = os.environ.get("AZURE_SEARCH_ENDPOINT")  # e.g. https://<service>.search.windows.net
API_KEY = os.environ.get("AZURE_SEARCH_KEY")


class SearchError(Exception):
    pass


def _headers():
    if not ENDPOINT or not API_KEY:
        raise SearchError("AZURE_SEARCH_ENDPOINT / AZURE_SEARCH_KEY not set. Add them to your .env file.")
    return {"api-key": API_KEY, "Content-Type": "application/json"}


def ensure_index_exists():
    """Create the invoices index if it doesn't already exist. Safe to call repeatedly."""
    schema = {
        "name": INDEX_NAME,
        "fields": [
            {"name": "id", "type": "Edm.String", "key": True},
            {"name": "vendor", "type": "Edm.String", "searchable": True, "filterable": True},
            {"name": "number", "type": "Edm.String", "searchable": True},
            {"name": "date", "type": "Edm.String", "filterable": True, "sortable": True},
            {"name": "total", "type": "Edm.Double", "filterable": True, "sortable": True},
            {"name": "status", "type": "Edm.String", "filterable": True},
        ],
    }
    resp = requests.put(
        f"{ENDPOINT}/indexes/{INDEX_NAME}",
        headers=_headers(),
        params={"api-version": API_VERSION},
        json=schema,
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        raise SearchError(f"Failed to create index: {resp.status_code} {resp.text}")


def index_invoice(invoice: dict):
    """Upload/update one invoice document in the search index."""
    doc = {
        "value": [{
            "@search.action": "mergeOrUpload",
            "id": str(invoice["id"]),
            "vendor": invoice["vendor"],
            "number": invoice["number"],
            "date": invoice["date"],
            "total": float(invoice.get("total", 0)),
            "status": invoice["status"],
        }]
    }
    resp = requests.post(
        f"{ENDPOINT}/indexes/{INDEX_NAME}/docs/index",
        headers=_headers(),
        params={"api-version": API_VERSION},
        json=doc,
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        raise SearchError(f"Failed to index invoice: {resp.status_code} {resp.text}")


def search_invoices(query: str) -> list:
    """Full-text search across vendor/number for the query string."""
    resp = requests.post(
        f"{ENDPOINT}/indexes/{INDEX_NAME}/docs/search",
        headers=_headers(),
        params={"api-version": API_VERSION},
        json={"search": query, "top": 20},
        timeout=30,
    )
    if resp.status_code != 200:
        raise SearchError(f"Search failed: {resp.status_code} {resp.text}")
    return resp.json().get("value", [])

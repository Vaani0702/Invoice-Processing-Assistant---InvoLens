"""
FastAPI backend for the Invoice Processing Assistant (AI-103 group project).

Endpoints match exactly what the frontend already expects, so once the
Azure keys are added to .env, no frontend changes are needed.

Run locally:
    pip install -r requirements.txt
    uvicorn main:app --reload --port 8000

Without AZURE_CU_ENDPOINT / AZURE_CU_KEY set, /invoices/upload falls back to
a mock extraction so the rest of the team can keep building against this
API before the Azure setup is done.
"""

import os
import uuid

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from dotenv import load_dotenv

load_dotenv()

import azure_content_understanding as cu
import azure_document_intelligence as di
import azure_search as search

app = FastAPI(title="Invoice Processing Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this before submitting if you deploy publicly
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_FILE = os.path.join(os.path.dirname(__file__), "..", "frontend", "invoice-assistant.html")
LANDING_FILE = os.path.join(os.path.dirname(__file__), "..", "frontend", "invo-lens-landing.html")


@app.get("/app", include_in_schema=False)
def serve_frontend():
    """Serves the working app itself, so running just this backend is
    enough — no separate Live Server needed. Visit http://localhost:8000/"""
    if os.path.exists(FRONTEND_FILE):
        return FileResponse(FRONTEND_FILE)
    return {"message": "InvoLens API is running, but couldn't find the frontend file."}


@app.get("/", include_in_schema=False)
def serve_landing():
    """Serves the showcase/landing page — the presentation intro,
    separate from the working app at /."""
    if os.path.exists(LANDING_FILE):
        return FileResponse(LANDING_FILE)
    return {"message": "Landing page not found."}

# In-memory store for the prototype. Fine for a course project;
# swap for a real database if you want persistence across restarts.
INVOICES = {}


def mock_extraction(filename: str) -> dict:
    """Used only when Azure keys aren't configured yet, so the team can keep
    building the rest of the app without waiting on credentials."""
    return {
        "vendor": "Sample Vendor Pvt Ltd",
        "number": f"INV-{uuid.uuid4().hex[:6].upper()}",
        "date": "16 Sep 2026",
        "total": 12500,
        "items": [{"description": "Sample line item", "quantity": 1, "rate": 12500}],
        "confidence": {"vendor": 0, "number": 0, "date": 0, "total": 0, "items": 0},
    }


def cu_is_configured() -> bool:
    return bool(os.environ.get("AZURE_CU_ENDPOINT") and os.environ.get("AZURE_CU_KEY"))


def di_is_configured() -> bool:
    return bool(os.environ.get("AZURE_DI_ENDPOINT") and os.environ.get("AZURE_DI_KEY"))


def azure_is_configured() -> bool:
    return di_is_configured() or cu_is_configured()


@app.get("/health")
def health():
    return {
        "status": "ok",
        "azure_document_intelligence_configured": di_is_configured(),
        "azure_content_understanding_configured": cu_is_configured(),
        "azure_search_configured": bool(os.environ.get("AZURE_SEARCH_ENDPOINT")),
    }


@app.post("/invoices/upload")
async def upload_invoice(file: UploadFile = File(...)):
    """
    Tries Document Intelligence first (broader region availability),
    then Content Understanding, then falls back to mock data if neither
    is configured — so the app is always testable.
    """
    used_mock = not azure_is_configured()
    source = "mock"

    if not used_mock:
        file_bytes = await file.read()
        content_type = file.content_type or "application/octet-stream"
        try:
            if di_is_configured():
                extracted = di.analyze_invoice_from_bytes(file_bytes, content_type)
                source = "document_intelligence"
            else:
                extracted = cu.analyze_invoice_from_bytes(file_bytes, content_type)
                source = "content_understanding"
        except (di.DocumentIntelligenceError, cu.ContentUnderstandingError) as e:
            raise HTTPException(status_code=502, detail=str(e))
    else:
        extracted = mock_extraction(file.filename)

    invoice_id = str(uuid.uuid4())
    avg_conf = sum(extracted["confidence"].values()) / max(len(extracted["confidence"]), 1)

    if not azure_is_configured():
        # Mock data has no real confidence info — always needs a human look.
        status = "review"
    elif avg_conf < 70:
        status = "flagged"
    elif avg_conf < 90:
        status = "review"
    else:
        status = "approved"

    invoice = {"id": invoice_id, "status": status, "mock": used_mock, "source": source, **extracted}
    INVOICES[invoice_id] = invoice

    if os.environ.get("AZURE_SEARCH_ENDPOINT"):
        try:
            search.ensure_index_exists()
            search.index_invoice(invoice)
        except search.SearchError as e:
            # Don't fail the whole upload just because indexing failed
            print(f"[warn] search indexing failed: {e}")

    return invoice


@app.get("/invoices")
def list_invoices():
    return list(INVOICES.values())


@app.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: str):
    inv = INVOICES.get(invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return inv


@app.post("/invoices/{invoice_id}/approve")
def approve_invoice(invoice_id: str):
    inv = INVOICES.get(invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    inv["status"] = "approved"
    return inv


@app.post("/invoices/{invoice_id}/flag")
def flag_invoice(invoice_id: str):
    inv = INVOICES.get(invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    inv["status"] = "flagged"
    return inv


@app.get("/invoices/search")
def search_invoices_endpoint(q: str):
    if not os.environ.get("AZURE_SEARCH_ENDPOINT"):
        raise HTTPException(status_code=400, detail="Azure AI Search not configured yet")
    return search.search_invoices(q)

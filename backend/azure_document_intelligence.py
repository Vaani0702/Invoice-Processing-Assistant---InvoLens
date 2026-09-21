"""
Wrapper around Azure Document Intelligence for invoice extraction.

Why this exists alongside azure_content_understanding.py: Content
Understanding has a narrow list of supported regions (eastus, eastus2,
southeastasia, westus, westus3, australiaeast, japaneast, northeurope,
southcentralus, swedencentral, uksouth, westeurope) that turned out not
to overlap with several student Azure subscriptions' allowed-region
policies. Document Intelligence is the older, more established sibling
service with the same prebuilt-invoice capability, but much broader
regional availability (including Central India and East Asia, which
worked where Content Understanding's regions didn't).

Based on the current (v4.0 GA) REST API:
  POST {endpoint}/documentintelligence/documentModels/prebuilt-invoice:analyze?api-version=2024-11-30
Sends the raw file bytes directly (Content-Type set to the file's mime
type) — no blob storage or public URL needed. This call is ASYNC: it
returns 202 + an Operation-Location header, then you poll that URL
until status == "succeeded".
"""

import os
import time
import requests

API_VERSION = "2024-11-30"
MODEL_ID = "prebuilt-invoice"

ENDPOINT = os.environ.get("AZURE_DI_ENDPOINT")  # e.g. https://<resource>.cognitiveservices.azure.com
API_KEY = os.environ.get("AZURE_DI_KEY")


class DocumentIntelligenceError(Exception):
    pass


def _headers(content_type: str = "application/json"):
    if not ENDPOINT or not API_KEY:
        raise DocumentIntelligenceError(
            "AZURE_DI_ENDPOINT / AZURE_DI_KEY not set. Add them to your .env file."
        )
    return {
        "Ocp-Apim-Subscription-Key": API_KEY,
        "Content-Type": content_type,
    }


def analyze_invoice_from_bytes(file_bytes: bytes, content_type: str, poll_interval: float = 2.0, timeout: float = 60.0) -> dict:
    """Send the raw file bytes to the prebuilt-invoice model and return
    the parsed result once ready."""
    submit_url = f"{ENDPOINT}/documentintelligence/documentModels/{MODEL_ID}:analyze"
    resp = requests.post(
        submit_url,
        headers=_headers(content_type),
        params={"api-version": API_VERSION},
        data=file_bytes,
        timeout=60,
    )
    if resp.status_code != 202:
        raise DocumentIntelligenceError(f"Analyze request failed: {resp.status_code} {resp.text}")

    operation_url = resp.headers.get("Operation-Location")
    if not operation_url:
        raise DocumentIntelligenceError("No Operation-Location header returned; cannot poll for result.")

    elapsed = 0.0
    while elapsed < timeout:
        poll = requests.get(operation_url, headers=_headers(), timeout=30)
        poll.raise_for_status()
        body = poll.json()
        status = body.get("status")
        if status == "succeeded":
            return _extract_fields(body)
        if status == "failed":
            raise DocumentIntelligenceError(f"Analysis failed: {body}")
        time.sleep(poll_interval)
        elapsed += poll_interval

    raise DocumentIntelligenceError("Timed out waiting for Document Intelligence result.")


def _extract_fields(result_body: dict) -> dict:
    """
    Normalise Document Intelligence's v4.0 response into the shape our
    frontend expects: { vendor, number, date, total, items, confidence }.
    """
    try:
        fields = result_body["analyzeResult"]["documents"][0]["fields"]
    except (KeyError, IndexError):
        raise DocumentIntelligenceError(f"Unexpected response shape: {result_body}")

    def val(name, kind="valueString", default=None):
        f = fields.get(name, {})
        v = f.get(kind)
        return v if v is not None else default

    def conf(name, default=0):
        f = fields.get(name, {})
        return round((f.get("confidence") or default) * 100)

    def currency_amount(name):
        f = fields.get(name, {})
        amt = f.get("valueCurrency", {}).get("amount")
        return amt if amt is not None else 0

    raw_items = fields.get("Items", {}).get("valueArray", [])
    items = []
    for it in raw_items:
        obj = it.get("valueObject", {})
        items.append({
            "description": obj.get("Description", {}).get("valueString", ""),
            "quantity": obj.get("Quantity", {}).get("valueNumber", 0),
            "rate": obj.get("UnitPrice", {}).get("valueCurrency", {}).get("amount", 0),
        })

    return {
        "vendor": val("VendorName", default="Unknown vendor"),
        "number": val("InvoiceId", default="Unknown"),
        "date": val("InvoiceDate", kind="valueDate", default="Unknown"),
        "total": currency_amount("InvoiceTotal"),
        "items": items,
        "confidence": {
            "vendor": conf("VendorName"),
            "number": conf("InvoiceId"),
            "date": conf("InvoiceDate"),
            "total": conf("InvoiceTotal"),
            "items": conf("Items"),
        },
    }

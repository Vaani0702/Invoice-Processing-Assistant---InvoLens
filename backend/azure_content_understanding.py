"""
Wrapper around Azure AI Content Understanding for invoice extraction.

Based on the current (GA) Content Understanding REST surface:
  POST {endpoint}/contentunderstanding/analyzers/{analyzerId}:analyzeBinary?api-version=2025-11-01
This sends the raw file bytes directly — no need to host the file
anywhere public first. (There's also an :analyze operation that takes a
URL instead, for cases where the file already lives somewhere reachable
like Blob Storage, but analyzeBinary is what we want here since the
frontend uploads the file directly to us.)

This call is ASYNC: it returns 202 + an Operation-Location header.
You then poll that URL until status == "Succeeded" to get the actual result.

We use the built-in "prebuilt-invoice" analyzer, which is purpose-built for
exactly this task, so we don't need to define a custom schema.

IMPORTANT: field names inside the result (VendorName, InvoiceId, etc.) are
based on documented invoice-model conventions. Confirm the exact field
names against a real response once you have a working key, and adjust
`_extract_fields()` below if anything differs.
"""

import os
import time
import requests

API_VERSION = "2025-11-01"
ANALYZER_ID = "prebuilt-invoice"

ENDPOINT = os.environ.get("AZURE_CU_ENDPOINT")  # e.g. https://<resource>.cognitiveservices.azure.com
API_KEY = os.environ.get("AZURE_CU_KEY")


class ContentUnderstandingError(Exception):
    pass


def _headers(content_type: str = "application/json"):
    if not ENDPOINT or not API_KEY:
        raise ContentUnderstandingError(
            "AZURE_CU_ENDPOINT / AZURE_CU_KEY not set. Add them to your .env file."
        )
    return {
        "Ocp-Apim-Subscription-Key": API_KEY,
        "Content-Type": content_type,
    }


def analyze_invoice_from_bytes(file_bytes: bytes, content_type: str, poll_interval: float = 2.0, timeout: float = 60.0) -> dict:
    """
    Send the raw file bytes (whatever the user uploaded — PDF, JPG, PNG)
    directly to the prebuilt-invoice analyzer and return the parsed
    result once ready. This is what the backend actually calls.
    """
    submit_url = f"{ENDPOINT}/contentunderstanding/analyzers/{ANALYZER_ID}:analyzeBinary"
    resp = requests.post(
        submit_url,
        headers=_headers(content_type),
        params={"api-version": API_VERSION},
        data=file_bytes,
        timeout=60,
    )
    if resp.status_code != 202:
        raise ContentUnderstandingError(f"Analyze request failed: {resp.status_code} {resp.text}")

    return _poll_for_result(resp.headers.get("Operation-Location"), poll_interval, timeout)


def analyze_invoice_from_url(file_url: str, poll_interval: float = 2.0, timeout: float = 60.0) -> dict:
    """
    Alternative path: submit a publicly reachable file URL (e.g. an Azure
    Blob SAS URL) instead of raw bytes. Not used by default — kept here
    in case you later store invoices in Blob Storage and want to analyze
    from there instead of the request body.
    """
    submit_url = f"{ENDPOINT}/contentunderstanding/analyzers/{ANALYZER_ID}:analyze"
    resp = requests.post(
        submit_url,
        headers=_headers(),
        params={"api-version": API_VERSION},
        json={"inputs": [{"url": file_url}]},
        timeout=30,
    )
    if resp.status_code != 202:
        raise ContentUnderstandingError(f"Analyze request failed: {resp.status_code} {resp.text}")

    return _poll_for_result(resp.headers.get("Operation-Location"), poll_interval, timeout)


def _poll_for_result(operation_url, poll_interval: float, timeout: float) -> dict:
    if not operation_url:
        raise ContentUnderstandingError("No Operation-Location header returned; cannot poll for result.")

    elapsed = 0.0
    while elapsed < timeout:
        poll = requests.get(operation_url, headers=_headers(), timeout=30)
        poll.raise_for_status()
        body = poll.json()
        status = body.get("status")
        if status == "Succeeded":
            return _extract_fields(body)
        if status == "Failed":
            raise ContentUnderstandingError(f"Analysis failed: {body}")
        time.sleep(poll_interval)
        elapsed += poll_interval

    raise ContentUnderstandingError("Timed out waiting for Content Understanding result.")


def _extract_fields(result_body: dict) -> dict:
    """
    Normalise the raw Content Understanding response into the shape our
    frontend expects: { vendor, number, date, total, items, confidence }.

    NOTE: adjust the key names below once you've seen a real response —
    this follows documented invoice-field conventions but the exact nesting
    can vary by API version.
    """
    try:
        fields = result_body["result"]["contents"][0]["fields"]
    except (KeyError, IndexError):
        raise ContentUnderstandingError(f"Unexpected response shape: {result_body}")

    def field_value(name, default=None):
        f = fields.get(name, {})
        return f.get("valueString") or f.get("valueNumber") or default

    def field_confidence(name, default=0):
        f = fields.get(name, {})
        return round((f.get("confidence") or default) * 100)

    raw_items = fields.get("Items", {}).get("valueArray", [])
    items = []
    for it in raw_items:
        obj = it.get("valueObject", {})
        items.append({
            "description": obj.get("Description", {}).get("valueString", ""),
            "quantity": obj.get("Quantity", {}).get("valueNumber", 0),
            "rate": obj.get("UnitPrice", {}).get("valueNumber", 0),
        })

    return {
        "vendor": field_value("VendorName", "Unknown vendor"),
        "number": field_value("InvoiceId", "Unknown"),
        "date": field_value("InvoiceDate", "Unknown"),
        "total": field_value("InvoiceTotal", 0),
        "items": items,
        "confidence": {
            "vendor": field_confidence("VendorName"),
            "number": field_confidence("InvoiceId"),
            "date": field_confidence("InvoiceDate"),
            "total": field_confidence("InvoiceTotal"),
            "items": field_confidence("Items"),
        },
    }

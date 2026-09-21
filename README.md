# InvoLens

**AI-103 Group Project — Chitkara University, September 2026**

Team members:Vaani (2410992988, Team Leader), Ojasvi Sethi (2410992552), Vaani Singh (2410992911), Manan Dhillon (2410993476), Chirag (2410993157)

## Problem statement

Small and mid-sized businesses process invoices manually — someone reads a
PDF or scanned invoice and re-types vendor, amount, and line-item details
into an accounting system. This is slow and error-prone: totals get
mistyped, line items get missed, and there's no consistent record of what
was verified versus assumed.

## Solution overview

InvoLens automates this: a user uploads an invoice
(PDF or image) and the app extracts structured data — vendor, invoice
number, date, line items, and total — automatically. Extracted fields
carry a confidence score; anything below a set threshold is flagged for
human review before it's approved and synced. This keeps a human in the
loop for uncertain extractions rather than blindly trusting the model,
which is the core "responsible AI" principle for this kind of automation.

The project has two pages: the working app (`/`) where you actually
upload and review invoices, and a separate showcase/landing page
(`/landing`) that explains the concept for a presentation or demo intro.

## Solution architecture

```
 ┌────────────┐      ┌──────────────┐      ┌────────────────────────────┐
 │  Frontend   │─────▶│   Backend    │─────▶│ Azure AI Content            │
 │ (upload UI, │      │  (FastAPI)   │      │ Understanding                │
 │  inbox,     │◀─────│  orchestrates│◀─────│ (prebuilt-invoice analyzer) │
 │  review UI) │      │  + validates │      └────────────────────────────┘
 └────────────┘      └──────┬───────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │ Azure AI Search   │
                    │ (indexed invoices,│
                    │  search/retrieval)│
                    └──────────────────┘
```

The frontend never calls Azure directly — the backend is the only thing
holding API keys, and it shapes Azure's raw response into the simple
JSON structure the frontend renders.

## Technology stack

- **Frontend**: HTML/CSS/JavaScript (single-page app, no build step)
- **Backend**: Python, FastAPI
- **AI services**: Azure Document Intelligence (`prebuilt-invoice` model)
  as the primary extraction engine — chosen for its much broader region
  availability compared to Content Understanding, which several student
  Azure subscriptions couldn't use due to region-restriction policies.
  Content Understanding is supported as a fallback if Document
  Intelligence isn't configured. Azure AI Search is optional, for
  indexing and retrieval of processed invoices.
- **Auth to Azure**: subscription key, loaded from environment variables

## Setup instructions

### Running the whole app (one command)

```bash
cd backend
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env          # then fill in real Azure endpoint/key values, when ready
uvicorn main:app --reload --port 8000
```

Then open **http://localhost:8000** in your browser — that's it. The
backend now serves the frontend page itself, so there's no separate
frontend server to run.

**Without Azure keys set**, uploading still works — it returns mock
extraction data (with a "needs review" status, since there's no real
confidence to judge by) so the rest of the team can build against a
stable API before the Azure resource is provisioned.

If you'd rather develop the frontend separately (e.g. with Live Server
for faster iteration), you still can — add
`<script>window.API_BASE = 'http://localhost:8000';</script>` before the
main script tag in `frontend/invoice-assistant.html`, and keep the
backend running on port 8000 in another terminal.

### Azure resources (one-time, done by whoever holds the Azure for
   Students credit)

1. In the Azure portal, create an **Azure AI Foundry** resource (Content
   Understanding is accessed through it) and note its endpoint + key.
2. Optionally create an **Azure AI Search** service for the search
   feature, and note its endpoint + key.
3. Share the endpoint + key values with the team **privately** (chat,
   not committed to Git) — everyone can call the same Azure resources
   from their own machine, since it's a cloud API, not local software.

## Testing and results

- Verified the review workflow end-to-end using mock extraction data:
  upload → fields populate → low-confidence fields are flagged →
  approve/flag updates the invoice status and activity log.
- Verified the actual Azure integration code path (not just mocked):
  the backend correctly authenticates and calls Azure AI Content
  Understanding's `analyzeBinary` endpoint with real credentials.
- **Real finding, worth documenting**: our first working Azure resource
  was created in a region (`eastasia`) that turned out not to support
  Content Understanding's GA API — Azure returned a clear
  `404 GA API is not supported in this region` error on the actual
  analyze call, even though resource *creation* succeeded there. This
  is a genuine constraint of Content Understanding's narrower regional
  availability compared to older Azure AI services, and is worth
  mentioning if asked about testing during the demo.
- Once a resource exists in a supported region (e.g. `eastus`,
  `southeastasia`, `westus`), record real extraction accuracy here
  against 3–5 sample invoices.

## Known limitations

- Extraction accuracy has not yet been fully validated against a broad
  set of real invoices.
- Some Azure for Students subscriptions carry a region-restriction
  policy that doesn't overlap with Content Understanding's supported
  regions (`eastus`, `eastus2`, `southeastasia`, `westus`, `westus3`,
  `australiaeast`, `japaneast`, `northeurope`, `southcentralus`,
  `swedencentral`, `uksouth`, `westeurope`). If you hit
  `RequestDisallowedByAzure` or `GA API is not supported in this
  region`, this is why — pick a supported region, or use a different
  Azure account if the policy can't be edited (it's a Microsoft-managed
  system policy on some student subscriptions and can't be changed by
  the subscription owner).
- No persistent database — invoices are stored in memory and reset when
  the backend restarts. Fine for a course demo; would need a real
  database for production use.
- No authentication — anyone with the URL can use the app. Acceptable
  for a course prototype demoed on one laptop; a real deployment would
  need per-user accounts.

## Future improvements

- Persist invoices in a real database (e.g. Azure Cosmos DB or SQLite for
  simplicity).
- Add duplicate-invoice detection.
- Add authentication so multiple companies could use the same deployment
  without seeing each other's data.

## Responsible AI considerations

- **Human oversight**: any field below the confidence threshold is
  flagged for manual review rather than auto-approved.
- **Transparency**: the UI shows the confidence score per field, not just
  the final extracted value, so users can see what the model was unsure
  about.
- **Privacy**: invoice data (which may include vendor and financial
  details) is only sent to Azure, never to a third party; the `.env` file
  holding API keys is excluded from version control.

## Acknowledgements

- Azure AI Content Understanding (`prebuilt-invoice` analyzer) — Microsoft
- Azure AI Search — Microsoft
- FastAPI, python-dotenv, requests — open-source Python libraries

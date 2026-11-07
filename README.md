# PaidOnTime

**Invoice-to-payment copilot for freelancers.** Create an invoice, send a PayPal
payment link, and watch it move from awaiting payment to paid — without chasing.

Built for the **PayPal AI Hackathon 2026**. The payment spine and AI invoice
extraction are working; follow-up drafting and deployment come next.

## What works today

- Upload a text-based invoice PDF and extract fields with an AI model.
- Extract the client, invoice number, amount, currency and due date.
- Create an invoice with client, amount, currency, due date and description.
- Create a real PayPal **sandbox** order through the Orders v2 API.
- Open the PayPal sandbox checkout and approve as the test buyer.
- Return to the app, capture the payment, and store the capture ID.
- Dashboard with outstanding, paid, awaiting-payment and overdue totals.
- Overdue badge and an AI-drafted follow-up for unpaid invoices.
- Retry a failed or cancelled payment link.
- No real money and no live PayPal credentials.

## Stack

- Python 3.11+; `http.server` + SQLite
- `pypdf` for PDF text extraction
- DeepSeek/OpenAI-compatible chat endpoint for structured extraction
- PayPal Orders v2 REST API
- Plain HTML/CSS, no build step
- Ready for Render: `Procfile` included

## Run locally

```powershell
cd paypal-invoice-autopilot
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
python server.py
```

Open <http://127.0.0.1:8000>.

`.env` needs your **sandbox** app credentials and AI key:

```text
PAYPAL_CLIENT_ID=...
PAYPAL_SECRET=...
PAYPAL_API_BASE=https://api-m.sandbox.paypal.com
PUBLIC_BASE_URL=http://127.0.0.1:8000
AI_API_KEY=...
AI_BASE_URL=https://api.deepseek.com/v1
AI_MODEL=deepseek-chat
```

The app refuses to start if `PAYPAL_API_BASE` is not a sandbox URL.

## Deploy to Render

1. Push the repo to GitHub.
2. Render Dashboard → **New → Blueprint** → select the repo.
3. Render reads [`render.yaml`](render.yaml) and asks for the secret values.
4. Enter `PAYPAL_CLIENT_ID`, `PAYPAL_SECRET` and `AI_API_KEY`.
5. Set `PUBLIC_BASE_URL` to the actual Render URL, e.g.
   `https://paidontime.onrender.com`.
6. Deploy and open `/healthz`; it should return
   `{"ok": true, "paypal_configured": true}`.
7. Create an invoice on the hosted URL and complete the sandbox flow.

Free Render web services use an ephemeral filesystem, so the SQLite file can
reset when the service restarts or redeploys. That is acceptable for the demo;
a production version would use Postgres.

## Test the full loop

1. Click **New invoice**.
2. Upload a text-based PDF and click **Extract with AI**. Use
   [`samples/sample_invoice.pdf`](samples/sample_invoice.pdf) if you need one.
3. Review the extracted client, invoice number, amount, currency and due date.
4. Click **Create PayPal link**.
5. Open the PayPal checkout on the invoice page.
6. Log in with the **sandbox personal buyer** account — not your real PayPal account.
7. Approve the payment.
8. You return to the invoice page; the app captures the payment.
9. The dashboard now shows the invoice as **Paid**.

For an overdue invoice, the dashboard shows an **Overdue** badge and the detail
page offers **Draft with AI** to write a follow-up email.

If you land on the invoice page before capture completes, click **Refresh status**
or **Capture payment**.

## Project layout

```text
server.py                  HTTP routes and form handling
paypal.py                  Orders v2 client (OAuth, create, get, capture)
ai.py                      PDF text extraction + structured AI extraction
db.py                      SQLite schema and queries
views.py                   HTML rendering
config.py                  .env loading and sandbox guard
static/style.css           UI
samples/sample_invoice.pdf  Demo invoice for the AI extractor
scripts/paypal_smoke_test.py   First API smoke test
scripts/paypal_order_tool.py   Inspect/capture an existing order
```

## Sandbox accounts

Developer Dashboard → **Testing Tools → Sandbox Accounts**:

- **Business** account — receives the sandbox payment
- **Personal** account — approves the sandbox payment

Use the personal account in an incognito window. If the password is unknown,
open the account → **View/Edit account** → reset it.

## Abuse controls

This is a public demo, so the expensive endpoints are capped:

- **12 AI extractions per hour per IP**, **80 per day** globally.
- **20 invoice creations per hour per IP**, **60 per day** globally.
- **30 follow-up drafts per hour per IP**.
- Upload body limit: 12 MB on the extraction API, 1 MB on forms.
- `DEMO_PAUSED=true` in Render turns off extraction, invoice creation and
  follow-ups immediately.

The PayPal and AI secrets stay server-side. If a key is abused, rotate it in
the provider dashboard and redeploy; `DEMO_PAUSED` is the emergency stop.

## Current limitations

- Single-user demo; there is no login or account separation.
- SQLite file storage; on a hosted free tier the file may reset on deploy.
- No webhook yet; the return page and manual refresh drive the status.
- Scanned/image-only PDFs are not OCR'd yet; the PDF needs a text layer.
- Sandbox only. The app is intentionally blocked from live PayPal.

## Next

1. Deploy to Render with a public `PUBLIC_BASE_URL`.
2. Three-minute demo video and Devpost submission.


## License

MIT — see [LICENSE](LICENSE).

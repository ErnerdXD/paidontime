"""HTML views for PaidOnTime. No template engine, no external assets."""

from __future__ import annotations

from datetime import date, datetime
from html import escape

from db import STATUS_LABELS, is_overdue


def esc(value: object) -> str:
    return escape(str(value if value is not None else ""))


def money(cents: int, currency: str) -> str:
    return f"{cents / 100:,.2f} {esc(currency)}"


def totals(by_currency: dict, key: str) -> str:
    parts = [
        f"{esc(currency)} {values[key] / 100:,.2f}"
        for currency, values in sorted(by_currency.items())
        if values.get(key)
    ]
    return " · ".join(parts) if parts else "0.00"


def fmt_dt(value: str) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d %b %Y, %H:%M")
    except ValueError:
        return esc(value)


def fmt_date(value: str) -> str:
    if not value:
        return "—"
    try:
        return date.fromisoformat(value).strftime("%d %b %Y")
    except ValueError:
        return esc(value)


def badge(status: str) -> str:
    label = STATUS_LABELS.get(status, status.title())
    return f'<span class="badge badge-{esc(status.lower())}">{esc(label)}</span>'


def invoice_badge(invoice) -> str:
    if is_overdue(invoice):
        return '<span class="badge badge-overdue">Overdue</span>'
    return badge(invoice["status"])


def alert(message: str, kind: str = "error") -> str:
    if not message:
        return ""
    return f'<div class="alert alert-{esc(kind)}" role="status">{esc(message)}</div>'


def layout(title: str, content: str, active: str = "dashboard") -> str:
    def nav_class(key: str) -> str:
        return "nav-link active" if active == key else "nav-link"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)} · PaidOnTime</title>
  <link rel="stylesheet" href="/static/style.css?v=minimal-1">
</head>
<body>
  <header class="topbar">
    <a class="brand" href="/">
      <span class="brand-mark" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
          <path d="M5 12.5l4.5 4.5L19 6.5"/>
        </svg>
      </span>
      <span>PaidOnTime</span>
    </a>
    <nav class="nav" aria-label="Main">
      <a class="{nav_class("dashboard")}" href="/">Dashboard</a>
      <a class="{nav_class("new")}" href="/invoices/new">New invoice</a>
    </nav>
  </header>

  <main class="shell">
    {content}
  </main>

  <footer class="footer">
    <span>PaidOnTime · invoice-to-payment, without the chase</span>
    <span class="sandbox-pill"><span class="dot"></span> PayPal sandbox · no real money</span>
  </footer>

  <script>
    document.addEventListener("click", async (event) => {{
      const button = event.target.closest("[data-copy]");
      if (!button) return;
      const field = document.querySelector(button.getAttribute("data-copy"));
      if (!field) return;
      try {{
        await navigator.clipboard.writeText(field.value);
        const old = button.textContent;
        button.textContent = "Copied";
        setTimeout(() => {{ button.textContent = old; }}, 1400);
      }} catch (error) {{
        field.select();
      }}
    }});
  </script>
</body>
</html>"""


def dashboard(invoices: list, stats: dict, notice: str = "", error: str = "") -> str:
    rows = []
    for invoice in invoices:
        rows.append(
            f"""
            <tr>
              <td>
                <a class="invoice-link" href="/invoices/{invoice['id']}">
                  <strong>{esc(invoice['invoice_number'])}</strong>
                  <span>{esc(invoice['client_name'])}</span>
                </a>
              </td>
              <td class="num">{money(invoice['amount_cents'], invoice['currency'])}</td>
              <td>{invoice_badge(invoice)}</td>
              <td class="muted">{fmt_date(invoice['due_date'])}</td>
              <td class="right"><a class="text-link" href="/invoices/{invoice['id']}">Open</a></td>
            </tr>"""
        )

    if rows:
        table = f"""
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>Invoice</th><th>Amount</th><th>Status</th><th>Due</th><th></th></tr>
            </thead>
            <tbody>{''.join(rows)}</tbody>
          </table>
        </div>"""
    else:
        table = """
        <div class="empty">
          <div class="empty-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
              <path d="M7 3h7l4 4v14H7z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h4"/>
            </svg>
          </div>
          <h2>No invoices yet</h2>
          <p>Create your first invoice and turn it into a PayPal payment link.</p>
          <a class="button" href="/invoices/new">Create invoice</a>
        </div>"""

    content = f"""
    <section class="hero">
      <div class="hero-copy">
        <p class="eyebrow">PAYMENT OPERATIONS</p>
        <h1>Invoices in.<br><span>Paid on time.</span></h1>
        <p class="lede">Turn a finished invoice into a PayPal payment link, then see exactly what is paid, approved, or still waiting.</p>
        <div class="hero-actions">
          <a class="button" href="/invoices/new">Create invoice</a>
          <a class="ghost-link" href="#invoices">View invoices <span aria-hidden="true">→</span></a>
        </div>
      </div>
      <div class="hero-card">
        <p class="mini">TRACKED</p>
        <strong>{stats['count']}</strong>
        <span>invoice{'' if stats['count'] == 1 else 's'} in this workspace</span>
        <div class="hero-rule"></div>
        <p class="mini">AWAITING PAYMENT</p>
        <strong>{stats['awaiting_count']}</strong>
        <span>need a nudge or a checkout</span>
      </div>
    </section>

    {alert(notice, 'success')}
    {alert(error, 'error')}

    <section class="stats" aria-label="Totals">
      <div class="stat">
        <p class="stat-label">Outstanding</p>
        <p class="stat-value">{totals(stats['by_currency'], 'outstanding_cents')}</p>
        <p class="stat-note">Created or approved, not captured</p>
      </div>
      <div class="stat">
        <p class="stat-label">Paid</p>
        <p class="stat-value">{totals(stats['by_currency'], 'paid_cents')}</p>
        <p class="stat-note">Captured in PayPal sandbox</p>
      </div>
      <div class="stat">
        <p class="stat-label">Awaiting payment</p>
        <p class="stat-value">{stats['awaiting_count']}</p>
        <p class="stat-note">Created or approved, not captured</p>
      </div>
      <div class="stat stat-alert">
        <p class="stat-label">Overdue</p>
        <p class="stat-value">{stats['overdue_count']}</p>
        <p class="stat-note">Past the due date and unpaid</p>
      </div>
    </section>

    <section class="panel" id="invoices">
      <div class="panel-head">
        <div>
          <p class="eyebrow">LEDGER</p>
          <h2>All invoices</h2>
        </div>
        <a class="button button-small" href="/invoices/new">+ New invoice</a>
      </div>
      {table}
    </section>"""
    return layout("Dashboard", content, active="dashboard")


EXTRACT_SCRIPT = """
<script>
(() => {
  const fileInput = document.getElementById("invoice_file");
  const extractBtn = document.getElementById("extract-btn");
  const fileName = document.getElementById("file-name");
  const status = document.getElementById("extract-status");
  if (!fileInput || !extractBtn || !status) return;

  const setStatus = (message, kind = "") => {
    status.textContent = message;
    status.className = "extract-status" + (kind ? " " + kind : "");
  };

  const readAsDataUrl = (file) => new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("Could not read the file."));
    reader.readAsDataURL(file);
  });

  const fill = (fields) => {
    const set = (name, value) => {
      if (!value) return;
      const input = document.querySelector('[name="' + name + '"]');
      if (input) input.value = value;
    };
    set("client_name", fields.client_name);
    set("client_email", fields.client_email);
    set("invoice_number", fields.invoice_number);
    set("description", fields.description);
    set("amount", fields.amount);
    set("currency", fields.currency);
    set("due_date", fields.due_date);
  };

  fileInput.addEventListener("change", () => {
    const file = fileInput.files[0];
    fileName.textContent = file ? file.name : "No file selected · max 8 MB";
    setStatus("");
  });

  extractBtn.addEventListener("click", async () => {
    const file = fileInput.files[0];
    if (!file) {
      setStatus("Choose a PDF first.", "err");
      return;
    }
    if (file.size > 8 * 1024 * 1024) {
      setStatus("That PDF is larger than 8 MB.", "err");
      return;
    }
    extractBtn.disabled = true;
    extractBtn.textContent = "Reading…";
    setStatus("Reading the invoice and extracting fields…");
    try {
      const dataUrl = await readAsDataUrl(file);
      const response = await fetch("/api/extract", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: file.name, pdf_base64: dataUrl })
      });
      const data = await response.json();
      if (!data.ok) throw new Error(data.error || "Extraction failed.");
      fill(data.fields);
      const confidence = data.fields.confidence
        ? " Confidence " + Math.round(data.fields.confidence * 100) + "%."
        : "";
      const warnings = data.fields.warnings && data.fields.warnings.length
        ? " Check: " + data.fields.warnings.join(" · ")
        : "";
      setStatus("Fields extracted." + confidence + " Review everything before creating the link." + warnings, "ok");
    } catch (error) {
      setStatus(error.message || "Extraction failed.", "err");
    } finally {
      extractBtn.disabled = false;
      extractBtn.textContent = "Read invoice";
    }
  });
})();
</script>
"""


def new_invoice(values: dict | None = None, error: str = "") -> str:
    values = values or {}
    currency_options = "".join(
        f'<option value="{code}"{" selected" if values.get("currency", "MYR") == code else ""}>{code}</option>'
        for code in ("MYR", "USD", "SGD", "EUR", "GBP", "AUD")
    )
    content = f"""
    <div class="page-head">
      <a class="back-link" href="/">← Dashboard</a>
      <p class="eyebrow">NEW INVOICE</p>
      <h1>Create a payment link.</h1>
      <p class="lede narrow">Enter the invoice details once. PaidOnTime creates the PayPal order and keeps the status in sync.</p>
    </div>

    {alert(error, 'error')}

    <div class="form-grid">
      <section class="panel form-panel">
        <div class="upload-box">
          <div class="upload-copy">
            <span class="ai-chip">IMPORT</span>
            <h2>Read the invoice</h2>
            <p>Upload a text-based PDF and the details are read into the form. Review everything before creating the payment link.</p>
          </div>
          <div class="upload-actions">
            <input type="file" id="invoice_file" accept="application/pdf" hidden>
            <label class="button button-quiet" for="invoice_file">Choose PDF</label>
            <button class="button" type="button" id="extract-btn">Read invoice</button>
          </div>
          <p class="file-name" id="file-name">No file selected · max 8 MB</p>
          <p class="extract-status" id="extract-status" role="status"></p>
          <p class="sample-line">No invoice handy? <a class="text-link" href="/samples/sample_invoice.pdf" target="_blank" rel="noopener">Download the sample PDF</a>.</p>
        </div>

        <form method="post" action="/invoices" autocomplete="off">
          <div class="field-row">
            <label class="field">
              <span>Client name</span>
              <input name="client_name" required maxlength="120" value="{esc(values.get('client_name', ''))}" placeholder="Aina Studio">
            </label>
            <label class="field">
              <span>Client email</span>
              <input type="email" name="client_email" maxlength="160" value="{esc(values.get('client_email', ''))}" placeholder="aina@example.com">
            </label>
          </div>

          <div class="field-row">
            <label class="field">
              <span>Invoice number</span>
              <input name="invoice_number" required maxlength="60" value="{esc(values.get('invoice_number', ''))}" placeholder="INV-2026-014">
            </label>
            <label class="field">
              <span>Amount</span>
              <div class="amount-input">
                <select name="currency" aria-label="Currency">{currency_options}</select>
                <input name="amount" required inputmode="decimal" pattern="[0-9]+([.][0-9]{{1,2}})?" value="{esc(values.get('amount', ''))}" placeholder="1250.00">
              </div>
            </label>
          </div>

          <label class="field">
            <span>Description <em>optional</em></span>
            <input name="description" maxlength="127" value="{esc(values.get('description', ''))}" placeholder="Brand identity sprint · March 2026">
          </label>

          <label class="field">
            <span>Due date <em>optional</em></span>
            <input type="date" name="due_date" value="{esc(values.get('due_date', ''))}">
          </label>

          <div class="form-actions">
            <button class="button" type="submit">Create PayPal link</button>
            <a class="ghost-link" href="/">Cancel</a>
          </div>
          <p class="fine-print">You will review the order in PayPal sandbox before any payment is approved. No real money moves.</p>
        </form>
      </section>

      <aside class="panel aside-panel">
        <p class="eyebrow">HOW IT WORKS</p>
        <ol class="steps">
          <li><span>01</span><div><strong>Create the order</strong><p>PaidOnTime stores the invoice and asks PayPal for a checkout link.</p></div></li>
          <li><span>02</span><div><strong>Send the link</strong><p>Share it with the client, or open it yourself to test the sandbox flow.</p></div></li>
          <li><span>03</span><div><strong>Capture and track</strong><p>The return page captures the payment and the dashboard updates to Paid.</p></div></li>
        </ol>
        <div class="aside-note">
          <strong>Sandbox only</strong>
          <p>This demo uses PayPal's sandbox. Use the sandbox personal buyer account to approve the payment.</p>
        </div>
      </aside>
    </div>
    {EXTRACT_SCRIPT}"""
    return layout("New invoice", content, active="new")


REMINDER_SCRIPT = """
<script>
(() => {
  const button = document.getElementById("draft-reminder");
  const result = document.getElementById("reminder-result");
  const subject = document.getElementById("reminder-subject");
  const body = document.getElementById("reminder-body");
  const status = document.getElementById("reminder-status");
  if (!button || !result || !subject || !body || !status) return;

  button.addEventListener("click", async () => {
    button.disabled = true;
    const old = button.textContent;
    button.textContent = "Drafting…";
    status.textContent = "";
    status.className = "extract-status";
    try {
      const response = await fetch("/api/reminder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ invoice_id: button.dataset.invoice })
      });
      const data = await response.json();
      if (!data.ok) throw new Error(data.error || "Could not draft a follow-up.");
      subject.value = data.reminder.subject;
      body.value = data.reminder.body;
      result.hidden = false;
      status.textContent = "Draft ready. Review and edit before sending.";
      status.className = "extract-status ok";
    } catch (error) {
      status.textContent = error.message || "Could not draft a follow-up.";
      status.className = "extract-status err";
    } finally {
      button.disabled = false;
      button.textContent = old;
    }
  });
})();
</script>
"""


def detail(invoice, notice: str = "", error: str = "") -> str:
    status = invoice["status"]
    is_paid = status == "COMPLETED"
    is_created = status == "CREATED"
    is_approved = status == "APPROVED"
    overdue = is_overdue(invoice)
    approval_url = invoice["approval_url"]

    primary_action = ""
    if is_created and approval_url:
        primary_action = f"""
        <a class="button" href="{esc(approval_url)}" target="_blank" rel="noopener">Open PayPal checkout</a>
        <form method="post" action="/invoices/{invoice['id']}/refresh" class="inline-form">
          <button class="button button-quiet" type="submit">Refresh status</button>
        </form>"""
    elif is_approved:
        primary_action = f"""
        <form method="post" action="/invoices/{invoice['id']}/capture" class="inline-form">
          <button class="button" type="submit">Capture payment</button>
        </form>
        <form method="post" action="/invoices/{invoice['id']}/refresh" class="inline-form">
          <button class="button button-quiet" type="submit">Refresh status</button>
        </form>"""
    elif is_paid:
        primary_action = '<span class="paid-stamp">Payment captured</span>'
    else:
        primary_action = f"""
        <form method="post" action="/invoices/{invoice['id']}/retry" class="inline-form">
          <button class="button" type="submit">Create new PayPal link</button>
        </form>"""

    copy_box = ""
    if approval_url and not is_paid:
        copy_box = f"""
        <div class="copy-row">
          <input id="approval-link" class="copy-field" readonly value="{esc(approval_url)}" aria-label="PayPal approval link">
          <button class="button button-quiet" type="button" data-copy="#approval-link">Copy link</button>
        </div>"""

    created_done = "done"
    approved_done = "done" if status in ("APPROVED", "COMPLETED") else ""
    paid_done = "done" if is_paid else ""

    reminder_panel = ""
    if is_created and invoice["due_date"]:
        reminder_panel = f"""
        <div class="followup">
          <p class="eyebrow">FOLLOW-UP</p>
          <h3>Draft a reminder</h3>
          <p class="aside-copy">Write a polite follow-up for {esc(invoice['client_name'])} using the invoice and due date.</p>
          <button class="button button-quiet" type="button" id="draft-reminder" data-invoice="{invoice['id']}">Draft follow-up</button>
          <p class="extract-status" id="reminder-status" role="status"></p>
          <div class="reminder-result" id="reminder-result" hidden>
            <label class="field"><span>Subject</span><input id="reminder-subject" readonly></label>
            <label class="field"><span>Body</span><textarea id="reminder-body" rows="7" readonly></textarea></label>
            <button class="button button-quiet" type="button" data-copy="#reminder-body">Copy body</button>
          </div>
        </div>"""

    content = f"""
    <div class="page-head detail-head">
      <a class="back-link" href="/">← Dashboard</a>
      <div class="detail-title-row">
        <div>
          <p class="eyebrow">INVOICE</p>
          <h1>{esc(invoice['invoice_number'])}</h1>
          <p class="lede narrow">{esc(invoice['client_name'])} · {fmt_dt(invoice['created_at'])}</p>
        </div>
        <div class="detail-amount">
          <span>Amount</span>
          <strong>{money(invoice['amount_cents'], invoice['currency'])}</strong>
          {invoice_badge(invoice)}
        </div>
      </div>
    </div>

    {alert(notice, 'success')}
    {alert(error, 'error')}

    <div class="detail-grid">
      <section class="panel detail-main">
        <div class="panel-head">
          <div>
            <p class="eyebrow">PAYMENT</p>
            <h2>PayPal order</h2>
          </div>
          {primary_action}
        </div>

        {copy_box}

        <dl class="meta-grid">
          <div><dt>Client</dt><dd>{esc(invoice['client_name'])}</dd></div>
          <div><dt>Email</dt><dd>{esc(invoice['client_email']) or '—'}</dd></div>
          <div><dt>Description</dt><dd>{esc(invoice['description']) or '—'}</dd></div>
          <div><dt>Due date</dt><dd>{fmt_date(invoice['due_date'])}{' · overdue' if overdue else ''}</dd></div>
          <div><dt>PayPal order</dt><dd class="mono">{esc(invoice['paypal_order_id']) or '—'}</dd></div>
          <div><dt>Capture ID</dt><dd class="mono">{esc(invoice['capture_id']) or '—'}</dd></div>
          <div><dt>Last update</dt><dd>{fmt_dt(invoice['updated_at'])}</dd></div>
        </dl>

        <div class="timeline">
          <div class="timeline-step {created_done}">
            <span class="timeline-dot"></span>
            <div><strong>Invoice created</strong><p>Saved locally and ready for a PayPal order.</p></div>
          </div>
          <div class="timeline-step {approved_done}">
            <span class="timeline-dot"></span>
            <div><strong>Buyer approved</strong><p>The sandbox buyer completed the PayPal checkout.</p></div>
          </div>
          <div class="timeline-step {paid_done}">
            <span class="timeline-dot"></span>
            <div><strong>Payment captured</strong><p>The funds are captured in the sandbox merchant account.</p></div>
          </div>
        </div>
      </section>

      <aside class="panel detail-aside">
        <p class="eyebrow">NEXT STEP</p>
        <h2>{'Nothing to chase.' if is_paid else 'Send a nudge.' if overdue else 'Send the checkout.' if is_created else 'Capture the payment.' if is_approved else 'Review this invoice.'}</h2>
        <p class="aside-copy">
          {'This invoice is complete. The capture ID is stored above.' if is_paid else
           'This invoice is past due. Open the checkout again or draft a polite follow-up.' if overdue else
           'Open the PayPal checkout, log in with the sandbox personal buyer, and approve the payment. Then return here and capture.' if is_created else
           'PayPal has approved the order. Capture it now to move the money in sandbox.' if is_approved else
           'This invoice is not currently awaiting payment.'}
        </p>
        <div class="aside-note">
          <strong>Sandbox reminder</strong>
          <p>Approval must happen with the PayPal sandbox personal account. Your real PayPal account will not work here.</p>
        </div>
        {reminder_panel}
      </aside>
    </div>
    {REMINDER_SCRIPT}"""
    return layout(f"Invoice {invoice['invoice_number']}", content, active="dashboard")


def not_found() -> str:
    content = """
    <div class="empty standalone">
      <p class="eyebrow">404</p>
      <h1>That invoice is not here.</h1>
      <p>The link may be wrong, or the invoice was never created.</p>
      <a class="button" href="/">Back to dashboard</a>
    </div>"""
    return layout("Not found", content)


def server_error(message: str = "") -> str:
    content = f"""
    <div class="empty standalone">
      <p class="eyebrow">500</p>
      <h1>Something went wrong.</h1>
      <p>{esc(message) or 'The server hit an unexpected error. Check the terminal log.'}</p>
      <a class="button" href="/">Back to dashboard</a>
    </div>"""
    return layout("Server error", content)


def too_many(message: str = "Too many requests.", retry_after: int = 0) -> str:
    wait = f" Try again in about {retry_after} seconds." if retry_after else ""
    content = f"""
    <div class="empty standalone">
      <p class="eyebrow">SLOW DOWN</p>
      <h1>That was a lot of requests.</h1>
      <p>{esc(message)}{esc(wait)}</p>
      <a class="button" href="/">Back to dashboard</a>
    </div>"""
    return layout("Too many requests", content)


def access_gate(next_path: str = "/", error: str = "") -> str:
    content = f"""
    <div class="gate-wrap">
      <section class="gate-card">
        <p class="eyebrow">PRIVATE DEMO</p>
        <h1>Enter the demo code.</h1>
        <p class="lede narrow">This prototype is shared with judges and reviewers. Enter the code from the submission testing notes.</p>
        {alert(error, 'error')}
        <form method="post" action="/access">
          <input type="hidden" name="next" value="{esc(next_path)}">
          <label class="field">
            <span>Access code</span>
            <input name="code" type="password" required autofocus autocomplete="current-password" placeholder="Demo code">
          </label>
          <button class="button" type="submit">Open demo</button>
        </form>
        <p class="fine-print">The code is a light gate, not a replacement for the demo's rate limits. It is stored in an HttpOnly cookie for seven days.</p>
      </section>
    </div>"""
    return layout("Demo access", content, active="")


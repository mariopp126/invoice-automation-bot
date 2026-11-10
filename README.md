# Invoice Bot MVP

A minimal personal PoC that turns invoice photos sent over WhatsApp into rows in an Excel report.

**Pipeline:** WhatsApp image/PDF → Meta Cloud API webhook → FastAPI → Gemini vision OCR → structured JSON → `openpyxl` → Excel.

> This is an MVP for validating the pipeline, not a production system. See [MVP limitations](#mvp-limitations) before using it with real accounting data.

## What works

- `GET /webhook` — Meta verification handshake.
- `POST /webhook` — receives WhatsApp `image` and `document` messages, downloads the media, extracts the invoice, appends it to Excel, and replies with a summary.
- `POST /process` — manual upload endpoint for cURL/Postman testing (no WhatsApp needed).
- Gemini structured extraction of `rnc`, `ncf`, `emisor`, `fecha`, `monto_total`.
- Excel file creation and append with headers, formatting, and an atomic save.
- Optional Meta `X-Hub-Signature-256` verification and optional `X-API-Key` protection.
- Docker + Docker Compose setup.

## Project layout

```
app/
  main.py          FastAPI routes, webhook handling, background processing
  config.py        Environment settings (.env)
  models.py        InvoiceData schema + field normalization
  gemini_ocr.py    Gemini vision call and JSON parsing
  sheets.py        Excel writer
  whatsapp.py      Graph API media download + text replies
scripts/
  make_sample_invoice.py   Generates a fake Dominican invoice PNG
  send_sample.py           Sends a file to /process
tests/
  test_mvp.py              Smoke tests (Gemini/WhatsApp mocked)
Dockerfile
docker-compose.yml
.env.example
```

## 1. Prerequisites

- Python 3.11+ (tested with 3.12) or Docker.
- A Google AI Studio API key: <https://aistudio.google.com/api-keys>.
- Optional: a Meta developer app with the WhatsApp product, for the real WhatsApp flow.
- Optional: Tailscale on the server, with Funnel enabled, to expose the webhook over HTTPS.

### Gemini model note

Gemini 1.5 Flash is retired. The MVP defaults to **`gemini-3.5-flash-lite`**, which supports image/PDF input and structured outputs on the free tier. If you want stronger extraction, set:

```env
GEMINI_MODEL=gemini-3.8-flash
```

Model availability and free-tier limits change over time. Check AI Studio if a model returns `404`/`400`.

## 2. Local setup

### Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
# If PowerShell blocks activation: Set-ExecutionPolicy -Scope Process Bypass
pip install -r requirements-dev.txt
Copy-Item .env.example .env
# Edit .env and set GOOGLE_API_KEY
uvicorn app.main:app --reload --port 8000
```

### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
# Edit .env and set GOOGLE_API_KEY
uvicorn app.main:app --reload --port 8000
```

Open <http://localhost:8000/docs> for the interactive API docs.

## 3. Test the pipeline without WhatsApp

Generate a sample invoice:

```bash
python scripts/make_sample_invoice.py
```

Send it to the running server:

```bash
python scripts/send_sample.py sample_invoice.png
```

Or use cURL directly:

```bash
# Linux/macOS
curl -X POST http://localhost:8000/process \
  -F "file=@sample_invoice.png;type=image/png"

# Windows PowerShell (use curl.exe, not the PowerShell alias)
curl.exe -X POST http://localhost:8000/process -F "file=@sample_invoice.png;type=image/png"
```

Expected response:

```json
{
  "invoice": {
    "rnc": "1-31-23456-7",
    "ncf": "B0100000123",
    "emisor": "FERRETERÍA EL MARTILLO, SRL",
    "fecha": "2026-11-05",
    "monto_total": 4720.0
  },
  "row": 2,
  "file": "./data/facturas.xlsx"
}
```

The first invoice creates `data/facturas.xlsx`; subsequent invoices append rows. Download the current file at <http://localhost:8000/report>.

If `APP_API_KEY` is set in `.env`, add the header:

```bash
curl -X POST http://localhost:8000/process \
  -H "X-API-Key: your-key" \
  -F "file=@sample_invoice.png;type=image/png"
```

## 4. Run with Docker

```bash
cp .env.example .env
# Edit .env and set GOOGLE_API_KEY
mkdir -p data
docker compose up -d --build
docker compose logs -f invoice-bot
```

- The API is at <http://localhost:8000>.
- The Excel file is bind-mounted at `./data/facturas.xlsx` on the host.
- `docker-compose.yml` overrides `EXCEL_PATH` to `/app/data/facturas.xlsx` inside the container.
- The container uses one uvicorn worker on purpose (see limitations).
- The container runs as root for bind-mount simplicity. That is acceptable for this personal PoC; use a non-root user and proper volume permissions for anything beyond that.

Stop it with:

```bash
docker compose down
```

## 5. Connect WhatsApp Cloud API

### 5.1 Expose the webhook with Tailscale Funnel

On the Ubuntu server (or any machine running the container):

```bash
sudo tailscale funnel --bg 8000
tailscale funnel status
```

This maps the public HTTPS URL (port 443) to local port 8000 and prints something like:

```text
https://your-machine.your-tailnet.ts.net
```

Verify it from outside your network:

```bash
curl https://your-machine.your-tailnet.ts.net/health
```

The webhook URL will be:

```text
https://your-machine.your-tailnet.ts.net/webhook
```

Tailscale Funnel must be allowed in your tailnet policy. If Funnel is unavailable, use any other HTTPS tunnel (Cloudflare Tunnel, ngrok, etc.).

### 5.2 Configure the Meta app

1. Create an app at <https://developers.facebook.com/apps> (type: Business).
2. Add the **WhatsApp** product.
3. In **WhatsApp → API Setup**, note:
   - **Phone number ID** → `WHATSAPP_PHONE_NUMBER_ID`
   - **Temporary access token** → `WHATSAPP_TOKEN` (expires in 24 hours)
4. Add your personal WhatsApp number as a test recipient.
5. In **WhatsApp → Configuration → Webhook**, click **Edit**:
   - **Callback URL:** `https://your-machine.your-tailnet.ts.net/webhook`
   - **Verify token:** the exact value of `WHATSAPP_VERIFY_TOKEN` in `.env`
   - Click **Verify and save**. The FastAPI server must be running.
6. Subscribe to the **`messages`** webhook field.
7. Put the token and phone number ID in `.env`, then recreate the container so the new environment is loaded:

```bash
docker compose up -d invoice-bot
```

8. Send an invoice photo or PDF to the WhatsApp test number.

Optional but recommended: copy **App settings → Basic → App secret** into `WHATSAPP_APP_SECRET`. The app will then reject webhook POSTs whose `X-Hub-Signature-256` does not match. Leave it empty if you are manually posting test payloads without a signature.

For a longer-lived token, create a System User token with `whatsapp_business_messaging` and `whatsapp_business_management` permissions instead of using the 24-hour temporary token.

## Excel output

Default sheet: `Facturas`

| Fecha | RNC | NCF | Emisor | Monto Total | Registrado (UTC) |
|---|---|---|---|---|---|
| 2026-11-05 | 1-31-23456-7 | B0100000123 | FERRETERÍA EL MARTILLO, SRL | 4720.00 | 2026-11-09 22:25:52 |

- The file is created automatically on the first invoice.
- Rows are appended after the last used row.
- If you need a different budget layout, edit `HEADERS`, `COLUMN_WIDTHS`, and `_row_values()` in `app/sheets.py`. Delete/rename the existing workbook after changing headers so a fresh one is created.
- Close the workbook in Excel while the bot is writing; Windows will block the atomic file replace otherwise.

## Configuration

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GOOGLE_API_KEY` | Yes | — | Google AI Studio API key |
| `GEMINI_MODEL` | No | `gemini-3.5-flash-lite` | Vision model; `gemini-3.8-flash` for higher accuracy |
| `WHATSAPP_TOKEN` | For WhatsApp | — | Meta Cloud API access token |
| `WHATSAPP_PHONE_NUMBER_ID` | For WhatsApp | — | WhatsApp phone number ID |
| `WHATSAPP_VERIFY_TOKEN` | For webhook | `change-me` | Random string shared with Meta |
| `WHATSAPP_APP_SECRET` | Recommended | — | Enables webhook signature verification |
| `WHATSAPP_API_VERSION` | No | `v23.0` | Graph API version |
| `EXCEL_PATH` | No | `./data/facturas.xlsx` | Workbook path |
| `EXCEL_SHEET_NAME` | No | `Facturas` | Sheet name |
| `APP_API_KEY` | No | — | If set, `/process` and `/report` require `X-API-Key` |
| `LOG_LEVEL` | No | `INFO` | Python log level |

## API endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health/config summary |
| GET | `/webhook` | Meta verification handshake |
| POST | `/webhook` | Meta message events |
| POST | `/process` | Manual invoice upload (multipart `file`) |
| GET | `/report` | Download the Excel report |
| GET | `/docs` | Swagger UI |

## Tests

```bash
pytest -q
```

The tests mock Gemini and WhatsApp, so they do not need API keys or network access. They cover:

- health and webhook verification;
- manual upload → Excel row;
- unsupported file rejection;
- optional API-key protection;
- full WhatsApp image flow → Excel row → reply.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `GOOGLE_API_KEY no está configurada` | Key missing from `.env`; restart the app. |
| `404` or `400` from Gemini | `GEMINI_MODEL` is not available to your project; try `gemini-3.5-flash-lite` or `gemini-3.8-flash`. |
| `429 RESOURCE_EXHAUSTED` | Free-tier rate limit; wait and retry. |
| Meta webhook verification fails | Token mismatch, URL must end in `/webhook`, server not reachable, or Funnel not running. |
| Row is written but no WhatsApp reply | `WHATSAPP_TOKEN` expired or `WHATSAPP_PHONE_NUMBER_ID` wrong; check `docker compose logs`. |
| Media download returns `401` | WhatsApp token expired (temporary tokens last 24 hours). |
| `PermissionError` saving the Excel file | Workbook is open in Excel, or the `data` directory is not writable. |
| `docker compose` cannot find `.env` | Run `cp .env.example .env` first. |

## MVP limitations

- **No webhook deduplication.** Meta can retry a delivery; the same invoice may be appended twice. The next iteration should store processed `message.id` values in SQLite.
- **Single process only.** Excel writes are protected by an in-process lock. Run one uvicorn worker and one container replica.
- **No database.** The workbook is the source of truth.
- **No human review.** Extraction mistakes go straight into the report.
- **Only five fields.** Subtotal, ITBIS, currency, line items, and payment method are not stored. The reply assumes the total is in DOP (RD$).
- **One invoice per file.** Multi-invoice PDFs are not split.
- **Default layout only.** A custom budget template needs a small change in `app/sheets.py`.
- **Public endpoints.** Tailscale Funnel exposes the service. Set `APP_API_KEY` for `/process` and `/report`, and `WHATSAPP_APP_SECRET` for webhook signature checks.
- **No queue/retry.** If Gemini or WhatsApp is unavailable, the message is lost after the error reply.
- **No media storage.** Files are processed in memory and not archived.

## Suggested next steps

1. Deduplicate webhook deliveries using `message.id` in SQLite.
2. Add a confirmation step: reply with the extracted fields and let the user confirm before writing.
3. Add ITBIS, subtotal, currency, and line-item extraction.
4. Add a Google Sheets backend (`gspread`) if the report should live in the cloud.
5. Add real invoice fixtures and accuracy checks to the test suite.
6. Move to a permanent WhatsApp System User token.
7. Add authentication and rate limiting before exposing this beyond a personal PoC.

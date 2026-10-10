# Bulk Certificate Generator

&copy; 2026 Rajesh. Built for the Aereo project.

A FastAPI backend that takes a list of recipients, validates each one, generates a PDF certificate per valid recipient in the background, tracks job progress, and lets you download the PDFs individually or as a ZIP. A single-page UI is served at `/`.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Requires Python 3.11+.

## Run

```bash
uvicorn app.main:app --reload
```

- UI: http://127.0.0.1:8000/
- API docs (Swagger): http://127.0.0.1:8000/docs

Environment variables (all optional): `DATABASE_URL` (default `sqlite:///./certificates.db`), `STORAGE_DIR` (default `storage`), `RESEND_API_KEY` and `EMAIL_FROM` (see below).

### Emailing certificates (optional)

The UI always requests emailing; API clients send `"send_email": true` in the POST body. Delivery uses [Resend](https://resend.com):

```bash
export RESEND_API_KEY=re_xxxxxxxx
export EMAIL_FROM="Aereo <certificates@your-verified-domain.com>"   # default is Resend's test sender
uvicorn app.main:app --reload
```

Without `RESEND_API_KEY` nothing changes: certificates are generated as usual and each row gets `email_status: "skipped"`. Email results are stored per certificate (`sent`, `failed` plus `email_error`, or `skipped`), and an email failure never marks the certificate itself as failed. Note that Resend's test sender can only deliver to your own account email until you verify a domain.

## Tests

```bash
pytest
```

Tests use a temporary SQLite DB and a temporary storage directory. Starlette's `TestClient` runs background tasks before returning, so tests can assert on the final job state directly.

## Usage with curl

Submit a job (this one contains an invalid email and a duplicate):

```bash
curl -s -X POST http://127.0.0.1:8000/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "event_name": "Intro to Python",
    "issue_date": "2025-01-15",
    "issuer_name": "Jane Smith, Director",
    "recipients": [
      {"name": "Ada Lovelace", "email": "ada@example.com"},
      {"name": "Bad Email", "email": "nope"},
      {"name": "Ada Again", "email": "ada@example.com"}
    ]
  }'
# -> {"job_id":"<JOB_ID>","status":"pending","total_count":3,"invalid_count":2}
```

Poll status (counts, percentage, per-certificate status and `download_url`):

```bash
curl -s http://127.0.0.1:8000/api/jobs/<JOB_ID>
```

Download one certificate, or everything as a ZIP:

```bash
curl -o cert.pdf http://127.0.0.1:8000/api/jobs/<JOB_ID>/certificates/<CERT_ID>/download
curl -o certificates.zip http://127.0.0.1:8000/api/jobs/<JOB_ID>/download
```

## API reference

| Method | Path | Description | Responses |
|---|---|---|---|
| POST | `/api/jobs` | Create a job. Body: `event_name`, optional `issue_date` (default today), optional `issuer_name`, optional `send_email` (default false), `recipients[{name,email}]` (1–1000) | 202 `{job_id, status, total_count, invalid_count}`; 422 for empty/oversized list or blank `event_name` |
| GET | `/api/jobs` | 20 most recent jobs | 200 |
| GET | `/api/jobs/{job_id}` | Status, counts, percentage, certificates (with `download_url` when successful) | 200; 404 |
| GET | `/api/jobs/{job_id}/certificates/{certificate_id}/download` | One PDF (`application/pdf`) | 200; 404 unknown job/certificate; 409 not generated or failed |
| GET | `/api/jobs/{job_id}/download` | ZIP of all successful PDFs | 200; 404 unknown job; 409 still processing or nothing generated |
| GET | `/health` | Liveness check | 200 |

Job statuses: `pending`, `processing`, `completed` (all succeeded), `completed_with_errors` (some failed), `failed` (all failed). Certificate statuses: `pending`, `success`, `failed`.

## Design decisions

**FastAPI + SQLite.** FastAPI gives request validation, OpenAPI docs and a test client with little code. SQLite needs no setup; SQLAlchemy keeps the code database-agnostic, so setting `DATABASE_URL` to a Postgres URL is the only change needed (plus installing a driver).

**Background processing (BackgroundTasks).** Generating up to 1000 PDFs takes far too long for one HTTP request, so `POST /api/jobs` stores the job, schedules a worker and returns `202` with the job id straight away. The worker (`services/processor.py`) handles recipients one by one and commits after each, so polling `GET /api/jobs/{id}` shows live progress.
*Tradeoff:* `BackgroundTasks` runs inside the web process. If the server restarts mid-job, the job stays `processing` forever and the work is lost; it also competes with request handling for CPU and can't scale across machines. A production system would use Celery or RQ with a broker (Redis/RabbitMQ) and separate workers, and on startup would re-queue jobs left in `processing` (the worker skips certificates that are already done, so re-running is safe to design for).

**Per-recipient failure isolation.** Each certificate is generated inside its own `try/except`. A failure marks only that certificate `failed` with the error message, and the loop continues. The final job status is derived from the counts.

**Validation strategy.** Two levels. Request-level problems (empty list, over 1000, blank `event_name`) are rejected with 422 by Pydantic. Recipients are accepted as loose items and checked one by one in `services/validation.py` (name non-empty, trimmed, ≤100 chars; valid email via `email-validator`, format only; duplicate emails, case-insensitive, within the request). A bad recipient never rejects the whole request.

**Invalid recipients are stored as failed rows.** They become `Certificate` rows with `status=failed` and a clear `error_message`. The client then gets one list that accounts for every submitted recipient, in order, instead of silently losing some.

**File storage layout.** `storage/<job_id>/<certificate_id>.pdf`. Paths are built only from server-generated UUIDs, never from user input, so names can't cause path traversal. Names are sanitized only where they appear in download filenames and ZIP entries. The PDF generator shrinks text to fit the page and uses a Unicode font (e.g. Arial Unicode on macOS, DejaVu on Linux) if one is found, falling back to Helvetica (non-Latin characters may not render in that case).

**Testability.** The worker calls `generator.generate_certificate_pdf(...)` through the module, so tests can monkeypatch it to simulate failures.

## Known limitations and next steps

- Move to Celery/RQ + Redis, with startup re-queue of stuck `processing` jobs.
- Store PDFs in S3 (or similar) and serve pre-signed URLs instead of local disk.
- Send emails from a separate queue with retries (currently sent inline by the worker).
- Add authentication and per-user job ownership (job IDs are currently the only access control).
- Add rate limiting and request size limits.
- Add a retry endpoint to regenerate failed certificates for a job.
- Use Alembic migrations instead of `create_all` on startup.
- Only one template; no cleanup/retention of old files.

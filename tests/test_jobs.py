import io
import zipfile

from app import database
from app.models import Certificate, Job
from app.config import settings
from app.services import emailer, generator
from tests.conftest import make_payload


def create(client, **kwargs):
    res = client.post("/api/jobs", json=make_payload(**kwargs))
    assert res.status_code == 202, res.text
    return res.json()


# ---------- creating a job ----------

def test_create_job_returns_202_and_creates_rows(client):
    body = create(client)
    assert body["total_count"] == 2
    assert body["invalid_count"] == 0
    assert body["status"] == "pending"  # response is sent before the worker runs

    db = database.SessionLocal()
    assert db.get(Job, body["job_id"]) is not None
    assert db.query(Certificate).filter_by(job_id=body["job_id"]).count() == 2


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


# ---------- request-level validation ----------

def test_empty_recipients_is_422(client):
    assert client.post("/api/jobs", json=make_payload(recipients=[])).status_code == 422


def test_missing_or_blank_event_name_is_422(client):
    payload = make_payload()
    del payload["event_name"]
    assert client.post("/api/jobs", json=payload).status_code == 422
    assert client.post("/api/jobs", json=make_payload(event_name="   ")).status_code == 422


def test_too_many_recipients_is_422(client):
    many = [{"name": f"P{i}", "email": f"p{i}@example.com"} for i in range(1001)]
    assert client.post("/api/jobs", json=make_payload(recipients=many)).status_code == 422


# ---------- recipient-level validation ----------

def test_invalid_recipients_are_marked_failed_not_rejected(client):
    body = create(client, recipients=[
        {"name": "Good Person", "email": "good@example.com"},
        {"name": "Bad Email", "email": "not-an-email"},
        {"name": "   ", "email": "blank@example.com"},
        {"name": "x" * 101, "email": "long@example.com"},
        "not even an object",
    ])
    assert body["invalid_count"] == 4

    job = client.get(f"/api/jobs/{body['job_id']}").json()
    assert job["status"] == "completed_with_errors"
    errors = [c["error_message"] for c in job["certificates"]]
    assert errors[0] is None
    assert errors[1] == "invalid email format"
    assert errors[2] == "name is required"
    assert "100 characters" in errors[3]
    assert [c["status"] for c in job["certificates"]] == ["success"] + ["failed"] * 4


def test_duplicate_email_is_flagged(client):
    body = create(client, recipients=[
        {"name": "First", "email": "same@example.com"},
        {"name": "Second", "email": "SAME@example.com"},
    ])
    job = client.get(f"/api/jobs/{body['job_id']}").json()
    assert job["certificates"][0]["status"] == "success"
    assert job["certificates"][1]["status"] == "failed"
    assert job["certificates"][1]["error_message"] == "duplicate email"


def test_names_are_trimmed(client):
    body = create(client, recipients=[{"name": "  Ada  ", "email": " ada@example.com "}])
    cert = client.get(f"/api/jobs/{body['job_id']}").json()["certificates"][0]
    assert cert["recipient_name"] == "Ada"
    assert cert["recipient_email"] == "ada@example.com"


# ---------- generation ----------

def test_pdf_is_generated(client):
    body = create(client)
    db = database.SessionLocal()
    certs = db.query(Certificate).filter_by(job_id=body["job_id"]).all()
    for cert in certs:
        assert cert.file_path.endswith(f"{body['job_id']}/{cert.id}.pdf")
        with open(cert.file_path, "rb") as f:
            data = f.read()
        assert len(data) > 0
        assert data.startswith(b"%PDF")


def test_long_and_unicode_names_do_not_crash(client):
    body = create(client, recipients=[
        {"name": "Zoë Åström-Nguyen 王小明", "email": "u@example.com"},
        {"name": "W" * 100, "email": "long@example.com"},
    ], event_name="E" * 150)
    assert client.get(f"/api/jobs/{body['job_id']}").json()["status"] == "completed"


# ---------- status and progress ----------

def test_job_status_and_progress(client):
    body = create(client)
    job = client.get(f"/api/jobs/{body['job_id']}").json()
    assert job["status"] == "completed"
    assert (job["total_count"], job["success_count"], job["failed_count"]) == (2, 2, 0)
    assert job["percentage"] == 100.0
    assert all(c["download_url"] for c in job["certificates"])


def test_all_invalid_job_is_failed(client):
    body = create(client, recipients=[{"name": "", "email": "x"}])
    assert client.get(f"/api/jobs/{body['job_id']}").json()["status"] == "failed"


def test_unknown_job_is_404(client):
    assert client.get("/api/jobs/does-not-exist").status_code == 404


def test_list_jobs(client):
    create(client)
    jobs = client.get("/api/jobs").json()
    assert len(jobs) == 1 and jobs[0]["event_name"] == "Intro to Python"


# ---------- individual failure ----------

def test_one_generation_failure_does_not_stop_the_rest(client, monkeypatch):
    real = generator.generate_certificate_pdf

    def flaky(output_path, recipient_name, *args, **kwargs):
        if recipient_name == "Grace Hopper":
            raise RuntimeError("boom")
        return real(output_path, recipient_name, *args, **kwargs)

    monkeypatch.setattr(generator, "generate_certificate_pdf", flaky)
    body = create(client, recipients=[
        {"name": "Ada Lovelace", "email": "ada@example.com"},
        {"name": "Grace Hopper", "email": "grace@example.com"},
        {"name": "Alan Turing", "email": "alan@example.com"},
    ])

    job = client.get(f"/api/jobs/{body['job_id']}").json()
    assert job["status"] == "completed_with_errors"
    assert (job["success_count"], job["failed_count"]) == (2, 1)
    statuses = {c["recipient_name"]: c for c in job["certificates"]}
    assert statuses["Ada Lovelace"]["status"] == "success"
    assert statuses["Alan Turing"]["status"] == "success"
    assert statuses["Grace Hopper"]["status"] == "failed"
    assert "boom" in statuses["Grace Hopper"]["error_message"]


def test_all_generation_failures_mark_job_failed(client, monkeypatch):
    def always_fail(*args, **kwargs):
        raise RuntimeError("nope")

    monkeypatch.setattr(generator, "generate_certificate_pdf", always_fail)
    body = create(client)
    assert client.get(f"/api/jobs/{body['job_id']}").json()["status"] == "failed"


# ---------- downloads ----------

def test_download_single_pdf(client):
    body = create(client)
    cert = client.get(f"/api/jobs/{body['job_id']}").json()["certificates"][0]
    res = client.get(cert["download_url"])
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF")


def test_download_zip(client):
    body = create(client, recipients=[
        {"name": "Ada Lovelace", "email": "ada@example.com"},
        {"name": "Bad", "email": "bad"},
        {"name": "Grace Hopper", "email": "grace@example.com"},
    ])
    res = client.get(f"/api/jobs/{body['job_id']}/download")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        assert sorted(zf.namelist()) == ["0001_Ada_Lovelace.pdf", "0003_Grace_Hopper.pdf"]
        assert zf.read("0001_Ada_Lovelace.pdf").startswith(b"%PDF")


def test_download_404s(client):
    body = create(client)
    job_id = body["job_id"]
    cert_id = client.get(f"/api/jobs/{job_id}").json()["certificates"][0]["id"]
    assert client.get("/api/jobs/nope/download").status_code == 404
    assert client.get(f"/api/jobs/nope/certificates/{cert_id}/download").status_code == 404
    assert client.get(f"/api/jobs/{job_id}/certificates/nope/download").status_code == 404


def test_download_failed_certificate_is_409(client):
    body = create(client, recipients=[
        {"name": "Good", "email": "good@example.com"},
        {"name": "Bad", "email": "bad"},
    ])
    bad = client.get(f"/api/jobs/{body['job_id']}").json()["certificates"][1]
    res = client.get(f"/api/jobs/{body['job_id']}/certificates/{bad['id']}/download")
    assert res.status_code == 409


def test_zip_while_processing_is_409(client):
    body = create(client)
    db = database.SessionLocal()
    job = db.get(Job, body["job_id"])
    job.status = "processing"  # simulate a job that hasn't finished
    db.commit()
    assert client.get(f"/api/jobs/{body['job_id']}/download").status_code == 409


def test_zip_with_no_successes_is_409(client):
    body = create(client, recipients=[{"name": "Bad", "email": "bad"}])
    assert client.get(f"/api/jobs/{body['job_id']}/download").status_code == 409


# ---------- optional email ----------

def test_email_skipped_without_api_key(client, monkeypatch):
    monkeypatch.setattr(settings, "resend_api_key", "")
    body = create(client, send_email=True)
    job = client.get(f"/api/jobs/{body['job_id']}").json()
    assert job["status"] == "completed"  # certificates still generated as usual
    assert {c["email_status"] for c in job["certificates"]} == {"skipped"}


def test_email_sent_and_failure_is_isolated(client, monkeypatch):
    monkeypatch.setattr(settings, "resend_api_key", "test-key")
    sent = []

    def fake_send(to_email, name, event_name, pdf_path):
        if name == "Grace Hopper":
            raise RuntimeError("mailbox full")
        sent.append(to_email)

    monkeypatch.setattr(emailer, "send_certificate_email", fake_send)
    body = create(client, send_email=True)
    job = client.get(f"/api/jobs/{body['job_id']}").json()
    by_name = {c["recipient_name"]: c for c in job["certificates"]}
    assert sent == ["ada@example.com"]
    assert by_name["Ada Lovelace"]["email_status"] == "sent"
    assert by_name["Grace Hopper"]["email_status"] == "failed"
    assert by_name["Grace Hopper"]["status"] == "success"  # email failure doesn't fail the certificate
    assert job["status"] == "completed"


def test_no_email_when_not_requested(client):
    body = create(client)
    job = client.get(f"/api/jobs/{body['job_id']}").json()
    assert all(c["email_status"] is None for c in job["certificates"])

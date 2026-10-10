"""Background worker that turns a job's recipients into PDFs."""
import os

from app.config import settings
from app.models import Certificate, Job
from app.services import emailer, generator


def process_job(job_id: str, session_factory) -> None:
    """Generate PDFs for one job, one certificate at a time.

    Runs in a FastAPI BackgroundTask, so it opens its own DB session
    (the request's session is closed once the response is sent).
    """
    db = session_factory()
    try:
        job = db.get(Job, job_id)
        job.status = "processing"
        db.commit()

        output_dir = os.path.join(settings.storage_dir, job.id)
        os.makedirs(output_dir, exist_ok=True)

        for cert in job.certificates:
            if cert.status == "failed":
                continue  # failed validation at submit time; already counted

            try:
                # Path comes from our own UUIDs, never from user input.
                path = os.path.join(output_dir, f"{cert.id}.pdf")
                generator.generate_certificate_pdf(
                    path, cert.recipient_name, job.event_name, job.issue_date, job.issuer_name
                )
                cert.status = "success"
                cert.file_path = path
                job.success_count += 1
                if job.send_email:
                    _send_email(cert, job)
            except Exception as exc:
                # One bad certificate must not stop the rest of the job.
                cert.status = "failed"
                cert.error_message = f"generation failed: {exc}"
                job.failed_count += 1

            db.commit()  # commit per certificate so polling sees live progress

        job.status = _final_status(job)
        db.commit()
    except Exception:
        # Something unexpected (e.g. disk or DB error): don't leave the job "processing".
        db.rollback()
        job = db.get(Job, job_id)
        job.status = "failed"
        db.commit()
    finally:
        db.close()


def _send_email(cert: Certificate, job: Job) -> None:
    """Email one certificate. The result is stored on the row; errors never propagate."""
    if not emailer.is_enabled():
        cert.email_status = "skipped"
        cert.email_error = "RESEND_API_KEY not set"
        return
    try:
        emailer.send_certificate_email(cert.recipient_email, cert.recipient_name, job.event_name, cert.file_path)
        cert.email_status = "sent"
    except Exception as exc:
        cert.email_status = "failed"
        cert.email_error = str(exc)


def _final_status(job: Job) -> str:
    if job.failed_count == 0:
        return "completed"
    if job.success_count == 0:
        return "failed"
    return "completed_with_errors"

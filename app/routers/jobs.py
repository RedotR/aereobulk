import io
import os
import re
import zipfile
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import database
from app.database import get_db
from app.models import Certificate, Job
from app.schemas import CertificateOut, JobCreate, JobCreated, JobDetail, JobSummary
from app.services.processor import process_job
from app.services.validation import validate_recipients

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def safe_filename(text: str) -> str:
    """Keep letters/digits (any language) only so names are safe inside zip entries and headers."""
    return re.sub(r"[^\w-]+", "_", text).strip("_") or "certificate"


def get_job_or_404(db: Session, job_id: str) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


@router.post("", status_code=202, response_model=JobCreated)
def create_job(body: JobCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    checked = validate_recipients(body.recipients)
    invalid_count = sum(1 for r in checked if r.error)

    # Invalid recipients are stored too (as failed rows) so the client can see them.
    job = Job(
        event_name=body.event_name,
        issue_date=body.issue_date or date.today(),
        issuer_name=body.issuer_name,
        send_email=body.send_email,
        total_count=len(checked),
        failed_count=invalid_count,
    )
    for i, r in enumerate(checked):
        job.certificates.append(
            Certificate(
                recipient_name=r.name,
                recipient_email=r.email,
                status="failed" if r.error else "pending",
                error_message=r.error,
                index=i,
            )
        )
    db.add(job)
    db.commit()

    # Runs after the 202 response is sent. SessionLocal is read here (not imported
    # by name) so tests can replace it.
    background_tasks.add_task(process_job, job.id, database.SessionLocal)
    return JobCreated(
        job_id=job.id, status=job.status, total_count=job.total_count, invalid_count=invalid_count
    )


@router.get("", response_model=list[JobSummary])
def list_jobs(db: Session = Depends(get_db)):
    return db.scalars(select(Job).order_by(Job.created_at.desc()).limit(20)).all()


@router.get("/{job_id}", response_model=JobDetail)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = get_job_or_404(db, job_id)
    done = job.success_count + job.failed_count
    certificates = [
        CertificateOut(
            id=c.id,
            recipient_name=c.recipient_name,
            recipient_email=c.recipient_email,
            status=c.status,
            error_message=c.error_message,
            email_status=c.email_status,
            email_error=c.email_error,
            download_url=f"/api/jobs/{job.id}/certificates/{c.id}/download"
            if c.status == "success"
            else None,
        )
        for c in job.certificates
    ]
    return JobDetail(
        **JobSummary.model_validate(job, from_attributes=True).model_dump(),
        issue_date=job.issue_date,
        issuer_name=job.issuer_name,
        send_email=job.send_email,
        updated_at=job.updated_at,
        percentage=round(100 * done / job.total_count, 1) if job.total_count else 0.0,
        certificates=certificates,
    )


@router.get("/{job_id}/certificates/{certificate_id}/download")
def download_certificate(job_id: str, certificate_id: str, db: Session = Depends(get_db)):
    get_job_or_404(db, job_id)
    cert = db.get(Certificate, certificate_id)
    if cert is None or cert.job_id != job_id:
        raise HTTPException(404, "Certificate not found")
    if cert.status != "success" or not cert.file_path or not os.path.exists(cert.file_path):
        raise HTTPException(409, f"Certificate is not available (status: {cert.status})")
    return FileResponse(
        cert.file_path,
        media_type="application/pdf",
        filename=f"{safe_filename(cert.recipient_name)}.pdf",
    )


@router.get("/{job_id}/download")
def download_zip(job_id: str, db: Session = Depends(get_db)):
    job = get_job_or_404(db, job_id)
    if job.status in ("pending", "processing"):
        raise HTTPException(409, "Job is still processing")

    successful = [c for c in job.certificates if c.status == "success"]
    if not successful:
        raise HTTPException(409, "No certificates were generated for this job")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for c in successful:
            # Prefix with the position so two people with the same name don't collide.
            zf.write(c.file_path, f"{c.index + 1:04d}_{safe_filename(c.recipient_name)}.pdf")

    return Response(
        buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="certificates_{job.id[:8]}.zip"'},
    )

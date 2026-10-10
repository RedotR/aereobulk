from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.config import settings


class JobCreate(BaseModel):
    event_name: str
    issue_date: date | None = None  # defaults to today in the router
    issuer_name: str | None = None
    send_email: bool = False  # email each PDF to its recipient (needs RESEND_API_KEY)
    # Recipients are deliberately loose (list[Any]): a bad recipient must not
    # reject the whole request. Each one is checked in services/validation.py.
    recipients: list[Any] = Field(min_length=1, max_length=settings.max_recipients)

    @field_validator("event_name")
    @classmethod
    def event_name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("event_name must not be blank")
        return v

    @field_validator("issuer_name")
    @classmethod
    def blank_issuer_is_none(cls, v: str | None) -> str | None:
        return (v or "").strip() or None


class JobCreated(BaseModel):
    job_id: str
    status: str
    total_count: int
    invalid_count: int


class CertificateOut(BaseModel):
    id: str
    recipient_name: str
    recipient_email: str
    status: str
    error_message: str | None
    email_status: str | None
    email_error: str | None
    download_url: str | None  # only set when status == "success"


class JobSummary(BaseModel):
    id: str
    status: str
    event_name: str
    total_count: int
    success_count: int
    failed_count: int
    created_at: datetime


class JobDetail(JobSummary):
    issue_date: date
    issuer_name: str | None
    send_email: bool
    percentage: float
    updated_at: datetime
    certificates: list[CertificateOut]

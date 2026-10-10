import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def new_id() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    # pending | processing | completed | completed_with_errors | failed
    status: Mapped[str] = mapped_column(String(30), default="pending")
    event_name: Mapped[str] = mapped_column(String(200))
    issue_date: Mapped[date] = mapped_column(Date)
    issuer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    send_email: Mapped[bool] = mapped_column(Boolean, default=False)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    certificates: Mapped[list["Certificate"]] = relationship(
        back_populates="job", order_by="Certificate.index", cascade="all, delete-orphan"
    )


class Certificate(Base):
    __tablename__ = "certificates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    recipient_name: Mapped[str] = mapped_column(String(500))
    recipient_email: Mapped[str] = mapped_column(String(500))
    # pending | success | failed
    status: Mapped[str] = mapped_column(String(20), default="pending")
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Email delivery is tracked separately so an email problem never fails the certificate.
    # None (not requested) | sent | skipped (no API key) | failed
    email_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    index: Mapped[int] = mapped_column(Integer)  # position in the original request

    job: Mapped[Job] = relationship(back_populates="certificates")

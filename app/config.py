"""Copyright (c) 2026 Rajesh - Aereo project.

App settings. Everything can be overridden with environment variables."""
import os
from dataclasses import dataclass


@dataclass
class Settings:
    # Swap for e.g. postgresql+psycopg://user:pw@host/db to use Postgres.
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./certificates.db")
    storage_dir: str = os.getenv("STORAGE_DIR", "storage")
    # Email is optional: without RESEND_API_KEY certificates are just generated.
    resend_api_key: str = os.getenv("RESEND_API_KEY", "")
    email_from: str = os.getenv("EMAIL_FROM", "Aereo <onboarding@resend.dev>")
    max_recipients: int = 1000
    max_name_length: int = 100


# One shared instance. Tests change its fields (e.g. storage_dir) directly.
settings = Settings()

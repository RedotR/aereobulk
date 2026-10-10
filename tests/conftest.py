import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import database
from app.config import settings
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient wired to a temporary SQLite DB and a temporary storage dir."""
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    database.Base.metadata.create_all(engine)
    # Both the request handlers and the background worker read SessionLocal at call time.
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    return TestClient(app)


def make_payload(recipients=None, **overrides):
    payload = {
        "event_name": "Intro to Python",
        "issue_date": "2025-01-15",
        "issuer_name": "Jane Smith",
        "recipients": recipients
        if recipients is not None
        else [
            {"name": "Ada Lovelace", "email": "ada@example.com"},
            {"name": "Grace Hopper", "email": "grace@example.com"},
        ],
    }
    payload.update(overrides)
    return payload

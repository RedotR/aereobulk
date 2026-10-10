"""Bulk Certificate Generator - Copyright (c) 2026 Rajesh, for the Aereo project."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app import database, models  # noqa: F401  (models must be imported to register tables)
from app.routers import jobs

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.Base.metadata.create_all(database.engine)  # create tables on startup
    # Production idea: re-queue jobs still marked "processing" here (see README).
    yield


app = FastAPI(title="Bulk Certificate Generator", lifespan=lifespan)
app.include_router(jobs.router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")

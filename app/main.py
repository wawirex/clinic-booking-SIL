from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.errors import DomainError
from app.routers import appointments, doctors, patients
from app.seed import seed


@asynccontextmanager
async def lifespan(_: FastAPI):
    # create_all is enough for this scope; see README for the Alembic trade-off.
    Base.metadata.create_all(engine)
    if settings.seed_on_startup:
        with SessionLocal() as db:
            seed(db)
    yield


app = FastAPI(title="Clinic Booking API", version="1.0.0", lifespan=lifespan)
app.include_router(doctors.router)
app.include_router(appointments.router)
app.include_router(patients.router)


@app.exception_handler(DomainError)
async def domain_error_handler(_: Request, exc: DomainError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(RequestValidationError)
async def request_validation_handler(_: Request, exc: RequestValidationError):
    details = [
        {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]}
        for e in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "validation_error", "message": "Request validation failed.", "details": details}},
    )


@app.get("/health", tags=["meta"])
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}

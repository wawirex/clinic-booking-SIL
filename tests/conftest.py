from datetime import datetime, time, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import clock
from app.database import Base, get_db
from app.main import app
from app.models import Doctor, DoctorSchedule, Patient

# Monday 2030-01-07 08:00 in Nairobi (05:00 UTC). Far-future fixed date => tests never rot.
FROZEN_NOW = datetime(2030, 1, 7, 5, 0, tzinfo=timezone.utc)


def at(day: str, hhmm: str) -> str:
    """Nairobi-local ISO timestamp, e.g. at('2030-01-08', '10:00')."""
    return f"{day}T{hhmm}:00+03:00"


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def world(db_session):
    """One doctor (Mon-Fri 08-12, 13-17) and two patients."""
    doctor = Doctor(name="Dr. Test")
    db_session.add(doctor)
    db_session.flush()
    for wd in range(5):
        db_session.add(DoctorSchedule(doctor_id=doctor.id, weekday=wd, start_time=time(8), end_time=time(12)))
        db_session.add(DoctorSchedule(doctor_id=doctor.id, weekday=wd, start_time=time(13), end_time=time(17)))
    p1 = Patient(name="Pat One", email="one@example.com")
    p2 = Patient(name="Pat Two", email="two@example.com")
    db_session.add_all([p1, p2])
    db_session.commit()
    return {"doctor": doctor, "p1": p1, "p2": p2}


@pytest.fixture
def client(db_session, monkeypatch):
    monkeypatch.setattr(clock, "utcnow", lambda: FROZEN_NOW)
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)  # no `with`: skip lifespan (no seeding / real DB)
    app.dependency_overrides.clear()


@pytest.fixture
def book(client, world):
    def _book(start: str, patient: str = "p1", doctor_id: int | None = None):
        return client.post(
            "/appointments",
            json={
                "doctor_id": doctor_id or world["doctor"].id,
                "patient_id": world[patient].id,
                "start_time": start,
            },
        )

    return _book

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import clock
from app.database import get_db
from app.errors import ConflictError
from app.models import Patient
from app.schemas import AppointmentOut, PatientCreate, PatientOut
from app.services import booking

router = APIRouter(prefix="/patients", tags=["patients"])


@router.post("", response_model=PatientOut, status_code=status.HTTP_201_CREATED)
def create_patient(payload: PatientCreate, db: Session = Depends(get_db)):
    email = payload.email.lower()
    if db.scalar(select(Patient.id).where(Patient.email == email)) is not None:
        raise ConflictError("email_taken", "A patient with that email already exists.")
    patient = Patient(name=payload.name, email=email, phone=payload.phone)
    db.add(patient)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConflictError("email_taken", "A patient with that email already exists.") from None
    return patient


@router.get("/{patient_id}/appointments", response_model=list[AppointmentOut])
def upcoming_appointments(patient_id: int, db: Session = Depends(get_db)):
    """Upcoming (not cancelled, not yet started) appointments, soonest first."""
    return booking.upcoming_for_patient(db, patient_id, clock.utcnow())

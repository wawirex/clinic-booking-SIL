from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app import clock
from app.database import get_db
from app.schemas import AppointmentCreate, AppointmentOut, CancelRequest, RescheduleRequest
from app.services import booking
from app.services.booking import _get_or_404
from app.models import Appointment

router = APIRouter(prefix="/appointments", tags=["appointments"])


@router.post("", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED)
def book_appointment(payload: AppointmentCreate, db: Session = Depends(get_db)):
    return booking.book(
        db,
        doctor_id=payload.doctor_id,
        patient_id=payload.patient_id,
        start=payload.start_time,
        now=clock.utcnow(),
    )


@router.get("/{appointment_id}", response_model=AppointmentOut)
def get_appointment(appointment_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, Appointment, appointment_id, "appointment")


@router.patch("/{appointment_id}/cancel", response_model=AppointmentOut)
def cancel_appointment(appointment_id: int, payload: CancelRequest, db: Session = Depends(get_db)):
    return booking.cancel(db, appointment_id, payload.reason, clock.utcnow())


@router.patch("/{appointment_id}/reschedule", response_model=AppointmentOut)
def reschedule_appointment(appointment_id: int, payload: RescheduleRequest, db: Session = Depends(get_db)):
    return booking.reschedule(db, appointment_id, payload.new_start_time, clock.utcnow())

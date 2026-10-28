from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.config import settings
from app.database import get_db
from app.models import Doctor
from app.schemas import AvailabilityOut, DoctorOut, SlotOut
from app.services import availability
from app.services.booking import _get_or_404

router = APIRouter(prefix="/doctors", tags=["doctors"])


@router.get("", response_model=list[DoctorOut])
def list_doctors(db: Session = Depends(get_db)):
    return list(db.scalars(select(Doctor).order_by(Doctor.id)))


@router.get("/{doctor_id}/availability", response_model=AvailabilityOut)
def doctor_availability(
    doctor_id: int,
    target_date: date = Query(alias="date", description="Clinic-local date, YYYY-MM-DD"),
    db: Session = Depends(get_db),
):
    _get_or_404(db, Doctor, doctor_id, "doctor")
    slots = availability.get_availability(db, doctor_id, target_date, clock.utcnow())
    return AvailabilityOut(
        doctor_id=doctor_id,
        date=target_date,
        timezone=settings.clinic_timezone,
        slot_minutes=settings.slot_minutes,
        slots=[SlotOut(start_time=s, end_time=e) for s, e in slots],
    )

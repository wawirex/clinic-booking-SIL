from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.errors import ConflictError, NotFoundError, UnprocessableError
from app.models import Appointment, AppointmentStatus, Doctor, Patient
from app.services import availability


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


def _get_or_404(db: Session, model, obj_id: int, label: str):
    obj = db.get(model, obj_id)
    if obj is None:
        raise NotFoundError(f"{label}_not_found", f"{label.capitalize()} {obj_id} does not exist.")
    return obj


def validate_slot(
    db: Session, doctor_id: int, start: datetime, now: datetime, exclude_appointment_id: int | None = None
) -> None:
    """Rules shared by booking and rescheduling, so a reschedule is validated like a fresh booking."""
    tz = settings.tz
    local = start.astimezone(tz)

    if start <= now:
        raise UnprocessableError("slot_in_past", "Appointments cannot be booked in the past.")

    if start < now + timedelta(minutes=settings.min_lead_minutes):
        raise UnprocessableError(
            "slot_too_soon",
            f"Appointments must be booked at least {settings.min_lead_minutes} minutes in advance.",
        )

    valid_starts = {s[0] for s in availability.generate_slots(db, doctor_id, local.date())}
    if start not in valid_starts:
        if availability.within_a_block(db, doctor_id, start):
            raise UnprocessableError(
                "slot_not_aligned",
                f"Slots start on {settings.slot_minutes}-minute boundaries within the doctor's hours "
                f"(you sent {local:%H:%M:%S}).",
            )
        raise UnprocessableError(
            "outside_working_hours",
            f"Doctor {doctor_id} does not work at {local:%A %Y-%m-%d %H:%M}.",
        )

    clash = select(Appointment.id).where(
        Appointment.doctor_id == doctor_id,
        Appointment.start_time == start,
        Appointment.status == AppointmentStatus.BOOKED.value,
    )
    if exclude_appointment_id is not None:
        clash = clash.where(Appointment.id != exclude_appointment_id)
    if db.scalar(clash) is not None:
        raise ConflictError("slot_taken", "That slot is already booked.")


def _commit_or_conflict(db: Session) -> None:
    """The unique partial index is the real guard against races; translate its failure to a 409."""
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConflictError("slot_taken", "That slot was just booked by someone else.") from None


def book(db: Session, *, doctor_id: int, patient_id: int, start: datetime, now: datetime) -> Appointment:
    _get_or_404(db, Doctor, doctor_id, "doctor")
    _get_or_404(db, Patient, patient_id, "patient")
    start = _utc(start)
    validate_slot(db, doctor_id, start, now)

    appt = Appointment(
        doctor_id=doctor_id,
        patient_id=patient_id,
        start_time=start,
        end_time=start + timedelta(minutes=settings.slot_minutes),
        status=AppointmentStatus.BOOKED.value,
    )
    db.add(appt)
    _commit_or_conflict(db)
    return appt


def cancel(db: Session, appointment_id: int, reason: str, now: datetime) -> Appointment:
    appt = _get_or_404(db, Appointment, appointment_id, "appointment")
    if appt.status == AppointmentStatus.CANCELLED.value:
        raise ConflictError("already_cancelled", "Appointment is already cancelled.")
    if appt.start_time <= now:
        raise ConflictError("appointment_already_started", "Past appointments cannot be cancelled.")

    appt.status = AppointmentStatus.CANCELLED.value
    appt.cancel_reason = reason
    appt.cancelled_at = now
    db.commit()
    return appt


def reschedule(db: Session, appointment_id: int, new_start: datetime, now: datetime) -> Appointment:
    appt = _get_or_404(db, Appointment, appointment_id, "appointment")
    if appt.status == AppointmentStatus.CANCELLED.value:
        raise ConflictError("appointment_cancelled", "Cancelled appointments cannot be rescheduled; book a new one.")
    if appt.start_time <= now:
        raise ConflictError("appointment_already_started", "Past appointments cannot be rescheduled.")

    new_start = _utc(new_start)
    if new_start == appt.start_time:
        raise UnprocessableError("same_slot", "The appointment is already at that time.")

    validate_slot(db, appt.doctor_id, new_start, now, exclude_appointment_id=appt.id)

    # Single UPDATE of the same row inside one transaction: the old slot is released and the
    # new one claimed atomically. If the new slot fails, nothing changes.
    appt.start_time = new_start
    appt.end_time = new_start + timedelta(minutes=settings.slot_minutes)
    _commit_or_conflict(db)
    return appt


def upcoming_for_patient(db: Session, patient_id: int, now: datetime) -> list[Appointment]:
    _get_or_404(db, Patient, patient_id, "patient")
    stmt = (
        select(Appointment)
        .where(
            Appointment.patient_id == patient_id,
            Appointment.status == AppointmentStatus.BOOKED.value,
            Appointment.start_time >= now,
        )
        .order_by(Appointment.start_time)
    )
    return list(db.scalars(stmt))

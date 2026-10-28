from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Appointment, AppointmentStatus, DoctorSchedule

Slot = tuple[datetime, datetime]  # (start, end), tz-aware UTC


def _blocks(db: Session, doctor_id: int, weekday: int) -> list[DoctorSchedule]:
    stmt = (
        select(DoctorSchedule)
        .where(DoctorSchedule.doctor_id == doctor_id, DoctorSchedule.weekday == weekday)
        .order_by(DoctorSchedule.start_time)
    )
    return list(db.scalars(stmt))


def generate_slots(db: Session, doctor_id: int, day: date) -> list[Slot]:
    """Every slot in the doctor's working hours on a clinic-local calendar day (booked or not).

    Slots are computed from the weekly schedule instead of being stored, so there is
    nothing to pre-generate or keep in sync when schedules change.
    """
    tz = settings.tz
    step = timedelta(minutes=settings.slot_minutes)
    slots: list[Slot] = []
    for block in _blocks(db, doctor_id, day.weekday()):
        cur = datetime.combine(day, block.start_time, tzinfo=tz)
        end = datetime.combine(day, block.end_time, tzinfo=tz)
        while cur + step <= end:
            slots.append((cur.astimezone(timezone.utc), (cur + step).astimezone(timezone.utc)))
            cur += step
    return slots


def within_a_block(db: Session, doctor_id: int, start: datetime) -> bool:
    """True if `start` falls inside working hours at all (used to tell 'misaligned' from 'closed')."""
    local = start.astimezone(settings.tz)
    return any(b.start_time <= local.time() < b.end_time for b in _blocks(db, doctor_id, local.weekday()))


def booked_starts(db: Session, doctor_id: int, slots: list[Slot]) -> set[datetime]:
    if not slots:
        return set()
    stmt = select(Appointment.start_time).where(
        Appointment.doctor_id == doctor_id,
        Appointment.status == AppointmentStatus.BOOKED.value,
        Appointment.start_time >= slots[0][0],
        Appointment.start_time <= slots[-1][0],
    )
    return set(db.scalars(stmt))


def get_availability(db: Session, doctor_id: int, day: date, now: datetime) -> list[Slot]:
    """Slots that are genuinely bookable right now: free, in the future, and past the lead time."""
    earliest = now + timedelta(minutes=settings.min_lead_minutes)
    slots = generate_slots(db, doctor_id, day)
    taken = booked_starts(db, doctor_id, slots)
    return [s for s in slots if s[0] not in taken and s[0] >= earliest]

import enum
from datetime import datetime, time, timezone

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, String, Text, Time, UniqueConstraint, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.database import Base


class UTCDateTime(TypeDecorator):
    """Always store UTC, always return timezone-aware UTC (SQLite drops tzinfo)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetime passed to UTCDateTime; attach a timezone first")
        value = value.astimezone(timezone.utc)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class AppointmentStatus(str, enum.Enum):
    BOOKED = "booked"
    CANCELLED = "cancelled"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    specialty: Mapped[str] = mapped_column(String(120), default="General Practice")

    schedules: Mapped[list["DoctorSchedule"]] = relationship(back_populates="doctor")


class DoctorSchedule(Base):
    """A working-hours block on a weekday (0=Monday). Several blocks per day allow lunch breaks."""

    __tablename__ = "doctor_schedules"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_schedule_weekday"),
        CheckConstraint("end_time > start_time", name="ck_schedule_order"),
        UniqueConstraint("doctor_id", "weekday", "start_time", name="uq_schedule_block"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"), index=True)
    weekday: Mapped[int]
    start_time: Mapped[time] = mapped_column(Time)  # local clinic time
    end_time: Mapped[time] = mapped_column(Time)

    doctor: Mapped[Doctor] = relationship(back_populates="schedules")


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        # The core invariant: at most ONE active booking per doctor per slot.
        # Cancelled rows are exempt, so a cancelled slot is immediately bookable again.
        Index(
            "uq_active_slot", "doctor_id", "start_time", unique=True,
            postgresql_where=text("status = 'booked'"),
            sqlite_where=text("status = 'booked'"),
        ),
        Index("ix_appointments_patient_start", "patient_id", "start_time"),
        CheckConstraint("status IN ('booked', 'cancelled')", name="ck_appointment_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"))
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"))
    start_time: Mapped[datetime] = mapped_column(UTCDateTime)
    end_time: Mapped[datetime] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(16), default=AppointmentStatus.BOOKED.value)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, onupdate=_now)

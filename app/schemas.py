from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_serializer, field_validator

from app.config import settings


def _to_local(value: datetime | None) -> datetime | None:
    return value.astimezone(settings.tz) if value else None


def _ensure_aware(value: datetime) -> datetime:
    """Naive datetimes are interpreted as clinic-local time (Africa/Nairobi by default)."""
    return value.replace(tzinfo=settings.tz) if value.tzinfo is None else value


class AppointmentCreate(BaseModel):
    doctor_id: int
    patient_id: int
    start_time: datetime = Field(description="ISO 8601. Naive values are treated as clinic-local time.")

    _aware = field_validator("start_time")(_ensure_aware)


class CancelRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class RescheduleRequest(BaseModel):
    new_start_time: datetime = Field(description="ISO 8601. Naive values are treated as clinic-local time.")

    _aware = field_validator("new_start_time")(_ensure_aware)


class AppointmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doctor_id: int
    patient_id: int
    start_time: datetime
    end_time: datetime
    status: str
    cancel_reason: str | None = None
    cancelled_at: datetime | None = None
    created_at: datetime

    @field_serializer("start_time", "end_time", "cancelled_at", "created_at")
    def _local(self, value: datetime | None) -> datetime | None:
        return _to_local(value)


class SlotOut(BaseModel):
    start_time: datetime
    end_time: datetime

    @field_serializer("start_time", "end_time")
    def _local(self, value: datetime) -> datetime:
        return _to_local(value)


class AvailabilityOut(BaseModel):
    doctor_id: int
    date: date
    timezone: str
    slot_minutes: int
    slots: list[SlotOut]


class DoctorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    specialty: str


class PatientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=32)


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    phone: str | None = None

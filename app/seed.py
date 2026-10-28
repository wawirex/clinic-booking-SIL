from datetime import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Doctor, DoctorSchedule

DOCTORS = [
    ("Dr. Amina Wanjiru", "General Practice"),
    ("Dr. Brian Otieno", "Paediatrics"),
    ("Dr. Chebet Kiprop", "Internal Medicine"),
    ("Dr. David Mwangi", "Dermatology"),
    ("Dr. Esther Njeri", "Gynaecology"),
]


def seed(db: Session) -> None:
    """Idempotent: 5 doctors, Mon-Fri 08:00-12:00 and 13:00-17:00 (lunch break)."""
    if db.scalar(select(func.count(Doctor.id))):
        return
    for name, specialty in DOCTORS:
        doctor = Doctor(name=name, specialty=specialty)
        db.add(doctor)
        db.flush()
        for weekday in range(5):
            db.add(DoctorSchedule(doctor_id=doctor.id, weekday=weekday, start_time=time(8), end_time=time(12)))
            db.add(DoctorSchedule(doctor_id=doctor.id, weekday=weekday, start_time=time(13), end_time=time(17)))
    db.commit()

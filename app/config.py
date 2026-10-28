import os
from zoneinfo import ZoneInfo


def _normalize_db_url(url: str) -> str:
    """Render/Heroku hand out postgres:// or postgresql:// URLs; use the psycopg3 driver."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


class Settings:
    def __init__(self) -> None:
        self.database_url = _normalize_db_url(os.getenv("DATABASE_URL", "sqlite:///./clinic.db"))
        self.clinic_timezone = os.getenv("CLINIC_TIMEZONE", "Africa/Nairobi")
        self.slot_minutes = int(os.getenv("SLOT_MINUTES", "30"))
        self.min_lead_minutes = int(os.getenv("MIN_LEAD_MINUTES", "60"))
        self.seed_on_startup = os.getenv("SEED_ON_STARTUP", "true").lower() in ("1", "true", "yes")

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.clinic_timezone)


settings = Settings()

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Single source of 'now'. Tests monkeypatch this to freeze time."""
    return datetime.now(timezone.utc)

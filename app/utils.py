from datetime import datetime, timezone

def utc_now() -> datetime:
    """Returns a timezone-aware current UTC datetime with tzinfo stripped for DB compatibility."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

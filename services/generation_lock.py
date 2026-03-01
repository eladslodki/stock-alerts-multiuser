"""
DB-backed generation lock with TTL.

Replaces the in-process threading.Lock in report_generator.py so that:
- Stale locks from crashed processes do not block future runs.
- Lock state survives gunicorn worker recycling (--max-requests).

Table: fn_generation_locks (defined in fundamentals_models.GenerationLock)

Functions
---------
acquire_lock(key, ttl_seconds=300) -> bool
    Returns True  if the lock was acquired (or stolen from an expired holder).
    Returns False if the lock is held and not yet expired.

release_lock(key)
    Deletes the lock row.  Safe to call even if the row doesn't exist.
"""
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def acquire_lock(key: str, ttl_seconds: int = 300) -> bool:
    """
    Attempt to acquire the generation lock for *key*.

    - If no row exists              → INSERT and return True.
    - If row exists, not expired    → return False  ("LOCK busy").
    - If row exists, expired        → UPDATE (steal) and return True.

    On any DB error, fails open (returns True) so generation is not
    permanently blocked by a broken lock table.
    """
    from fundamentals_db import get_db
    from fundamentals_models import GenerationLock

    logger.info("LOCK acquire attempt: key=%r ttl=%ds", key, ttl_seconds)
    now     = datetime.utcnow()
    expires = now + timedelta(seconds=ttl_seconds)

    try:
        with get_db() as db:
            existing = db.query(GenerationLock).filter_by(key=key).first()

            if existing:
                if existing.expires_at > now:
                    logger.info(
                        "LOCK busy: key=%r acquired_at=%s expires_at=%s (%.0fs remaining)",
                        key,
                        existing.acquired_at.isoformat(),
                        existing.expires_at.isoformat(),
                        (existing.expires_at - now).total_seconds(),
                    )
                    return False
                else:
                    logger.info(
                        "LOCK expired -> stealing: key=%r was_acquired=%s was_expires=%s",
                        key,
                        existing.acquired_at.isoformat(),
                        existing.expires_at.isoformat(),
                    )
                    existing.acquired_at = now
                    existing.expires_at  = expires
            else:
                db.add(GenerationLock(key=key, acquired_at=now, expires_at=expires))

    except Exception as exc:
        # Fail open: if the lock table is missing or DB is down, let generation proceed.
        logger.error(
            "LOCK acquire DB error for key=%r — failing open: %s", key, exc
        )
        return True

    logger.info("LOCK acquired: key=%r expires=%s", key, expires.isoformat())
    return True


def release_lock(key: str) -> None:
    """Delete the lock row for *key*.  Safe to call multiple times."""
    from fundamentals_db import get_db
    from fundamentals_models import GenerationLock

    try:
        with get_db() as db:
            deleted = db.query(GenerationLock).filter_by(key=key).delete()
        if deleted:
            logger.info("LOCK released: key=%r", key)
        else:
            logger.debug("LOCK release: key=%r (row already gone)", key)
    except Exception as exc:
        logger.warning("LOCK release failed for key=%r: %s", key, exc)

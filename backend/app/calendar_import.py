from datetime import date, datetime, time, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.auth_utils import get_current_user
from app.db import conn
from app.busy_store import insert_busy_rows

router = APIRouter()
PST = ZoneInfo("America/Los_Angeles")
MAX_ICS_BYTES = 5 * 1024 * 1024
MAX_EVENTS = 5000


MAX_FILES = 10


def ics_rows(content: bytes, user_id: str, window_start, window_end) -> list:
    """Busy rows from one .ics file. Raises HTTPException if it can't be read."""
    if len(content) > MAX_ICS_BYTES:
        raise HTTPException(status_code=413, detail="That calendar file is too big (5 MB max).")
    try:
        calendar = icalendar.Calendar.from_ical(content)
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read that file as a valid .ics calendar")
    try:
        events = recurring_ical_events.of(calendar).between(window_start, window_end)
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read events from that .ics file")

    return event_rows(events, user_id, "ics")


def event_rows(events, user_id: str, source: str, skip_free: bool = False) -> list:
    """Busy rows from expanded icalendar VEVENTs (an .ics file or Apple Calendar).
    skip_free drops events marked "Free" (TRANSP:TRANSPARENT) and cancelled ones."""
    rows = []
    for event in events[:MAX_EVENTS]:
        if event.get("dtstart") is None:
            continue
        if skip_free and (str(event.get("transp", "")).upper() == "TRANSPARENT"
                          or str(event.get("status", "")).upper() == "CANCELLED"):
            continue
        raw_start = event.get("dtstart").dt
        # All-day events (a bare date, no time) don't block time (Sam, 2026-11-20).
        if isinstance(raw_start, date) and not isinstance(raw_start, datetime):
            continue
        # DTEND is optional in .ics: fall back to DURATION, then to the start
        # (a one-day block for all-day events, a zero-length one otherwise).
        if event.get("dtend") is not None:
            raw_end = event.get("dtend").dt
        elif event.get("duration") is not None:
            raw_end = raw_start + event.get("duration").dt
        elif isinstance(raw_start, date) and not isinstance(raw_start, datetime):
            raw_end = raw_start + timedelta(days=1)
        else:
            continue

        # All-day events come back as bare `date` objects, not `datetime`.
        if isinstance(raw_start, date) and not isinstance(raw_start, datetime):
            start_dt = datetime.combine(raw_start, time.min, tzinfo=PST)
            end_dt = datetime.combine(raw_end, time.min, tzinfo=PST)
        else:
            start_dt = raw_start.astimezone(PST) if raw_start.tzinfo else raw_start.replace(tzinfo=PST)
            end_dt = raw_end.astimezone(PST) if raw_end.tzinfo else raw_end.replace(tzinfo=PST)

        rows.append((user_id, start_dt.isoformat(), end_dt.isoformat(), source, str(PST), None))
    return rows


@router.post("/import/ics")
async def import_ics(
    files: Optional[List[UploadFile]] = File(None),
    file: Optional[UploadFile] = File(None),  # older pages send a single "file"
    user_id: str = Depends(get_current_user),
):
    """Import one or more .ics files (e.g. a class timetable and a work schedule) together.
    They replace the previous .ics import as a set, so importing several at once keeps all
    of them; every file is checked before anything is saved."""
    uploads = [f for f in (files or []) if f is not None] + ([file] if file is not None else [])
    if not uploads:
        raise HTTPException(status_code=400, detail="Choose at least one .ics file.")
    if len(uploads) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Import up to {MAX_FILES} files at a time.")

    # A generous window around today - covers anything worth importing
    # without materializing an unbounded number of recurring instances.
    today = datetime.now(PST).date()
    window_start = today - timedelta(days=7)
    window_end = today + timedelta(days=60)

    rows, seen = [], set()
    for upload in uploads:
        content = await upload.read(MAX_ICS_BYTES + 1)
        for row in ics_rows(content, user_id, window_start, window_end):
            if (row[1], row[2]) not in seen:  # the same event in two files counts once
                seen.add((row[1], row[2]))
                rows.append(row)

    conn.execute(
        "DELETE FROM busy_times WHERE user_id = ? AND source = 'ics'",
        (user_id,)
    )
    insert_busy_rows(rows)
    conn.commit()

    return {"imported": len(rows), "files": len(uploads)}

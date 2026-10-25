from datetime import date, datetime, time, timedelta
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


@router.post("/import/ics")
async def import_ics(file: UploadFile = File(...), user_id: str = Depends(get_current_user)):
    content = await file.read(MAX_ICS_BYTES + 1)
    if len(content) > MAX_ICS_BYTES:
        raise HTTPException(status_code=413, detail="That calendar file is too big (5 MB max).")

    try:
        calendar = icalendar.Calendar.from_ical(content)
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read that file as a valid .ics calendar")

    # A generous window around today - covers anything worth importing
    # without materializing an unbounded number of recurring instances.
    today = datetime.now(PST).date()
    window_start = today - timedelta(days=7)
    window_end = today + timedelta(days=60)

    try:
        events = recurring_ical_events.of(calendar).between(window_start, window_end)
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read events from that .ics file")

    conn.execute(
        "DELETE FROM busy_times WHERE user_id = ? AND source = 'ics'",
        (user_id,)
    )

    imported = 0
    rows = []

    for event in events[:MAX_EVENTS]:
        if event.get("dtstart") is None:
            continue
        raw_start = event.get("dtstart").dt
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

        rows.append((user_id, start_dt.isoformat(), end_dt.isoformat(), "ics", str(PST), None))
        imported += 1

    insert_busy_rows(rows)
    conn.commit()

    return {"imported": imported}

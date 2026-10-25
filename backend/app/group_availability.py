import re
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from datetime import datetime, time, timedelta
from app.availability import merge_intervals, find_free_time, score_slot
from app.auth_utils import get_current_user
from app.db import conn
from app.busy_store import insert_busy_rows

router = APIRouter()
PST = ZoneInfo("America/Los_Angeles")

# Group codes are 8 characters from the frontend's alphabet; older links may
# be UUIDs. Anything else is rejected.
GROUP_ID_RE = re.compile(r"^[A-Za-z0-9-]{6,64}$")
MAX_BLOCKS = 1000


def is_member(group_id: str, user_id: str) -> bool:
    rows = conn.execute("SELECT user_id FROM group_members WHERE group_id = ?", (group_id,)).fetchall()
    return any(r[0].strip().lower() == user_id.strip().lower() for r in rows)

@router.post("/availability/merge")
def merge_users_availability(
    request: Request,
    users_busy: list = Body(...),
    user_id: str = Depends(get_current_user),
    min_minutes: int = Query(30, ge=5, le=12 * 60),
    day_start: str = Query("08:00"),
    day_end: str = Query("22:00"),
    timezone: str = Query(None),
    days: int = Query(1, ge=1, le=62),
    start_offset: int = Query(0, ge=-366, le=366),
    # A plain refresh (changing view, joining a group, after an import)
    # sends keep_manual=1 so it never touches the saved manual blocks -
    # otherwise a device with nothing stored locally (a phone, a new
    # browser) would wipe them just by opening the app.
    keep_manual: bool = Query(False)
    ):

    # The viewer's own current timezone - "today", business hours, and
    # anything they enter manually are all relative to where THEY are right
    # now. Falls back to Pacific if the client doesn't send one.
    try:
        viewer_tz = ZoneInfo(timezone) if timezone else PST
    except Exception:
        viewer_tz = PST

    # ---- Parse day bounds ----
    try:
        day_start_time = time.fromisoformat(day_start)
        day_end_time = time.fromisoformat(day_end)
    except ValueError:
        raise HTTPException(status_code=400, detail="Day start/end must be times like 08:00.")
    if day_end_time <= day_start_time:
        raise HTTPException(status_code=400, detail="Day end must be after day start.")

    # ---- Normalize this request's manually-submitted busy blocks ----
    manual_blocks = []

    if sum(len(u) if isinstance(u, list) else 1 for u in users_busy) > MAX_BLOCKS:
        raise HTTPException(status_code=400, detail="Too many busy blocks in one request.")

    for user in users_busy:

        if isinstance(user, dict):
            user = [[user["start"], user["end"]]]

        for block in user:

            if isinstance(block, dict):
                # Any "title" a client sends is ignored: only the time is kept.
                start, end = block["start"], block["end"]
            else:
                start, end = block

            try:
                start_dt = datetime.fromisoformat(start)
                end_dt = datetime.fromisoformat(end)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Busy times must be ISO date-times.")

            # A naive value (e.g. from the manual-entry form) means "in the
            # viewer's own current timezone" - not a fixed Pacific default.
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=viewer_tz)
            else:
                start_dt = start_dt.astimezone(viewer_tz)

            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=viewer_tz)
            else:
                end_dt = end_dt.astimezone(viewer_tz)

            if end_dt <= start_dt:
                continue  # empty or backwards block: nothing to block out
            manual_blocks.append((start_dt, end_dt, None))

    # Persist them so other group members can see this user's busy times too -
    # previously manual entries only ever lived in this one response. Record
    # the zone they were entered in so viewers can later see them in their
    # original timezone rather than one silently converted.
    if not keep_manual:
        conn.execute(
            "DELETE FROM busy_times WHERE user_id = ? AND source = 'manual'",
            (user_id,)
        )

        insert_busy_rows(
            (user_id, start_dt.isoformat(), end_dt.isoformat(), "manual", str(viewer_tz), title)
            for start_dt, end_dt, title in manual_blocks
        )

        conn.commit()

    # ---- Gather busy times for this user + any group members, all from the DB ----
    today = datetime.now(viewer_tz).date()
    range_start = today + timedelta(days=start_offset)
    date_range = {range_start + timedelta(days=i) for i in range(days)}
    window_start = datetime.combine(range_start, time.min, tzinfo=viewer_tz)
    window_end = datetime.combine(range_start + timedelta(days=days), time.min, tzinfo=viewer_tz)
    member_ids = [user_id]
    seen_member_keys = {user_id.strip().lower()}

    group_id = request.query_params.get("group")

    # Only members see a group's calendars. A non-member (wrong code, or the
    # join hasn't gone through yet) just gets their own schedule.
    if group_id and GROUP_ID_RE.match(group_id) and is_member(group_id, user_id):
        for row in conn.execute(
            "SELECT user_id FROM group_members WHERE group_id = ?",
            (group_id,)
        ).fetchall():
            member_key = row[0].strip().lower()
            if member_key not in seen_member_keys:
                seen_member_keys.add(member_key)
                member_ids.append(row[0])

    # Each member's chosen name (or their email before the @) - what other
    # members see on their blocks.
    names = {}
    for uid in member_ids:
        row = conn.execute("SELECT display_name FROM users WHERE id = ?", (uid,)).fetchone()
        names[uid] = (row[0] if row else None) or uid.split("@")[0]

    all_busy = []
    busy_output = []
    seen_intervals = set()

    for uid in member_ids:
        rows = conn.execute(
            "SELECT start, end_time, source, raw_timezone FROM busy_times WHERE user_id = ?",
            (uid,)
        ).fetchall()

        for start, end, source, raw_timezone in rows:
            start_dt = datetime.fromisoformat(start).astimezone(viewer_tz)
            end_dt = datetime.fromisoformat(end).astimezone(viewer_tz)

            # Only consider busy time that overlaps the requested range -
            # including events that started before it (overnight, multi-day).
            if not (start_dt < window_end and end_dt > window_start):
                continue

            # Duplicate rows can pile up from things like a stale duplicate
            # group membership or a re-import - never show the same busy
            # interval twice.
            key = (start_dt.isoformat(), end_dt.isoformat())
            if key in seen_intervals:
                continue
            seen_intervals.add(key)

            all_busy.append((start_dt, end_dt))

            busy_output.append({
                "date": max(start_dt, window_start).date().isoformat(),
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "label": {
                    "google": "(imported)",
                    "ics": "(ics)",
                }.get(source, "(manual)"),
                # Never sent, even for rows saved before titles stopped
                # being stored: a block only says whose it is.
                "title": None,
                "owner": uid,
                "owner_name": names[uid],
                "source_timezone": raw_timezone
            })

    # ---- Merge busy intervals ----
    merged_busy = merge_intervals(all_busy)

    # ---- Compute free time for each requested day ----
    results = []

    for target_date in sorted(date_range):
        day_lo = datetime.combine(target_date, time.min, tzinfo=viewer_tz)
        day_hi = day_lo + timedelta(days=1)
        day_busy_count = sum(1 for s, e in merged_busy if s < day_hi and e > day_lo)

        free_slots = find_free_time(
            merged_busy,
            target_date=target_date,
            day_start=day_start_time,
            day_end=day_end_time,
            min_minutes=min_minutes,
            tz=viewer_tz
        )

        for start, end in free_slots:
            results.append({
                "date": target_date.isoformat(),
                "start": start.isoformat(),
                "end": end.isoformat(),
                "duration_minutes": int((end - start).total_seconds() / 60),
                "score": score_slot(start, end, day_start_time, day_end_time, day_busy_count)
            })

    results.sort(key=lambda x: x["score"], reverse=True)

    return {
        "busy_times": busy_output,
        "ranked_free_time": results
    }

@router.get("/availability/manual")
def my_manual_blocks(user_id: str = Depends(get_current_user)):
    """All of your saved manual busy blocks, so a new device can show (and
    keep) them instead of starting from an empty list."""
    rows = conn.execute(
        "SELECT start, end_time FROM busy_times WHERE user_id = ? AND source = 'manual' ORDER BY start",
        (user_id,)
    ).fetchall()
    return {"blocks": [{"start": s, "end": e} for s, e in rows]}


def clean_group_name(name) -> str | None:
    return " ".join(str(name or "").split())[:60] or None


@router.post("/groups/join")
def join_group(
    group_id: str = Query(...),
    name: str = Query(None),
    user_id: str = Depends(get_current_user),
):
    """Joins (or, for a new id, creates) a group. `name` only applies when
    the group is new - joining someone's link never renames their group."""
    if not GROUP_ID_RE.match(group_id):
        raise HTTPException(status_code=400, detail="That group link isn't valid.")
    conn.execute(
        "INSERT INTO groups (id, name) VALUES (?, ?) ON CONFLICT (id) DO NOTHING",
        (group_id, clean_group_name(name))
    )

    existing_members = conn.execute(
        "SELECT user_id FROM group_members WHERE group_id = ?",
        (group_id,)
    ).fetchall()

    already_member = any(
        row[0].strip().lower() == user_id.strip().lower()
        for row in existing_members
    )

    if not already_member:
        conn.execute(
            "INSERT INTO group_members (group_id, user_id) VALUES (?, ?)",
            (group_id, user_id)
        )

    conn.commit()
    return {"joined": True}


@router.get("/groups")
def my_groups(user_id: str = Depends(get_current_user)):
    """Every group link you're in, with its name and who's in it."""
    me = user_id.strip().lower()
    rows = conn.execute(
        "SELECT DISTINCT group_id FROM group_members WHERE LOWER(TRIM(user_id)) = ?", (me,)
    ).fetchall()
    group_ids = [r[0] for r in rows]

    out = []
    for gid in group_ids:
        name_row = conn.execute("SELECT name FROM groups WHERE id = ?", (gid,)).fetchone()
        members = []
        seen = set()
        for (uid,) in conn.execute("SELECT user_id FROM group_members WHERE group_id = ?", (gid,)).fetchall():
            key = uid.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            row = conn.execute("SELECT display_name FROM users WHERE id = ?", (uid,)).fetchone()
            members.append("You" if key == me else (row[0] if row and row[0] else uid.split("@")[0]))
        out.append({"id": gid, "name": name_row[0] if name_row else None, "members": members})
    return {"groups": out}


@router.post("/groups/rename")
def rename_group(group_id: str = Query(...), name: str = Query(""), user_id: str = Depends(get_current_user)):
    """Any member can name a group; blank clears the name."""
    if not GROUP_ID_RE.match(group_id) or not is_member(group_id, user_id):
        raise HTTPException(status_code=404, detail="You're not in that group.")
    clean = clean_group_name(name)
    conn.execute("UPDATE groups SET name = ? WHERE id = ?", (clean, group_id))
    conn.commit()
    return {"id": group_id, "name": clean}


@router.post("/groups/leave")
def leave_group(group_id: str = Query(...), user_id: str = Depends(get_current_user)):
    """Leaves a group: you stop seeing its calendars and its members stop
    seeing yours. The link keeps working for everyone else."""
    if not GROUP_ID_RE.match(group_id):
        raise HTTPException(status_code=400, detail="That group link isn't valid.")
    conn.execute(
        "DELETE FROM group_members WHERE group_id = ? AND LOWER(TRIM(user_id)) = ?",
        (group_id, user_id.strip().lower())
    )
    conn.commit()
    return {"left": True}

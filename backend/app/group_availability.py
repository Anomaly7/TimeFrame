import json
import re
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from datetime import datetime, time, timedelta
from app.availability import merge_intervals, find_free_time, score_slot, parse_prefer, is_all_day_block
from app.auth_utils import RateLimiter, clean_text, client_ip, get_current_user
from app.db import conn
from app.busy_store import insert_busy_rows

router = APIRouter()
PST = ZoneInfo("America/Los_Angeles")

# Group codes are 8 characters from the frontend's alphabet; older links may
# be UUIDs. Anything else is rejected.
GROUP_ID_RE = re.compile(r"^[A-Za-z0-9-]{6,64}$")
MAX_BLOCKS = 1000
# Joining with a made-up code is how someone would hunt for other people's groups: 30 tries per 10 minutes per
# account and per address is plenty for real use (codes are 8 random characters, ~10^12 possibilities).
join_limiter = RateLimiter(max_attempts=30, window_seconds=600)


def same_user(a, b) -> bool:
    return bool(a and b) and a.strip().lower() == b.strip().lower()


def group_row(group_id: str):
    """(name, owner, settings dict or None) for a group, or None."""
    row = conn.execute("SELECT name, owner, settings FROM groups WHERE id = ?", (group_id,)).fetchone()
    if not row:
        return None
    try:
        settings = json.loads(row[2]) if row[2] else None
    except ValueError:
        settings = None
    return row[0], row[1], settings


def require_admin(group_id: str, user_id: str):
    if not GROUP_ID_RE.match(group_id) or not is_member(group_id, user_id):
        raise HTTPException(status_code=404, detail="You're not in that group.")
    info = group_row(group_id)
    if not info or not same_user(info[1], user_id):
        raise HTTPException(status_code=403, detail="Only the group's admin can do that.")
    return info


def clean_settings(body: dict) -> dict:
    """Validates the scheduling settings an admin sets for a group."""
    try:
        day_start = time.fromisoformat(str(body.get("dayStart", "08:00")))
        day_end = time.fromisoformat(str(body.get("dayEnd", "22:00")))
    except ValueError:
        raise HTTPException(status_code=400, detail="Day start/end must be times like 08:00.")
    if day_end <= day_start:
        raise HTTPException(status_code=400, detail="Day end must be after day start.")
    try:
        length = int(body.get("meetingLength", 30))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Meeting length must be a number of minutes.")
    if not 5 <= length <= 12 * 60:
        raise HTTPException(status_code=400, detail="Meeting length must be 5 minutes to 12 hours.")
    prefs = parse_prefer(",".join(body.get("timePrefs") or [])) or []
    for name in ("afternoon", "morning", "evening"):
        if name not in prefs:
            prefs.append(name)
    return {
        "dayStart": day_start.strftime("%H:%M"),
        "dayEnd": day_end.strftime("%H:%M"),
        "meetingLength": length,
        "excludeWeekends": bool(body.get("excludeWeekends")),
        "timePrefs": prefs,
        "bufferMinutes": clean_buffer(body.get("bufferMinutes", 0)),
    }


def clean_buffer(value) -> int:
    """Travel time kept free before and after every busy block (0-60 minutes)."""
    try:
        minutes = int(value or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Travel buffer must be a number of minutes.")
    if not 0 <= minutes <= 60:
        raise HTTPException(status_code=400, detail="Travel buffer must be 0 to 60 minutes.")
    return minutes


def owned_group_count(user_id: str) -> int:
    """Groups this person is admin of and still in (leaving one frees the slot)."""
    me = user_id.strip().lower()
    return conn.execute(
        "SELECT COUNT(DISTINCT g.id) FROM groups g JOIN group_members m ON m.group_id = g.id "
        "WHERE LOWER(TRIM(g.owner)) = ? AND LOWER(TRIM(m.user_id)) = ?", (me, me)
    ).fetchone()[0]


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
    keep_manual: bool = Query(False),
    # Ranked times of day for the best slot, e.g. "afternoon,morning,evening".
    prefer: str = Query(None),
    # Minutes kept free before/after every busy block (travel time); Pro, or the group's setting.
    buffer: int = Query(0, ge=0, le=60),
    ):
    prefer_order = parse_prefer(prefer)

    # Viewing a group: its admin's settings apply to everyone in it, whatever
    # this browser has saved locally.
    group_id = request.query_params.get("group")
    in_group = bool(group_id and GROUP_ID_RE.match(group_id) and is_member(group_id, user_id))
    group_settings = (group_row(group_id) or (None, None, None))[2] if in_group else None
    exclude_weekends = False
    if group_settings:
        min_minutes = group_settings["meetingLength"]
        day_start = group_settings["dayStart"]
        day_end = group_settings["dayEnd"]
        prefer_order = group_settings["timePrefs"]
        exclude_weekends = group_settings["excludeWeekends"]
        buffer = group_settings.get("bufferMinutes", 0)
    else:
        # Custom settings are a Pro feature: a free account always gets the defaults,
        # whatever its browser sends.
        from app.billing import is_pro
        if not is_pro(user_id):
            min_minutes, day_start, day_end = 30, "08:00", "22:00"
            prefer_order = ["afternoon", "morning", "evening"]
            buffer = 0
    pad = timedelta(minutes=buffer)

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

        try:
            if isinstance(user, dict):
                user = [[user["start"], user["end"]]]
            if not isinstance(user, list):
                raise TypeError
        except (KeyError, TypeError):
            raise HTTPException(status_code=400, detail="Busy times must be ISO date-times.")

        for block in user:

            try:
                if isinstance(block, dict):
                    # Any "title" a client sends is ignored: only the time is kept.
                    start, end = block["start"], block["end"]
                else:
                    start, end = block
                start_dt = datetime.fromisoformat(start)
                end_dt = datetime.fromisoformat(end)
            except (KeyError, TypeError, ValueError):
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

    # Only members see a group's calendars. A non-member (wrong code, or the
    # join hasn't gone through yet) just gets their own schedule.
    if in_group:
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
    busy_by_member = {uid: [] for uid in member_ids}  # for "everyone but one" suggestions

    for uid in member_ids:
        rows = conn.execute(
            "SELECT start, end_time, source, raw_timezone FROM busy_times WHERE user_id = ?",
            (uid,)
        ).fetchall()

        for start, end, source, raw_timezone in rows:
            # All-day calendar events (birthdays, "Exam week", holidays...) don't block time (Sam, 2026-11-20).
            # Imports skip them now; this also hides ones saved before that. Hand-made blocks are always kept.
            if source != "manual" and is_all_day_block(start, end):
                continue
            start_dt = datetime.fromisoformat(start).astimezone(viewer_tz)
            end_dt = datetime.fromisoformat(end).astimezone(viewer_tz)

            # Only consider busy time that overlaps the requested range -
            # including events that started before it (overnight, multi-day).
            if not (start_dt < window_end and end_dt > window_start):
                continue

            # Duplicate rows can pile up from things like a stale duplicate
            # group membership or a re-import - never show the same busy
            # interval twice.
            # Per person: two members with the same class at the same time must both show as busy.
            key = (uid.strip().lower(), start_dt.isoformat(), end_dt.isoformat())
            if key in seen_intervals:
                continue
            seen_intervals.add(key)

            all_busy.append((start_dt - pad, end_dt + pad))
            busy_by_member[uid].append((start_dt - pad, end_dt + pad))

            busy_output.append({
                "date": max(start_dt, window_start).date().isoformat(),
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "label": {
                    "google": "(imported)",
                    "ics": "(ics)",
                    "apple": "(apple)",
                    "notion": "(notion)",
                }.get(source, "(manual)"),
                # Never sent, even for rows saved before titles stopped
                # being stored: a block only says whose it is.
                "title": None,
                "owner": uid,
                "owner_name": names[uid],
                "source_timezone": raw_timezone
            })

    # ---- Booked meetings (bookings.py) ----
    # Ones the viewer is part of show as "Booked" with their name; anyone else's (another group of a member's, a
    # member's booking page) is just a busy block for that person. All of them count as busy.
    from app.bookings import bookings_for_user, public as public_booking
    visible_bookings, seen_bookings = [], set()
    for uid in member_ids:
        mine = uid == user_id
        for b in bookings_for_user(uid):
            b_start = datetime.fromisoformat(b["start"]).astimezone(viewer_tz)
            b_end = datetime.fromisoformat(b["end"]).astimezone(viewer_tz)
            if not (b_start < window_end and b_end > window_start):
                continue
            all_busy.append((b_start - pad, b_end + pad))
            busy_by_member[uid].append((b_start - pad, b_end + pad))
            viewer_sees = mine or (b["group_id"] and b["group_id"] == group_id and in_group)
            if viewer_sees:
                if b["id"] not in seen_bookings:
                    seen_bookings.add(b["id"])
                    visible_bookings.append({**public_booking(b, user_id), "start": b_start.isoformat(),
                                             "end": b_end.isoformat(), "date": max(b_start, window_start).date().isoformat()})
                continue
            key = (uid.strip().lower(), b_start.isoformat(), b_end.isoformat())
            if key in seen_intervals:
                continue
            seen_intervals.add(key)
            busy_output.append({
                "date": max(b_start, window_start).date().isoformat(), "start": b_start.isoformat(),
                "end": b_end.isoformat(), "label": "(booked)", "title": None, "owner": uid,
                "owner_name": names[uid], "source_timezone": None})

    # ---- Merge busy intervals ----
    merged_busy = merge_intervals(all_busy)

    # ---- Compute free time for each requested day ----
    results = []

    for target_date in sorted(date_range):
        if exclude_weekends and target_date.weekday() >= 5:
            continue
        day_lo = datetime.combine(target_date, time.min, tzinfo=viewer_tz)
        day_hi = day_lo + timedelta(days=1)
        day_busy_count = sum(1 for s, e in merged_busy if s < day_hi and e > day_lo)

        free_slots = find_free_time(
            merged_busy,
            target_date=target_date,
            day_start=day_start_time,
            day_end=day_end_time,
            min_minutes=min_minutes,
            tz=viewer_tz,
            prefer=prefer_order
        )

        for start, end in free_slots:
            results.append({
                "date": target_date.isoformat(),
                "start": start.isoformat(),
                "end": end.isoformat(),
                "duration_minutes": int((end - start).total_seconds() / 60),
                "score": score_slot(start, end, day_start_time, day_end_time, day_busy_count, prefer_order)
            })

    results.sort(key=lambda x: x["score"], reverse=True)

    # ---- Almost works: free for everyone but one person ----
    # Only when the whole group barely fits (fewer than 3 times), and only for groups of 3+.
    almost = []
    if len(member_ids) >= 3 and len(results) < 3:
        full = {(r["start"], r["end"]) for r in results}
        for missing in member_ids:
            others = merge_intervals([iv for uid in member_ids if uid != missing for iv in busy_by_member[uid]])
            theirs = busy_by_member[missing]
            for target_date in sorted(date_range):
                if exclude_weekends and target_date.weekday() >= 5:
                    continue
                for start, end in find_free_time(others, target_date=target_date, day_start=day_start_time,
                                                 day_end=day_end_time, min_minutes=min_minutes, tz=viewer_tz,
                                                 prefer=prefer_order):
                    if (start.isoformat(), end.isoformat()) in full or not any(s < end and e > start for s, e in theirs):
                        continue
                    almost.append({
                        "date": target_date.isoformat(), "start": start.isoformat(), "end": end.isoformat(),
                        "duration_minutes": int((end - start).total_seconds() / 60),
                        "missing": "You" if missing == user_id else names[missing], "missing_id": missing,
                        "score": score_slot(start, end, day_start_time, day_end_time, 0, prefer_order),
                    })
        almost.sort(key=lambda x: x["score"], reverse=True)
        almost = almost[:5]

    return {
        "almost_free": almost,
        "busy_times": busy_output,
        "ranked_free_time": results,
        "bookings": visible_bookings,
        # The settings actually used, when a group's admin has set them.
        "group_settings": group_settings,
        # False when a group was asked for but you're not in it (removed, or it was deleted),
        # so the app can switch back to your own calendar.
        "in_group": in_group if group_id else None,
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
    return clean_text(name, 60) or None


@router.post("/groups/join")
def join_group(
    request: Request,
    group_id: str = Query(...),
    name: str = Query(None),
    user_id: str = Depends(get_current_user),
):
    """Joins (or, for a new id, creates) a group. `name` only applies when
    the group is new - joining someone's link never renames their group."""
    join_limiter.check("user:" + user_id.strip().lower(), "ip:" + client_ip(request))
    if not GROUP_ID_RE.match(group_id):
        raise HTTPException(status_code=400, detail="That group link isn't valid.")
    banned = conn.execute(
        "SELECT 1 FROM group_bans WHERE group_id = ? AND LOWER(TRIM(user_id)) = ?",
        (group_id, user_id.strip().lower())
    ).fetchone()
    if banned:
        raise HTTPException(status_code=403, detail="The group's admin removed you from this group.")
    if conn.execute("SELECT 1 FROM deleted_groups WHERE id = ?", (group_id,)).fetchone():
        raise HTTPException(status_code=410, detail="This group was deleted by its admin.")
    # Free accounts can create one group (counting the ones they own and are still in); Pro is
    # unlimited. Joining someone else's group is always free.
    exists = conn.execute("SELECT 1 FROM groups WHERE id = ?", (group_id,)).fetchone()
    from app.guests import guests_allowed, is_guest
    if is_guest(user_id) and (not exists or not guests_allowed(group_id)):
        raise HTTPException(status_code=403, detail="Guests can only join groups that allow guests. Make a free account to do more.")
    if not exists:
        from app.billing import FREE_GROUP_LIMIT, is_pro
        if owned_group_count(user_id) >= FREE_GROUP_LIMIT and not is_pro(user_id):
            raise HTTPException(status_code=402, detail=(
                f"Free accounts can create {FREE_GROUP_LIMIT} group. More groups are part of TimeFrame Pro."))
    # Whoever creates the link is its admin.
    conn.execute(
        "INSERT INTO groups (id, name, owner) VALUES (?, ?, ?) ON CONFLICT (id) DO NOTHING",
        (group_id, clean_group_name(name), user_id)
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
    if not already_member and existing_members:
        from app.bookings import display_name
        from app.notifications import notify_group
        notify_group(group_id, "joined", f"{display_name(user_id)} joined the group", exclude=user_id)
    return {"joined": True}


@router.get("/groups")
def my_groups(user_id: str = Depends(get_current_user)):
    """Every group link you're in, with its name and who's in it."""
    me = user_id.strip().lower()
    rows = conn.execute(
        "SELECT DISTINCT group_id FROM group_members WHERE LOWER(TRIM(user_id)) = ?", (me,)
    ).fetchall()
    group_ids = [r[0] for r in rows]

    from app.guests import guests_allowed, is_guest
    out = []
    for gid in group_ids:
        name, owner, settings = group_row(gid) or (None, None, None)
        members = []
        seen = set()
        for (uid,) in conn.execute("SELECT user_id FROM group_members WHERE group_id = ?", (gid,)).fetchall():
            key = uid.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            row = conn.execute("SELECT display_name FROM users WHERE id = ?", (uid,)).fetchone()
            members.append({
                "id": uid,
                "name": "You" if key == me else (row[0] if row and row[0] else uid.split("@")[0]),
                "you": key == me,
                "admin": same_user(owner, uid),
                "guest": is_guest(uid),
            })
        out.append({
            "id": gid,
            "name": name,
            "members": members,
            "is_admin": same_user(owner, user_id),
            # Links made before admins existed: any member can claim them.
            "claimable": owner is None,
            "settings": settings,
            "guests_allowed": guests_allowed(gid),
        })
    return {"groups": out}


@router.post("/groups/claim")
def claim_group(group_id: str = Query(...), user_id: str = Depends(get_current_user)):
    """Become admin of an older link that has none yet (first come)."""
    if not GROUP_ID_RE.match(group_id) or not is_member(group_id, user_id):
        raise HTTPException(status_code=404, detail="You're not in that group.")
    conn.execute("UPDATE groups SET owner = ? WHERE id = ? AND owner IS NULL", (user_id, group_id))
    conn.commit()
    if not same_user((group_row(group_id) or (None, None, None))[1], user_id):
        raise HTTPException(status_code=409, detail="This group already has an admin.")
    return {"is_admin": True}


@router.post("/groups/settings")
def set_group_settings(group_id: str = Query(...), body: dict = Body(...), user_id: str = Depends(get_current_user)):
    """Admin only: the best-time ranking, weekends, meeting length and day
    hours everyone viewing this group uses."""
    require_admin(group_id, user_id)
    from app.billing import require_pro
    require_pro(user_id, "Changing settings")
    settings = clean_settings(body)
    conn.execute("UPDATE groups SET settings = ? WHERE id = ?", (json.dumps(settings), group_id))
    conn.commit()
    return {"settings": settings}


@router.post("/groups/kick")
def kick_member(group_id: str = Query(...), member: str = Query(...), user_id: str = Depends(get_current_user)):
    """Admin only: removes someone from the group. They can't rejoin with the
    link, and they stop seeing (and sharing) its calendars."""
    require_admin(group_id, user_id)
    if same_user(member, user_id):
        raise HTTPException(status_code=400, detail="You can't remove yourself. Use Leave instead.")
    if not is_member(group_id, member):
        raise HTTPException(status_code=404, detail="That person isn't in this group.")
    conn.execute(
        "DELETE FROM group_members WHERE group_id = ? AND LOWER(TRIM(user_id)) = ?",
        (group_id, member.strip().lower())
    )
    conn.execute("INSERT INTO group_bans (group_id, user_id) VALUES (?, ?)", (group_id, member.strip().lower()))
    conn.commit()
    return {"removed": True}


@router.post("/groups/delete")
def delete_group(group_id: str = Query(...), user_id: str = Depends(get_current_user)):
    """Admin only: removes everyone (including the admin) and deletes the group.
    The link stops working for good."""
    require_admin(group_id, user_id)
    conn.execute("DELETE FROM group_members WHERE group_id = ?", (group_id,))
    conn.execute("DELETE FROM group_bans WHERE group_id = ?", (group_id,))
    conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))
    conn.execute("UPDATE bookings SET cancelled = 1 WHERE group_id = ?", (group_id,))
    conn.execute("UPDATE polls SET closed = 1 WHERE group_id = ?", (group_id,))
    conn.execute("DELETE FROM group_notes WHERE group_id = ?", (group_id,))
    conn.execute("DELETE FROM group_prefs WHERE group_id = ?", (group_id,))
    conn.execute(
        "INSERT INTO deleted_groups (id, at_ms) VALUES (?, ?) ON CONFLICT (id) DO NOTHING",
        (group_id, int(datetime.now().timestamp() * 1000))
    )
    conn.commit()
    return {"deleted": True}


@router.post("/groups/rename")
def rename_group(group_id: str = Query(...), name: str = Query(""), user_id: str = Depends(get_current_user)):
    """Admin only; blank clears the name."""
    require_admin(group_id, user_id)
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
    # The admin leaving used to leave the group with an admin who wasn't in it: nobody could rename it,
    # remove people or change its settings ever again. Now any remaining member can claim it.
    info = group_row(group_id)
    if info and same_user(info[1], user_id):
        conn.execute("UPDATE groups SET owner = NULL WHERE id = ?", (group_id,))
    conn.commit()
    return {"left": True}


@router.get("/availability/recurring")
def recurring_slots(
    user_id: str = Depends(get_current_user),
    group: str = Query(None),
    weeks: int = Query(10, ge=2, le=16),
    timezone: str = Query(None),
    length: int = Query(None, ge=5, le=12 * 60),
    day_start: str = Query(None),
    day_end: str = Query(None),
    exclude_weekends: bool = Query(False),
    buffer: int = Query(0, ge=0, le=60),
    prefer: str = Query(None),
):
    """Best weekly time: the weekday + start time that's free for everyone in the most of the next `weeks` weeks
    ("Tuesdays 3:00 PM: free 9 of 10 weeks"). Uses the group's settings, or yours (Pro) / the defaults."""
    import bisect
    from app.billing import is_pro
    from app.bookings import bookings_for_user
    try:
        tz = ZoneInfo(timezone) if timezone else PST
    except Exception:
        tz = PST
    in_group = bool(group and GROUP_ID_RE.match(group) and is_member(group, user_id))
    settings = (group_row(group) or (None, None, None))[2] if in_group else None
    if settings:
        day_start, day_end = time.fromisoformat(settings["dayStart"]), time.fromisoformat(settings["dayEnd"])
        minutes, weekends_off, prefs = settings["meetingLength"], settings["excludeWeekends"], settings["timePrefs"]
        buffer = settings.get("bufferMinutes", 0)
    elif is_pro(user_id):
        # Your own settings (Pro), sent by the app.
        try:
            day_start = time.fromisoformat(day_start or "08:00")
            day_end = time.fromisoformat(day_end or "22:00")
        except ValueError:
            raise HTTPException(status_code=400, detail="Day start/end must be times like 08:00.")
        if day_end <= day_start:
            raise HTTPException(status_code=400, detail="Day end must be after day start.")
        minutes, weekends_off = length or 30, exclude_weekends
        prefs = parse_prefer(prefer) or ["afternoon", "morning", "evening"]
    else:
        day_start, day_end, minutes, weekends_off, prefs, buffer = time(8), time(22), 30, False, ["afternoon", "morning", "evening"], 0
    pad = timedelta(minutes=buffer)

    members = [user_id]
    if in_group:
        seen = {user_id.strip().lower()}
        for (uid,) in conn.execute("SELECT user_id FROM group_members WHERE group_id = ?", (group,)).fetchall():
            if uid.strip().lower() not in seen:
                seen.add(uid.strip().lower())
                members.append(uid)

    today = datetime.now(tz).date()
    window_start = datetime.combine(today, time.min, tzinfo=tz)
    window_end = window_start + timedelta(days=7 * weeks + 1)
    busy = []
    for uid in members:
        for start, end, source in conn.execute(
                "SELECT start, end_time, source FROM busy_times WHERE user_id = ?", (uid,)).fetchall():
            if source != "manual" and is_all_day_block(start, end):
                continue
            s, e = datetime.fromisoformat(start), datetime.fromisoformat(end)
            if s < window_end and e > window_start:
                busy.append((s - pad, e + pad))
        for b in bookings_for_user(uid):
            s, e = datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"])
            if s < window_end and e > window_start:
                busy.append((s - pad, e + pad))
    merged = merge_intervals(busy)
    starts = [s for s, _ in merged]

    def is_free(s, e):
        # merged is sorted and non-overlapping, so of the blocks starting before e only the last can reach past s.
        i = bisect.bisect_left(starts, e)
        return i == 0 or merged[i - 1][1] <= s

    length_td = timedelta(minutes=minutes)
    candidates = []
    first_day = today + timedelta(days=1)  # from tomorrow, so every week counts fully
    for offset in range(7):
        day = first_day + timedelta(days=offset)
        if weekends_off and day.weekday() >= 5:
            continue
        t = datetime.combine(day, day_start, tzinfo=tz)
        last = datetime.combine(day, day_end, tzinfo=tz) - length_td
        while t <= last:
            free_weeks = 0
            for w in range(weeks):
                s = datetime.combine(day + timedelta(weeks=w), t.time(), tzinfo=tz)
                if is_free(s, s + length_td):
                    free_weeks += 1
            if free_weeks:
                candidates.append({
                    "weekday": day.strftime("%A"), "time": t.strftime("%H:%M"),
                    "start": t.isoformat(), "end": (t + length_td).isoformat(),
                    "free_weeks": free_weeks, "weeks": weeks,
                    "score": score_slot(t, t + length_td, day_start, day_end, 0, prefs),
                })
            t += timedelta(minutes=30)
    candidates.sort(key=lambda c: (c["free_weeks"], c["score"]), reverse=True)
    picked, per_day = [], {}
    for c in candidates:
        if per_day.get(c["weekday"], 0) >= 2:
            continue  # spread the suggestions over different days
        per_day[c["weekday"]] = per_day.get(c["weekday"], 0) + 1
        picked.append(c)
        if len(picked) == 5:
            break
    return {"slots": picked, "weeks": weeks, "minutes": minutes, "people": len(members)}

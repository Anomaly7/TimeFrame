from datetime import datetime, time, timedelta
from typing import List, Tuple
from zoneinfo import ZoneInfo

PST = ZoneInfo("America/Los_Angeles")

def parse_event(event):
    start = event["start"]
    end = event["end"]

    # Google includes the calendar's original named timezone alongside the
    # UTC-offset dateTime - surfaced to the frontend for debugging so a
    # mismatch between the event's zone and what we assume (PST) is visible
    # on the page instead of only in server logs.
    raw_timezone = start.get("timeZone")

    # Untitled events have no "summary" field at all.
    title = event.get("summary") or ""

    if "dateTime" in start:
        start_dt = datetime.fromisoformat(start["dateTime"]).astimezone(PST)
        end_dt = datetime.fromisoformat(end["dateTime"]).astimezone(PST)
    else:
        # all-day events block the whole day
        start_dt = datetime.fromisoformat(start["date"]).replace(tzinfo=PST)
        end_dt = datetime.fromisoformat(end["date"]).replace(tzinfo=PST)

    return start_dt, end_dt, raw_timezone, title


# Times of day people can rank for "best meeting time", as minutes after
# midnight: morning is before noon, afternoon noon-5 PM, evening after 5 PM.
PERIODS = {
    "morning": (0, 12 * 60),
    "afternoon": (12 * 60, 17 * 60),
    "evening": (17 * 60, 24 * 60),
}
# Score bonus by rank: 1st choice, 2nd, 3rd.
PERIOD_BONUS = (150, 75, 0)


def parse_prefer(value):
    """"afternoon,morning,evening" -> ["afternoon", "morning", "evening"];
    unknown or repeated names are dropped. None/empty = no ranking."""
    out = []
    for name in (value or "").lower().split(","):
        name = name.strip()
        if name in PERIODS and name not in out:
            out.append(name)
    return out or None


def period_of(minute_of_day: float) -> str:
    for name, (lo, hi) in PERIODS.items():
        if lo <= minute_of_day < hi:
            return name
    return "evening"


def merge_intervals(intervals):
    if not intervals:
        return []

    intervals.sort(key=lambda x: x[0])
    merged = [intervals[0]]

    for start, end in intervals[1:]:
        last_start, last_end = merged[-1]

        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))

    return merged


def find_free_time(
    busy_intervals,
    target_date,
    day_start,
    day_end,
    min_minutes=30,
    tz=PST,
    prefer=None
):
    free = []
    min_duration = timedelta(minutes=min_minutes)

    now_tz = datetime.now(tz)

    start_dt = datetime.combine(target_date, day_start, tzinfo=tz)
    end_dt = datetime.combine(target_date, day_end, tzinfo=tz)

    # If today, don’t look at past time
    if target_date == now_tz.date():
        start_dt = max(start_dt, now_tz)

    # Busy blocks that overlap this day's window, clipped to it - an event
    # that started yesterday (overnight, or a multi-day all-day event)
    # still blocks today.
    day_busy = [
        (max(s, start_dt), min(e, end_dt)) for s, e in busy_intervals
        if s < end_dt and e > start_dt
    ]

    merged = merge_intervals(day_busy)

    # Rather than returning the whole open gap (which could be hours long),
    # carve out a single min_minutes-long candidate meeting time from each
    # gap, positioned as close to the day's midpoint as that gap allows -
    # this is what actually gets proposed/ranked, not just "you're free
    # from 1pm to 4pm."
    day_mid = start_dt + (end_dt - start_dt) / 2
    ideal_start = day_mid - min_duration / 2

    midnight = datetime.combine(target_date, time.min, tzinfo=tz)

    def best_window(gap_start, gap_end):
        if gap_end - gap_start < min_duration:
            return None
        # With a ranking, put the meeting in the highest-ranked part of the
        # day this gap reaches (centered in it); otherwise near midday.
        for name in prefer or []:
            lo_min, hi_min = PERIODS[name]
            lo = max(gap_start, midnight + timedelta(minutes=lo_min))
            hi = min(gap_end, midnight + timedelta(minutes=hi_min))
            if hi - lo >= min_duration:
                start = lo + ((hi - lo) - min_duration) / 2
                return (start, start + min_duration)
        latest_start = gap_end - min_duration
        window_start = min(max(ideal_start, gap_start), latest_start)
        return (window_start, window_start + min_duration)

    current = start_dt

    for start, end in merged:
        if start > current:
            window = best_window(current, start)
            if window:
                free.append(window)
        current = max(current, end)

    if current < end_dt:
        window = best_window(current, end_dt)
        if window:
            free.append(window)

    return free

def score_slot(start: datetime, end: datetime, day_start: time, day_end: time, day_busy_count: int = 0, prefer=None) -> int:
    duration_minutes = int((end - start).total_seconds() / 60)

    if prefer:
        # Ranked times of day decide: 1st choice beats 2nd beats 3rd (and
        # any unranked period), then a small nudge toward the middle of that
        # period, then the quieter day.
        slot_mid = ((start.hour * 60 + start.minute) + (end.hour * 60 + end.minute)) / 2
        name = period_of(slot_mid)
        rank = prefer.index(name) if name in prefer else len(PERIOD_BONUS)
        bonus = PERIOD_BONUS[rank] if rank < len(PERIOD_BONUS) else -75
        lo = max(PERIODS[name][0], day_start.hour * 60 + day_start.minute)
        hi = min(PERIODS[name][1], day_end.hour * 60 + day_end.minute)
        half = max(hi - lo, 1) / 2
        nudge = max(0.0, 30 * (1 - abs(slot_mid - (lo + hi) / 2) / half))
        return round(duration_minutes + bonus + nudge - day_busy_count * 15)

    # A slot centered near the middle of the day's bounds scores highest,
    # falling off linearly toward either edge - replaces the old fixed
    # "10am-6pm is good" hour buckets with something that adapts to
    # whatever day_start/day_end the viewer has configured.
    day_start_minutes = day_start.hour * 60 + day_start.minute
    day_end_minutes = day_end.hour * 60 + day_end.minute
    day_mid_minutes = (day_start_minutes + day_end_minutes) / 2

    slot_mid_minutes = ((start.hour * 60 + start.minute) + (end.hour * 60 + end.minute)) / 2

    half_day_span = max(day_end_minutes - day_start_minutes, 1) / 2
    distance_from_mid = abs(slot_mid_minutes - day_mid_minutes)
    centeredness = max(0.0, 150 * (1 - distance_from_mid / half_day_span))

    # Between otherwise-similar slots, prefer the quieter day - e.g. a
    # meeting right after class on a 2-class day beats the same slot
    # shape on a 3-class day.
    quietness_penalty = day_busy_count * 15

    return round(duration_minutes + centeredness - quietness_penalty)

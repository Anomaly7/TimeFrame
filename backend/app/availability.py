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
    tz=PST
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

    def best_window(gap_start, gap_end):
        if gap_end - gap_start < min_duration:
            return None
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

def score_slot(start: datetime, end: datetime, day_start: time, day_end: time, day_busy_count: int = 0) -> int:
    duration_minutes = int((end - start).total_seconds() / 60)

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

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.availability import find_free_time, merge_intervals, score_slot

TZ = ZoneInfo("America/Los_Angeles")
DAY = date(2026, 9, 14)  # a Monday, safely not "today" in any test run
DAY_START = time(8, 0)
DAY_END = time(22, 0)  # midpoint = 15:00


def dt(hour, minute):
    return datetime(2026, 9, 14, hour, minute, tzinfo=TZ)


class TestMergeIntervals:
    def test_empty_input(self):
        assert merge_intervals([]) == []

    def test_non_overlapping_stay_separate(self):
        intervals = [(dt(9, 0), dt(10, 0)), (dt(14, 0), dt(15, 0))]
        assert merge_intervals(intervals) == intervals

    def test_overlapping_intervals_merge(self):
        intervals = [(dt(9, 0), dt(11, 0)), (dt(10, 0), dt(12, 0))]
        assert merge_intervals(intervals) == [(dt(9, 0), dt(12, 0))]

    def test_touching_intervals_merge(self):
        intervals = [(dt(9, 0), dt(10, 0)), (dt(10, 0), dt(11, 0))]
        assert merge_intervals(intervals) == [(dt(9, 0), dt(11, 0))]

    def test_unsorted_input_still_merges_correctly(self):
        intervals = [(dt(14, 0), dt(15, 0)), (dt(9, 0), dt(11, 0)), (dt(10, 0), dt(12, 0))]
        assert merge_intervals(intervals) == [(dt(9, 0), dt(12, 0)), (dt(14, 0), dt(15, 0))]


class TestFindFreeTime:
    def test_empty_day_returns_one_slot_centered_on_midpoint(self):
        slots = find_free_time([], DAY, DAY_START, DAY_END, min_minutes=30, tz=TZ)
        assert slots == [(dt(14, 45), dt(15, 15))]

    def test_slot_length_matches_min_minutes(self):
        slots = find_free_time([], DAY, DAY_START, DAY_END, min_minutes=60, tz=TZ)
        assert slots == [(dt(14, 30), dt(15, 30))]

    def test_gap_before_midpoint_clamps_to_latest_possible_start(self):
        busy = [(dt(10, 0), dt(22, 0))]
        slots = find_free_time(busy, DAY, DAY_START, DAY_END, min_minutes=30, tz=TZ)
        assert slots == [(dt(9, 30), dt(10, 0))]

    def test_gap_after_midpoint_clamps_to_earliest_possible_start(self):
        busy = [(dt(8, 0), dt(17, 0))]
        slots = find_free_time(busy, DAY, DAY_START, DAY_END, min_minutes=30, tz=TZ)
        assert slots == [(dt(17, 0), dt(17, 30))]

    def test_two_gaps_each_produce_one_candidate(self):
        busy = [(dt(11, 0), dt(15, 0))]
        slots = find_free_time(busy, DAY, DAY_START, DAY_END, min_minutes=30, tz=TZ)
        assert slots == [(dt(10, 30), dt(11, 0)), (dt(15, 0), dt(15, 30))]

    def test_gap_shorter_than_min_minutes_is_dropped(self):
        busy = [(dt(8, 0), dt(14, 50)), (dt(15, 10), dt(22, 0))]
        slots = find_free_time(busy, DAY, DAY_START, DAY_END, min_minutes=30, tz=TZ)
        assert slots == []

    def test_fully_booked_day_returns_no_slots(self):
        busy = [(dt(8, 0), dt(22, 0))]
        slots = find_free_time(busy, DAY, DAY_START, DAY_END, min_minutes=30, tz=TZ)
        assert slots == []


class TestScoreSlot:
    def test_slot_near_midpoint_scores_higher_than_far_from_it(self):
        near = score_slot(dt(14, 30), dt(15, 30), DAY_START, DAY_END, day_busy_count=0)
        far = score_slot(dt(8, 0), dt(9, 0), DAY_START, DAY_END, day_busy_count=0)
        assert near > far

    def test_busier_day_scores_lower_for_the_same_slot(self):
        quiet_day = score_slot(dt(11, 0), dt(12, 0), DAY_START, DAY_END, day_busy_count=0)
        busy_day = score_slot(dt(11, 0), dt(12, 0), DAY_START, DAY_END, day_busy_count=3)
        assert quiet_day > busy_day

    def test_each_extra_busy_block_costs_a_fixed_penalty(self):
        one = score_slot(dt(11, 0), dt(12, 0), DAY_START, DAY_END, day_busy_count=1)
        two = score_slot(dt(11, 0), dt(12, 0), DAY_START, DAY_END, day_busy_count=2)
        assert one - two == 15


class TestRankedTimesOfDay:
    def test_parse_prefer_keeps_valid_names_in_order(self):
        from app.availability import parse_prefer
        assert parse_prefer("Evening, morning,bogus,evening") == ["evening", "morning"]
        assert parse_prefer("") is None and parse_prefer(None) is None

    def test_free_day_places_the_meeting_in_the_first_choice(self):
        for prefer, expect_hour in ((["morning"], 9), (["afternoon"], 14), (["evening"], 19)):
            (start, end), = find_free_time([], DAY, DAY_START, DAY_END, min_minutes=60, tz=TZ, prefer=prefer)
            assert start.hour == expect_hour, (prefer, start)
            # morning 8-12 -> 9:30; afternoon 12-5 -> 14:00; evening 5-10 -> 19:00
            assert (end - start).total_seconds() == 3600

    def test_falls_back_to_the_next_choice_when_the_first_is_busy(self):
        busy = [(dt(8, 0), dt(12, 0))]  # whole morning taken
        (start, _), = find_free_time(busy, DAY, DAY_START, DAY_END, min_minutes=60, tz=TZ,
                                      prefer=["morning", "evening", "afternoon"])
        assert start.hour >= 17

    def test_ranking_decides_the_score(self):
        order = ["evening", "morning", "afternoon"]
        evening = score_slot(dt(19, 0), dt(20, 0), DAY_START, DAY_END, prefer=order)
        morning = score_slot(dt(9, 30), dt(10, 30), DAY_START, DAY_END, prefer=order)
        afternoon = score_slot(dt(14, 0), dt(15, 0), DAY_START, DAY_END, prefer=order)
        assert evening > morning > afternoon

    def test_no_ranking_keeps_the_midday_behaviour(self):
        (start, _), = find_free_time([], DAY, DAY_START, DAY_END, min_minutes=60, tz=TZ)
        assert start.hour == 14 and start.minute == 30  # centered on 15:00

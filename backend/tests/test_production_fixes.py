"""Regression tests for the production-readiness fixes."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException

from app.auth_utils import (RateLimiter, create_oauth_state, create_session_token,
                            get_current_user, verify_oauth_state)
from app.availability import find_free_time

TZ = ZoneInfo("America/Vancouver")
DAY = date(2030, 3, 5)  # far future, so "skip the past part of today" never applies


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "x" * 40)


def at(d, h, m=0):
    return datetime.combine(d, time(h, m), tzinfo=TZ)


def test_overnight_event_from_previous_day_blocks_the_morning():
    # 10 PM the night before until 10 AM: nothing should be free before 10.
    busy = [(at(DAY - timedelta(days=1), 22), at(DAY, 10))]
    free = find_free_time(busy, DAY, time(8), time(12), min_minutes=60, tz=TZ)
    assert free and all(s >= at(DAY, 10) for s, _ in free)


def test_multi_day_all_day_event_blocks_every_day_it_covers():
    busy = [(at(DAY - timedelta(days=1), 0), at(DAY + timedelta(days=2), 0))]
    assert find_free_time(busy, DAY, time(8), time(22), min_minutes=30, tz=TZ) == []


def test_missing_or_short_secret_refuses_to_issue_tokens(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "short")
    with pytest.raises(RuntimeError):
        create_session_token("a@b.com")
    monkeypatch.delenv("SESSION_SECRET")
    with pytest.raises(RuntimeError):
        create_session_token("a@b.com")


def test_oauth_state_needs_the_matching_cookie_and_cannot_be_used_as_a_session():
    state, nonce = create_oauth_state()
    assert verify_oauth_state(state, nonce)
    assert not verify_oauth_state(state, "someone-elses-nonce")
    assert not verify_oauth_state(state, None)
    with pytest.raises(HTTPException):
        get_current_user(f"Bearer {state}")


def test_rate_limiter_blocks_after_the_limit():
    limiter = RateLimiter(max_attempts=3, window_seconds=60)
    for _ in range(3):
        limiter.check("ip:1")
    with pytest.raises(HTTPException) as e:
        limiter.check("ip:1")
    assert e.value.status_code == 429
    limiter.check("ip:2")  # other clients unaffected

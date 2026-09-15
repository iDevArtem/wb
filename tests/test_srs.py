from datetime import datetime, timedelta, timezone
import pytest
from bot.services.srs_service import SRSService


def test_sm2_first_success():
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    res = SRSService.calculate_sm2(
        repetition=0,
        interval=1,
        ease_factor=2.5,
        is_success=True,
        now=now,
    )
    assert res.repetition == 1
    assert res.interval == 1
    assert res.ease_factor == 2.5
    assert res.next_review_at == now + timedelta(days=1)


def test_sm2_second_success():
    now = datetime(2026, 1, 2, 12, 0, 0, tzinfo=timezone.utc)
    res = SRSService.calculate_sm2(
        repetition=1,
        interval=1,
        ease_factor=2.5,
        is_success=True,
        now=now,
    )
    assert res.repetition == 2
    assert res.interval == 6
    assert res.ease_factor == 2.5
    assert res.next_review_at == now + timedelta(days=6)


def test_sm2_third_success():
    now = datetime(2026, 1, 8, 12, 0, 0, tzinfo=timezone.utc)
    res = SRSService.calculate_sm2(
        repetition=2,
        interval=6,
        ease_factor=2.5,
        is_success=True,
        now=now,
    )
    assert res.repetition == 3
    # round(6 * 2.5) == 15
    assert res.interval == 15
    assert res.ease_factor == 2.5
    assert res.next_review_at == now + timedelta(days=15)


def test_sm2_fourth_success():
    now = datetime(2026, 1, 23, 12, 0, 0, tzinfo=timezone.utc)
    res = SRSService.calculate_sm2(
        repetition=3,
        interval=15,
        ease_factor=2.5,
        is_success=True,
        now=now,
    )
    assert res.repetition == 4
    # round(15 * 2.5) == 38
    assert res.interval == 38
    assert res.ease_factor == 2.5
    assert res.next_review_at == now + timedelta(days=38)


def test_sm2_failure_resets_repetition_and_interval():
    now = datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc)
    res = SRSService.calculate_sm2(
        repetition=4,
        interval=38,
        ease_factor=2.5,
        is_success=False,
        now=now,
    )
    assert res.repetition == 0
    assert res.interval == 1
    assert round(res.ease_factor, 2) == 2.3
    assert res.next_review_at == now + timedelta(days=1)


def test_sm2_ease_factor_minimum_floor():
    now = datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc)
    # Start with already low ease factor
    res = SRSService.calculate_sm2(
        repetition=1,
        interval=6,
        ease_factor=1.4,
        is_success=False,
        now=now,
    )
    assert res.ease_factor == 1.3

    # Next failure should not decrease below 1.3
    res2 = SRSService.calculate_sm2(
        repetition=0,
        interval=1,
        ease_factor=1.3,
        is_success=False,
        now=now,
    )
    assert res2.ease_factor == 1.3

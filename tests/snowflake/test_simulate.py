import numpy as np
import pytest

from data_stack_bill_cut.snowflake.simulate import (
    billed_segments,
    busy_periods,
    estimate_billing,
)

SMALL = 2.0  # credits per hour


def periods(*intervals, rate=SMALL):
    starts, ends = zip(*intervals, strict=True)
    return busy_periods(starts, ends, [rate] * len(starts))


def test_overlapping_and_touching_queries_merge():
    p = busy_periods([0, 5, 20, 40], [10, 20, 30, 50], [1, 1, 1, 1])
    np.testing.assert_array_equal(p.start, [0, 40])
    np.testing.assert_array_equal(p.end, [30, 50])


def test_merged_period_keeps_highest_rate():
    p = busy_periods([0, 5], [10, 20], [2, 8])
    assert p.rate.tolist() == [8]


def test_empty_and_zero_length_queries():
    assert len(busy_periods([], [], [])) == 0
    assert len(busy_periods([5], [5], [1])) == 0
    assert estimate_billing(busy_periods([], [], []), 60, 100).credits == 0


def test_idle_gap_longer_than_auto_suspend_bills_one_tail():
    # Two 100 s queries 900 s apart, window ends 3900 s after the second one.
    p = periods((0, 100), (1000, 1100))
    at_600 = estimate_billing(p, 600, window_end=5000)
    assert at_600.busy_credits == pytest.approx(200 * SMALL / 3600)
    assert at_600.idle_credits == pytest.approx(1200 * SMALL / 3600)
    assert at_600.resumes == 2

    at_60 = estimate_billing(p, 60, window_end=5000)
    assert at_60.credits == pytest.approx(320 * SMALL / 3600)
    assert at_60.resumes == 2


def test_idle_gap_shorter_than_auto_suspend_is_billed_in_full():
    p = periods((0, 100), (400, 500))
    est = estimate_billing(p, 600, window_end=500)
    assert est.idle_credits == pytest.approx(300 * SMALL / 3600)
    assert est.resumes == 1


@pytest.mark.parametrize("never", [None, 0, np.inf])
def test_never_suspending_warehouse_bills_until_window_end(never):
    p = periods((0, 100), (1000, 1100))
    est = estimate_billing(p, never, window_end=5000)
    assert est.credits == pytest.approx(5000 * SMALL / 3600)
    assert est.resumes == 1


def test_sixty_second_minimum_per_resume():
    p = periods((0, 5))
    est = estimate_billing(p, 10, window_end=1000)
    assert est.topup_credits == pytest.approx(45 * SMALL / 3600)
    assert est.credits == pytest.approx(60 * SMALL / 3600)


def test_segments_match_estimate():
    p = periods((0, 100), (1000, 1100), (1150, 1200))
    start, end, rate = billed_segments(p, 300, window_end=10_000)
    assert np.all(start[1:] >= end[:-1])
    seg_credits = float(np.sum((end - start) * rate) / 3600)
    assert seg_credits == pytest.approx(estimate_billing(p, 300, 10_000).credits)

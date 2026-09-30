"""Warehouse billing model used to price auto-suspend changes.

Snowflake bills a running warehouse per second with a 60-second minimum each time it
resumes, and suspends it after AUTO_SUSPEND seconds without activity. Given the busy
periods reconstructed from QUERY_HISTORY, the billed time under any AUTO_SUSPEND value is:
busy time + idle gaps shorter than AUTO_SUSPEND + one AUTO_SUSPEND tail per suspension.
"""

from dataclasses import dataclass

import numpy as np

MIN_BILLED_SECONDS = 60.0


@dataclass(frozen=True)
class BusyPeriods:
    start: np.ndarray
    end: np.ndarray
    rate: np.ndarray  # credits per hour while the period runs

    def __len__(self) -> int:
        return len(self.start)

    @property
    def busy_seconds(self) -> float:
        return float(np.sum(self.end - self.start))

    @property
    def busy_credits(self) -> float:
        return float(np.sum((self.end - self.start) * self.rate) / 3600.0)


@dataclass(frozen=True)
class BillingEstimate:
    busy_credits: float
    idle_credits: float
    topup_credits: float
    resumes: int

    @property
    def credits(self) -> float:
        return self.busy_credits + self.idle_credits + self.topup_credits


def busy_periods(start, end, rate) -> BusyPeriods:
    """Union of query execution intervals; each merged period keeps the highest rate."""
    start = np.asarray(start, dtype=float)
    end = np.asarray(end, dtype=float)
    rate = np.asarray(rate, dtype=float)
    keep = end > start
    start, end, rate = start[keep], end[keep], rate[keep]
    if len(start) == 0:
        empty = np.array([], dtype=float)
        return BusyPeriods(empty, empty, empty)
    order = np.argsort(start, kind="stable")
    start, end, rate = start[order], end[order], rate[order]
    running_end = np.maximum.accumulate(end)
    is_new = np.ones(len(start), dtype=bool)
    is_new[1:] = start[1:] > running_end[:-1]
    idx = np.flatnonzero(is_new)
    return BusyPeriods(
        start=start[idx],
        end=np.maximum.reduceat(end, idx),
        rate=np.maximum.reduceat(rate, idx),
    )


def _suspend_after(auto_suspend_s: float | None) -> float:
    if auto_suspend_s is None or not np.isfinite(auto_suspend_s) or auto_suspend_s <= 0:
        return np.inf
    return float(auto_suspend_s)


def billed_segments(
    periods: BusyPeriods, auto_suspend_s: float | None, window_end: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Disjoint [start, end) intervals during which the warehouse is billed, with rates."""
    if len(periods) == 0:
        empty = np.array([], dtype=float)
        return empty, empty, empty
    idle = _idle_after(periods, _suspend_after(auto_suspend_s), window_end)
    return periods.start, periods.end + idle, periods.rate


def _idle_after(periods: BusyPeriods, suspend_after: float, window_end: float) -> np.ndarray:
    gaps = periods.start[1:] - periods.end[:-1]
    tail = max(window_end - periods.end[-1], 0.0)
    following = np.append(gaps, tail)
    return np.minimum(following, suspend_after)


def estimate_billing(
    periods: BusyPeriods, auto_suspend_s: float | None, window_end: float
) -> BillingEstimate:
    n = len(periods)
    if n == 0:
        return BillingEstimate(0.0, 0.0, 0.0, 0)
    suspend_after = _suspend_after(auto_suspend_s)
    idle = _idle_after(periods, suspend_after, window_end)
    gaps = periods.start[1:] - periods.end[:-1]
    suspends = gaps > suspend_after

    first = np.concatenate(([0], np.flatnonzero(suspends) + 1))
    last = np.append(first[1:] - 1, n - 1)
    session_seconds = periods.end[last] + idle[last] - periods.start[first]
    topup = np.maximum(MIN_BILLED_SECONDS - session_seconds, 0.0)

    return BillingEstimate(
        busy_credits=periods.busy_credits,
        idle_credits=float(np.sum(idle * periods.rate) / 3600.0),
        topup_credits=float(np.sum(topup * periods.rate[first]) / 3600.0),
        resumes=len(first),
    )

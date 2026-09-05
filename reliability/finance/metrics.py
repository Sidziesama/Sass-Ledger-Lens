"""Seasonal expectation. Turns a delta into a SURPRISE.

"Revenue up 18%" is a delta. If November is always up 18%, the surprise is zero
and there is nothing to explain. This module is what lets the agent say
"revenue grew and that is bad news".

Baselines are always computed from periods STRICTLY BEFORE the one under
analysis, so nothing the agent claims depends on data it would not have had.
"""

from collections import defaultdict
from statistics import mean, pstdev

from .variance import pnl


def _series(ds, periods, metric):
    return [pnl(ds, p)[metric] for p in periods]


def seasonal_index(ds, as_of, metric="revenue", min_history=13):
    """Ratio-to-moving-average seasonal index per calendar month.

    Returns {month_number: index} where 1.0 means an average month. Needs at
    least ~13 periods of history to separate season from trend.
    """
    hist = ds.history_before(as_of)
    if len(hist) < min_history:
        return None
    vals = {p: pnl(ds, p)[metric] for p in hist}
    overall = mean(vals.values())

    # Detrend with a centred 12-month moving average where possible.
    ratios = defaultdict(list)
    for i, p in enumerate(hist):
        lo, hi = max(0, i - 5), min(len(hist), i + 7)
        window = [vals[q] for q in hist[lo:hi]]
        ma = mean(window) if window else overall
        if ma:
            ratios[int(p[5:])].append(vals[p] / ma)

    idx = {m: mean(v) for m, v in ratios.items() if v}
    if not idx:
        return None
    scale = mean(idx.values())
    return {m: v / scale for m, v in idx.items()}


def expectation(ds, period, metric="revenue"):
    """What we should have expected for this period, before looking at it."""
    hist = ds.history_before(period)
    if len(hist) < 13:
        return {"available": False, "reason": "insufficient history for a seasonal baseline"}

    idx = seasonal_index(ds, period, metric)
    vals = {p: pnl(ds, p)[metric] for p in hist}

    # Deseasonalised trailing level and drift.
    deseason = [vals[p] / idx.get(int(p[5:]), 1.0) for p in hist]
    recent = deseason[-6:]
    level = mean(recent)
    if len(deseason) >= 12:
        drift = (mean(deseason[-3:]) - mean(deseason[-9:-6])) / 6.0
    else:
        drift = 0.0

    m = int(period[5:])
    expected = (level + drift * 3) * idx.get(m, 1.0)
    resid = [deseason[i] - mean(deseason[max(0, i - 5):i + 1]) for i in range(len(deseason))]
    sigma = pstdev(resid) * idx.get(m, 1.0) if len(resid) > 2 else 0.0

    actual = pnl(ds, period)[metric]
    surprise = actual - expected
    return {
        "available": True,
        "period": period,
        "metric": metric,
        "actual": round(actual, 2),
        "expected": round(expected, 2),
        "surprise": round(surprise, 2),
        "surprise_pct": round(surprise / expected * 100, 1) if expected else None,
        "sigma": round(sigma, 2),
        "z_score": round(surprise / sigma, 2) if sigma else None,
        "seasonal_index": round(idx.get(m, 1.0), 3),
        "seasonal_index_prior_month": round(idx.get(12 if m == 1 else m - 1, 1.0), 3),
        "history_periods": len(hist),
    }


def expected_mom_pct(ds, period, metric="revenue"):
    """The month-on-month change that seasonality ALONE would produce."""
    idx = seasonal_index(ds, period, metric)
    if not idx:
        return None
    m = int(period[5:])
    pm = 12 if m == 1 else m - 1
    if not idx.get(pm):
        return None
    return round((idx[m] / idx[pm] - 1) * 100, 1)

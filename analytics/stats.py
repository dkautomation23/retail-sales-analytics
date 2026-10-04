"""Two small statistical tools, standard library only: a two-proportion test and the
smallest lift a split test can detect.

Used by F9 (is a difference between two groups of customers more than chance?) and by the
first recommendation (how big must a lift be before a 50/50 test on the new customers we
actually get can see it?). Normal approximations; fine for the group sizes used here
(hundreds to thousands) and wrong for groups under about 30 or rates near 0% or 100%.
"""
from __future__ import annotations

from math import sqrt
from statistics import NormalDist

NORMAL = NormalDist()


def two_proportion_test(x1: int, n1: int, x2: int, n2: int, confidence: float = 0.95) -> dict:
    """Group 1 minus group 2: difference of rates, its confidence interval, two-sided p-value.

    The interval uses each group's own variance; the p-value uses the pooled rate, which is
    the test of "both groups share one rate".
    """
    if min(n1, n2) <= 0 or not (0 <= x1 <= n1 and 0 <= x2 <= n2):
        raise ValueError("counts must satisfy 0 <= x <= n and n > 0")
    p1, p2 = x1 / n1, x2 / n2
    diff = p1 - p2
    z_crit = NORMAL.inv_cdf(0.5 + confidence / 2)
    half = z_crit * sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    pooled = (x1 + x2) / (n1 + n2)
    se0 = sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    z = diff / se0 if se0 else 0.0
    return {"rate1": p1, "rate2": p2, "diff": diff, "low": diff - half, "high": diff + half,
            "z": z, "p": 2 * (1 - NORMAL.cdf(abs(z)))}


def min_detectable_lift(baseline: float, n_per_arm: float, alpha: float = 0.05, power: float = 0.8) -> float:
    """Smallest absolute lift over `baseline` that a two-arm test with `n_per_arm` customers per
    arm detects with the given power (two-sided alpha). Solves d = (z_a + z_b) * se(d) by
    iteration, because the variance depends on the rate being tested."""
    if not (0 < baseline < 1) or n_per_arm <= 0:
        raise ValueError("baseline must be in (0, 1) and n_per_arm positive")
    z = NORMAL.inv_cdf(1 - alpha / 2) + NORMAL.inv_cdf(power)
    d = z * sqrt(2 * baseline * (1 - baseline) / n_per_arm)
    for _ in range(50):
        p1 = min(baseline + d, 0.999999)
        d_next = z * sqrt((baseline * (1 - baseline) + p1 * (1 - p1)) / n_per_arm)
        if abs(d_next - d) < 1e-12:
            break
        d = d_next
    return d

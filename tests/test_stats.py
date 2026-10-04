"""The two statistical tools on cases with known answers. No database."""
import random
from math import isclose, sqrt

import pytest

from analytics.stats import min_detectable_lift, two_proportion_test


def test_textbook_two_proportion_case():
    # 50/100 vs 40/100: pooled rate 0.45, z = 0.10 / sqrt(0.45*0.55*0.02) = 1.4213, p = 0.1553
    r = two_proportion_test(50, 100, 40, 100)
    assert isclose(r["diff"], 0.10)
    assert isclose(r["z"], 0.10 / sqrt(0.45 * 0.55 * 0.02), rel_tol=1e-9)
    assert isclose(r["p"], 0.1553, abs_tol=5e-4)
    assert r["low"] < r["diff"] < r["high"]


def test_identical_groups_give_p_one_and_an_interval_around_zero():
    r = two_proportion_test(30, 100, 300, 1000)
    assert r["diff"] == 0 and isclose(r["p"], 1.0) and r["low"] < 0 < r["high"]


def test_swapping_groups_flips_the_sign_and_keeps_the_p_value():
    a, b = two_proportion_test(120, 400, 90, 500), two_proportion_test(90, 500, 120, 400)
    assert isclose(a["diff"], -b["diff"]) and isclose(a["p"], b["p"])


def test_a_large_gap_is_significant_and_a_small_sample_hides_it():
    assert two_proportion_test(500, 1000, 400, 1000)["p"] < 1e-4
    assert two_proportion_test(5, 10, 4, 10)["p"] > 0.5


@pytest.mark.parametrize("bad", [(1, 0, 1, 5), (6, 5, 1, 5), (-1, 5, 1, 5)])
def test_impossible_counts_are_refused(bad):
    with pytest.raises(ValueError):
        two_proportion_test(*bad)


def test_the_smallest_detectable_lift_shrinks_with_more_customers():
    sizes = [100, 400, 1600, 6400]
    lifts = [min_detectable_lift(0.21, n) for n in sizes]
    assert lifts == sorted(lifts, reverse=True)
    assert isclose(lifts[0] / lifts[-1], 8, rel_tol=0.15)  # 64x the customers -> about 1/8 the lift


def test_a_lift_of_one_point_at_21_percent_needs_tens_of_thousands_per_arm():
    # Known sample-size result: n = (1.96 + 0.84)^2 * (p1q1 + p2q2) / d^2, about 26,000 per arm.
    n = (1.959964 + 0.841621) ** 2 * (0.21 * 0.79 + 0.22 * 0.78) / 0.01 ** 2
    assert 25_000 < n < 27_500
    assert isclose(min_detectable_lift(0.21, n), 0.01, rel_tol=1e-3)


def test_the_test_really_detects_a_lift_of_the_stated_size_about_eighty_percent_of_the_time():
    random.seed(7)
    n, base = 1200, 0.21
    lift = min_detectable_lift(base, n)
    hits, runs = 0, 400
    for _ in range(runs):
        a = sum(random.random() < base for _ in range(n))
        b = sum(random.random() < base + lift for _ in range(n))
        hits += two_proportion_test(b, n, a, n)["p"] < 0.05
    assert 0.72 < hits / runs < 0.88

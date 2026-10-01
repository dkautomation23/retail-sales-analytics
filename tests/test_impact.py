"""The retention-value estimate on numbers small enough to check by hand. No database."""
import pandas as pd

from analytics.impact import annual_value_of_one_point, twelve_month_values


def test_one_point_is_new_customers_times_twelve_times_one_percent_times_the_gap():
    # 100 new customers a month -> 12 more returners a year at +1 pp, each worth 500 - 200.
    assert annual_value_of_one_point(100, 500, 200) == 12 * 300


def frame(rows):
    return pd.DataFrame(rows, columns=["customer_key", "cohort", "month_start", "net", "sold"])


def test_twelve_month_values_split_returners_and_skip_unusable_cohorts():
    rows = [
        # cohort Feb 2010: customer 1 comes back in month 1, customer 2 only in month 3
        (1, "2010-02-01", "2010-02-01", 50, 50), (1, "2010-02-01", "2010-03-01", 100, 100),
        (1, "2010-02-01", "2011-02-01", 20, 20),      # month +12: counted
        (1, "2010-02-01", "2011-03-01", 999, 999),    # month +13: outside the window
        (2, "2010-02-01", "2010-02-01", 70, 70), (2, "2010-02-01", "2010-05-01", 40, 40),
        # customer 3 buys in month 1 but cancels it all: still a returner, net 0
        (3, "2010-02-01", "2010-02-01", 10, 10), (3, "2010-02-01", "2010-03-01", 0, 30),
        # first month of data: existing customers, excluded
        (4, "2010-01-01", "2010-02-01", 5000, 5000),
        # cohort too young for 12 complete months: excluded
        (5, "2011-01-01", "2011-02-01", 7000, 7000),
    ]
    returning, other, first, last = twelve_month_values(
        frame(rows), first_month=pd.Timestamp("2010-01-01"), last_complete_month=pd.Timestamp("2011-11-01"))
    assert returning == (120 + 0) / 2          # customers 1 and 3
    assert other == 40                         # customer 2
    assert (first, last) == ("Feb 2010", "Feb 2010")

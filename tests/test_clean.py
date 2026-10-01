"""Cleaning rules on a hand-made frame: no database, no download."""
import pandas as pd

from analytics.clean import clean, format_steps


def frame(rows):
    return pd.DataFrame(rows, columns=["Invoice", "StockCode", "Description", "Quantity",
                                       "InvoiceDate", "Price", "Customer ID", "Country"])


BASE = ["500001", "85123A", "HEART HOLDER", 6, "2010-01-04 10:00", 2.55, 13085.0, "United Kingdom"]


def test_exact_duplicates_are_removed_once():
    result = clean(frame([BASE, BASE]))
    assert len(result.sales) == 1
    assert result.steps[0] == ("exact duplicate lines", 2, 1, 1)


def test_cancellations_go_to_returns_with_positive_quantity():
    cancel = ["C500002", "85123A", "HEART HOLDER", -3, "2010-01-05 10:00", 2.55, 13085.0, "United Kingdom"]
    result = clean(frame([BASE, cancel]))
    assert list(result.sales["Invoice"]) == ["500001"]
    assert list(result.returns["Quantity"]) == [3]


def test_postage_and_fees_are_not_products():
    postage = ["500003", "POST", "POSTAGE", 1, "2010-01-04 11:00", 18.0, 12345.0, "Germany"]
    fee = ["500004", "BANK CHARGES", "Bank Charges", 1, "2010-01-04 11:00", 15.0, None, "United Kingdom"]
    result = clean(frame([BASE, postage, fee]))
    assert list(result.sales["StockCode"]) == ["85123A"]


def test_zero_price_and_negative_quantity_are_dropped():
    free = ["500005", "22423", "CAKESTAND", 2, "2010-01-04 12:00", 0.0, 13085.0, "United Kingdom"]
    negative = ["500006", "22423", "CAKESTAND", -2, "2010-01-04 12:00", 12.75, 13085.0, "United Kingdom"]
    result = clean(frame([BASE, free, negative]))
    assert len(result.sales) == 1


def test_guest_lines_are_kept_and_counted():
    guest = ["500007", "22423", "CAKESTAND", 1, "2010-01-04 12:00", 12.75, None, "United Kingdom"]
    result = clean(frame([BASE, guest]))
    assert len(result.sales) == 2
    assert result.guest_lines == 1


def test_every_step_accounts_for_its_rows():
    result = clean(frame([BASE, BASE]))
    for _, before, after, removed in result.steps:
        assert before - after == removed
    assert "exact duplicate lines" in format_steps(result.steps)

"""Cleaning rules, each one counted.

Every rule takes the frame, removes or moves rows, and records how many rows it
touched. The table of counts is printed by the ETL and quoted in the README, so
"we cleaned the data" is a list of numbers someone can rerun.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

# Real products carry a five-digit stock code, sometimes with a letter suffix
# (e.g. 85123A). Everything else is postage, fees, manual adjustments or tests.
PRODUCT_CODE = r"^\d{5}"


@dataclass
class Cleaned:
    sales: pd.DataFrame
    returns: pd.DataFrame
    steps: list = field(default_factory=list)   # (rule, rows_before, rows_after, removed)
    guest_lines: int = 0   # kept, loaded with customer_key 0: revenue is real, the customer is unknown


def clean(raw: pd.DataFrame) -> Cleaned:
    steps = []
    df = raw.copy()

    def step(rule: str, keep: pd.Series) -> None:
        nonlocal df
        before = len(df)
        df = df[keep]
        steps.append((rule, before, len(df), before - len(df)))

    step("exact duplicate lines", ~df.duplicated(keep="first"))

    is_cancel = df["Invoice"].astype(str).str.startswith("C")
    cancels = df[is_cancel]
    step("cancellations moved to fact_returns", ~is_cancel)

    step("non-product stock codes (postage, fees, adjustments)",
         df["StockCode"].astype(str).str.match(PRODUCT_CODE))
    step("quantity zero or negative", df["Quantity"] > 0)
    step("unit price zero or negative", df["Price"] > 0)

    returns = cancels[cancels["StockCode"].astype(str).str.match(PRODUCT_CODE)
                      & (cancels["Quantity"] < 0)].copy()
    returns["Quantity"] = -returns["Quantity"]
    returns = returns[returns["Price"] >= 0]

    return Cleaned(sales=df.reset_index(drop=True), returns=returns.reset_index(drop=True),
                   steps=steps, guest_lines=int(df["Customer ID"].isna().sum()))


def format_steps(steps: list) -> str:
    width = max(len(s[0]) for s in steps)
    lines = [f"{'rule'.ljust(width)}  {'before':>9}  {'after':>9}  {'removed':>8}"]
    for rule, before, after, removed in steps:
        lines.append(f"{rule.ljust(width)}  {before:>9,}  {after:>9,}  {removed:>8,}")
    return "\n".join(lines)

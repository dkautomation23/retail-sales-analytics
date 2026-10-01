"""Build docs/index.html: one static page, KPIs on top, six charts.

    python -m analytics.dashboard

Plotly is loaded from its CDN so the page stays small enough to commit; the
data itself is embedded, so nothing is queried when the page is opened.
"""
from __future__ import annotations

import html
from pathlib import Path

import plotly.express as px
import plotly.graph_objects as go

from . import findings, queries
from .db import scalar

OUT = Path(__file__).resolve().parent.parent / "docs" / "index.html"
LAYOUT = dict(template="plotly_white", margin=dict(l=40, r=20, t=16, b=40), autosize=True)
LABELS = {"net_revenue": "net revenue, GBP", "name": "", "product": "", "revenue": "revenue, GBP",
          "month_start": "", "pct": "%", "segment": "", "measure": "", "return_rate_pct": "cancelled, % of sold"}


def figures() -> list:
    monthly = queries.run("01_monthly_revenue")
    monthly = monthly[~monthly["partial_month"]]
    monthly["net_revenue"] = monthly["net_revenue"].astype(float)
    f1 = px.line(monthly, x="month_start", y="net_revenue", markers=True,
                 labels=LABELS, title="Monthly net revenue, GBP (partial Dec 2011 excluded)")

    cohort = queries.run("02_cohort_retention")
    cohort = cohort[(cohort["months_since_first"] > 0) & (cohort["months_since_first"] <= 12)]
    grid = cohort.pivot(index="cohort", columns="months_since_first", values="retention_pct").astype(float)
    f2 = go.Figure(go.Heatmap(z=grid.values, x=[f"+{m}" for m in grid.columns],
                              y=[str(c)[:7] for c in grid.index], colorscale="Blues",
                              colorbar=dict(title="%")))
    f2.update_layout(title="Cohort retention: % of new customers buying again N months later")

    rfm = queries.run("03_rfm_segments")
    rfm_long = rfm.melt(id_vars="segment", value_vars=["share_of_customers_pct", "share_of_revenue_pct"],
                        var_name="measure", value_name="pct")
    rfm_long["pct"] = rfm_long["pct"].astype(float)
    rfm_long["measure"] = rfm_long["measure"].map({"share_of_customers_pct": "% of customers",
                                                   "share_of_revenue_pct": "% of net revenue"})
    f3 = px.bar(rfm_long, x="segment", y="pct", color="measure", barmode="group",
                labels=LABELS, title="RFM segments: share of customers vs share of net revenue")

    top = queries.run("04_top_products_countries")
    for col in ("net_revenue",):
        top[col] = top[col].astype(float)
    countries = top[(top["dimension"] == "country") & (top["name"] != "United Kingdom")]
    f4 = px.bar(countries.sort_values("net_revenue"), x="net_revenue", y="name", orientation="h",
                labels=LABELS, title="Top countries outside the UK, net revenue GBP")
    products = top[top["dimension"] == "product"]
    f5 = px.bar(products.sort_values("net_revenue"), x="net_revenue", y="name", orientation="h",
                labels=LABELS, title="Top 10 products by net revenue (sales minus cancellations), GBP")

    ret = queries.run("05_return_rate")
    ret = ret[~ret["product"].str.startswith("ALL PRODUCTS")].copy()
    ret["return_rate_pct"] = ret["return_rate_pct"].astype(float)
    f6 = px.bar(ret.sort_values("return_rate_pct"), x="return_rate_pct", y="product", orientation="h",
                labels=LABELS, title="Highest cancellation rates, same-day reversals excluded (%)")

    # Titles move out of Plotly into HTML, where they wrap on a phone instead of being cut.
    charts = []
    for fig in (f1, f2, f3, f4, f5, f6):
        title = fig.layout.title.text
        fig.update_layout(**LAYOUT, title=None)
        charts.append((title, fig))
    return charts


def kpis() -> list:
    gross = float(scalar("SELECT sum(revenue) FROM fact_sales"))
    cancelled = float(scalar("SELECT sum(amount) FROM fact_returns"))
    orders = int(scalar("SELECT count(DISTINCT invoice) FROM fact_sales"))
    customers = int(scalar("SELECT count(DISTINCT customer_key) FROM fact_sales WHERE customer_key <> 0"))
    return [("Net revenue", f"£{gross - cancelled:,.0f}"), ("Orders", f"{orders:,}"),
            ("Avg order value", f"£{gross / orders:,.2f}"), ("Customers who bought", f"{customers:,}"),
            ("Cancelled, % of sales", f"{100 * cancelled / gross:.2f}%")]


def build() -> str:
    # Fixed div ids: Plotly picks random ones, which would change the file on every rebuild.
    charts = [(title, fig.to_html(full_html=False, include_plotlyjs=False, default_width="100%",
                                  default_height="360px", div_id=f"chart-{n}",
                                  config={"displayModeBar": False, "responsive": True}))
              for n, (title, fig) in enumerate(figures(), 1)]
    cards = "".join(f'<div class="kpi"><div class="v">{html.escape(v)}</div><div class="k">{html.escape(k)}</div></div>'
                    for k, v in kpis())
    notes = "".join(f"<li>{html.escape(line)}</li>" for line in findings.compute())
    grid = "".join(f'<div class="card"><h3>{html.escape(title)}</h3>{chart}</div>' for title, chart in charts)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Online Retail II - sales dashboard</title>
<script src="https://cdn.plot.ly/plotly-3.1.1.min.js"
 integrity="sha384-eyWfwv4NWkH7sLjk6s+Al2SBmZhX8gcLellpr+PLrfiNaHoTlAQTG9zDi4Z0liz8"
 crossorigin="anonymous"></script>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f6f7f9;color:#1d2330}}
header{{padding:24px 32px 8px}} h1{{margin:0 0 4px;font-size:24px}} .sub{{color:#5b6475;font-size:14px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px;padding:16px 32px;max-width:1100px}}
.kpi{{background:#fff;border-radius:10px;padding:14px 18px;box-shadow:0 1px 2px #0001}}
.kpi .v{{font-size:22px;font-weight:600}} .kpi .k{{color:#5b6475;font-size:13px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(520px,1fr));gap:16px;padding:8px 32px}}
.card{{background:#fff;border-radius:10px;padding:8px;box-shadow:0 1px 2px #0001;min-width:0;overflow:hidden}}
.card h3{{font-size:15px;font-weight:600;margin:10px 12px 0;color:#2a3142}}
.findings{{padding:8px 32px 32px}} .findings li{{margin:6px 0}}
@media (max-width:600px){{.grid{{grid-template-columns:1fr;padding:8px 16px}} .kpis{{grid-template-columns:1fr 1fr}}
.kpis,header,.findings{{padding-left:16px;padding-right:16px}} .kpi .v{{font-size:19px}}}}
</style></head><body>
<header><h1>Online Retail II - sales dashboard</h1>
<div class="sub">UK gift wholesaler, Dec 2009 - Dec 2011, 1,003,214 cleaned sales lines.
Source: UCI Machine Learning Repository (CC BY 4.0). Built by
<a href="https://github.com/dkautomation23/retail-sales-analytics">retail-sales-analytics</a>.</div></header>
<section class="kpis">{cards}</section>
<section class="grid">{grid}</section>
<section class="findings"><h2>Findings</h2><ul>{notes}</ul></section>
<script>window.addEventListener("load",function(){{document.querySelectorAll(".js-plotly-plot").forEach(function(p){{Plotly.Plots.resize(p);}});}});</script>
</body></html>
"""


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    page = build()
    OUT.write_text(page, encoding="utf-8")
    print(f"wrote {OUT.name}: {len(page.encode()):,} bytes, {page.count('Plotly.newPlot')} charts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

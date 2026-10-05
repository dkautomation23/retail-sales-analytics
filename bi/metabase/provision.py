"""Set up the local Metabase over the warehouse: admin, database, four saved questions, one dashboard.

    docker compose up -d --wait metabase
    python bi/metabase/provision.py

Safe to run twice: whatever already exists (admin, database, a question or the dashboard
with the same name) is reused and brought up to date, not duplicated. If two objects share a name,
or a database with our name points elsewhere, it stops and says so. Standard library only. The admin login comes
from MB_ADMIN_EMAIL / MB_ADMIN_PASSWORD, falling back to the demo values in .env.example.
The warehouse is reached from inside the compose network as host "db", port 5432.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
BASE_URL = os.environ.get("MB_URL", "http://127.0.0.1:3000")
DB_NAME = "Retail warehouse"
DASHBOARD = "Retail sales overview"

NET_REVENUE = """
SELECT (SELECT sum(revenue) FROM fact_sales) - (SELECT sum(amount) FROM fact_returns) AS net_revenue
"""
MONTHLY = """
SELECT d.month_start AS month,
       coalesce(s.gross, 0) - coalesce(r.cancelled, 0) AS net_revenue
FROM (SELECT DISTINCT month_start FROM dim_date) d
LEFT JOIN (SELECT dd.month_start, sum(revenue) AS gross
           FROM fact_sales f JOIN dim_date dd USING (date_key) GROUP BY 1) s USING (month_start)
LEFT JOIN (SELECT dd.month_start, sum(amount) AS cancelled
           FROM fact_returns f JOIN dim_date dd USING (date_key) GROUP BY 1) r USING (month_start)
ORDER BY 1
"""
TOP_COUNTRIES = """
SELECT c.country, round(sum(f.revenue)) AS gross_revenue
FROM fact_sales f JOIN dim_country c USING (country_key)
WHERE c.country <> 'United Kingdom'
GROUP BY c.country
ORDER BY gross_revenue DESC
LIMIT 10
"""
REPEAT_BY_COHORT = """
WITH months AS (
    SELECT f.customer_key, d.month_start
    FROM fact_sales f JOIN dim_date d USING (date_key)
    WHERE f.customer_key <> 0
    GROUP BY 1, 2
),
customers AS (
    SELECT customer_key, min(month_start) AS first_month, count(*) AS active_months FROM months GROUP BY 1
)
SELECT first_month AS cohort,
       count(*) AS customers,
       round(100.0 * count(*) FILTER (WHERE active_months > 1) / count(*), 1) AS bought_again_pct
FROM customers
WHERE first_month > (SELECT min(month_start) FROM dim_date)
GROUP BY 1
ORDER BY 1
"""

# name, display, SQL. The first one is the number to compare with bi/measures.md.
QUESTIONS = [
    {"name": "Net revenue", "display": "scalar", "sql": NET_REVENUE, "size": (8, 3),
     "settings": {"scalar.compact_primary_number": False}},
    {"name": "Monthly net revenue", "display": "line", "sql": MONTHLY, "size": (16, 6),
     "settings": {"graph.dimensions": ["month"], "graph.metrics": ["net_revenue"]}},
    {"name": "Top 10 countries outside the UK by gross revenue", "display": "bar", "sql": TOP_COUNTRIES,
     "size": (12, 7), "settings": {"graph.dimensions": ["country"], "graph.metrics": ["gross_revenue"]}},
    {"name": "Customers active in more than one month, % by first-purchase month",
     "display": "bar", "sql": REPEAT_BY_COHORT, "size": (12, 7),
     "settings": {"graph.dimensions": ["cohort"], "graph.metrics": ["bought_again_pct"]}},
]


def credentials(env_file: Path = ROOT / ".env.example") -> tuple[str, str]:
    """The environment wins; the example file only fills what is missing."""
    found = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                found[key.strip()] = value.strip()
    email = os.environ.get("MB_ADMIN_EMAIL") or found.get("MB_ADMIN_EMAIL")
    password = os.environ.get("MB_ADMIN_PASSWORD") or found.get("MB_ADMIN_PASSWORD")
    if not email or not password:
        raise SystemExit("set MB_ADMIN_EMAIL and MB_ADMIN_PASSWORD (demo values are in .env.example)")
    return email, password


def by_name(items: list, kind: str) -> dict:
    """name -> id; two objects with one name make the run ambiguous, so stop instead of guessing."""
    found: dict = {}
    for item in items:
        if item["name"] in found:
            raise SystemExit(f"two Metabase {kind}s are named {item['name']!r}; rename or archive one and rerun")
        found[item["name"]] = item["id"]
    return found


def card_payload(question: dict, database_id: int) -> dict:
    return {
        "name": question["name"],
        "display": question["display"],
        "visualization_settings": question.get("settings", {}),
        "dataset_query": {"type": "native", "database": database_id, "native": {"query": question["sql"]}},
    }


def dashcards(card_ids: dict) -> list:
    """Lay the cards out on Metabase's 24-column grid, left to right, wrapping to a new row."""
    placed, row, col, row_height = [], 0, 0, 0
    for index, question in enumerate(QUESTIONS):
        width, height = question["size"]
        if col + width > 24:
            row, col, row_height = row + row_height, 0, 0
        placed.append({"id": -(index + 1), "card_id": card_ids[question["name"]], "row": row, "col": col,
                       "size_x": width, "size_y": height, "parameter_mappings": [],
                       "visualization_settings": {}})
        col += width
        row_height = max(row_height, height)
    return placed


class Metabase:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self.session: str | None = None

    def call(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        if self.session:
            request.add_header("X-Metabase-Session", self.session)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            raise SystemExit(f"{method} {path} -> HTTP {error.code}: {error.read().decode('utf-8', 'replace')[:300]}")
        return json.loads(raw) if raw else None

    def wait_until_ready(self, seconds: int = 180) -> None:
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                if urllib.request.urlopen(self.base + "/api/health", timeout=5).status == 200:
                    return
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(3)
        raise SystemExit(f"Metabase did not answer at {self.base}; run: docker compose up -d --wait metabase")

    def sign_in(self, email: str, password: str) -> None:
        properties = self.call("GET", "/api/session/properties")
        token = properties.get("setup-token")
        if token:
            self.call("POST", "/api/setup", {
                "token": token,
                "user": {"first_name": "Demo", "last_name": "Admin", "email": email, "password": password,
                         "site_name": "Retail demo"},
                "prefs": {"site_name": "Retail demo", "site_locale": "en", "allow_tracking": False}})
        self.session = self.call("POST", "/api/session", {"username": email, "password": password})["id"]

    def database(self) -> int:
        existing = self.call("GET", "/api/database")
        for item in existing["data"] if isinstance(existing, dict) else existing:
            if item["name"] == DB_NAME:
                details = item.get("details") or {}
                if item.get("engine") != "postgres" or details.get("dbname") != "retail":
                    raise SystemExit(f"a Metabase database named {DB_NAME!r} exists but is not the retail Postgres; "
                                     "rename it and rerun")
                return item["id"]
        created = self.call("POST", "/api/database", {
            "name": DB_NAME, "engine": "postgres",
            "details": {"host": "db", "port": 5432, "dbname": "retail", "user": "retail", "password": "retail",
                        "ssl": False},
            "is_full_sync": True, "auto_run_queries": True})
        self.call("POST", f"/api/database/{created['id']}/sync_schema")
        return created["id"]

    def cards(self, database_id: int) -> dict:
        have = by_name(self.call("GET", "/api/card"), "card")
        ids = {}
        for question in QUESTIONS:
            payload = card_payload(question, database_id)
            if question["name"] in have:
                ids[question["name"]] = have[question["name"]]
                self.call("PUT", f"/api/card/{have[question['name']]}", payload)
            else:
                ids[question["name"]] = self.call("POST", "/api/card", payload)["id"]
        return ids

    def dashboard(self, card_ids: dict) -> int:
        have = by_name(self.call("GET", "/api/dashboard"), "dashboard")
        dashboard_id = have.get(DASHBOARD) or self.call("POST", "/api/dashboard", {"name": DASHBOARD})["id"]
        self.call("PUT", f"/api/dashboard/{dashboard_id}", {"dashcards": dashcards(card_ids)})
        return dashboard_id


def main() -> int:
    email, password = credentials()
    client = Metabase(BASE_URL)
    client.wait_until_ready()
    client.sign_in(email, password)
    database_id = client.database()
    card_ids = client.cards(database_id)
    dashboard_id = client.dashboard(card_ids)
    print(f"database {database_id}, {len(card_ids)} questions, dashboard {BASE_URL}/dashboard/{dashboard_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

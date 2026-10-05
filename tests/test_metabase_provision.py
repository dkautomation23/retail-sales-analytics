"""The Metabase provisioning script's pure parts. No network, no running Metabase."""
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "provision", Path(__file__).resolve().parent.parent / "bi" / "metabase" / "provision.py")
provision = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provision)


def test_questions_are_read_only_sql_with_distinct_names():
    names = [q["name"] for q in provision.QUESTIONS]
    assert len(names) == len(set(names)) >= 4
    for q in provision.QUESTIONS:
        sql = q["sql"].lstrip().lower()
        assert sql.startswith(("select", "with")), q["name"]
        assert not any(w in sql for w in ("insert ", "update ", "delete ", "drop ", "alter ")), q["name"]


def test_card_payload_points_at_the_database_and_carries_the_sql():
    q = provision.QUESTIONS[0]
    payload = provision.card_payload(q, database_id=7)
    assert payload["name"] == q["name"]
    assert payload["display"] == q["display"]
    assert payload["dataset_query"] == {"type": "native", "database": 7, "native": {"query": q["sql"]}}
    assert payload["visualization_settings"] == q.get("settings", {})


def test_chart_settings_name_columns_that_appear_in_the_query():
    """Metabase silently ignores a setting that names a column the query does not return."""
    import re
    for q in provision.QUESTIONS:
        for key in ("graph.dimensions", "graph.metrics"):
            for name in q.get("settings", {}).get(key, []):
                assert re.search(rf"\b{name}\b", q["sql"]), f"{q['name']}: {name} is not in the SQL"


def test_dashboard_cards_do_not_overlap_and_fit_the_grid():
    cards = provision.dashcards({q["name"]: i + 1 for i, q in enumerate(provision.QUESTIONS)})
    assert len(cards) == len(provision.QUESTIONS)
    taken = set()
    for c in cards:
        assert c["col"] + c["size_x"] <= 24
        cells = {(c["row"] + r, c["col"] + k) for r in range(c["size_y"]) for k in range(c["size_x"])}
        assert not cells & taken, "two cards overlap"
        taken |= cells


def test_env_file_is_a_fallback_not_an_override(tmp_path, monkeypatch):
    env = tmp_path / ".env.example"
    env.write_text("# comment\nMB_ADMIN_EMAIL=from-file@users.noreply.github.com\nMB_ADMIN_PASSWORD=file-pass\n")
    monkeypatch.setenv("MB_ADMIN_PASSWORD", "from-environment")
    monkeypatch.delenv("MB_ADMIN_EMAIL", raising=False)
    creds = provision.credentials(env)
    assert creds == ("from-file@users.noreply.github.com", "from-environment")


def test_missing_credentials_raise_instead_of_guessing(tmp_path, monkeypatch):
    monkeypatch.delenv("MB_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("MB_ADMIN_PASSWORD", raising=False)
    with pytest.raises(SystemExit):
        provision.credentials(tmp_path / "missing.env")


class FakeMetabase(provision.Metabase):
    """Records calls instead of sending them; GET /api/card returns what a first run created."""

    def __init__(self, existing):
        super().__init__("http://unused")
        self.existing, self.calls = existing, []

    def call(self, method, path, body=None):
        self.calls.append((method, path))
        if (method, path) == ("GET", "/api/card"):
            return [{"name": n, "id": i} for n, i in self.existing.items()]
        return {"id": 99}


def test_first_run_creates_each_card_once():
    client = FakeMetabase({})
    ids = client.cards(database_id=2)
    assert len(ids) == len(provision.QUESTIONS)
    assert [c for c in client.calls if c[0] == "POST"] == [("POST", "/api/card")] * len(provision.QUESTIONS)
    assert not [c for c in client.calls if c[0] == "PUT"]


def test_second_run_updates_existing_cards_and_creates_none():
    existing = {q["name"]: 10 + i for i, q in enumerate(provision.QUESTIONS)}
    client = FakeMetabase(existing)
    assert client.cards(database_id=2) == existing
    assert not [c for c in client.calls if c[0] == "POST"]
    assert sorted(c for c in client.calls if c[0] == "PUT") == sorted(("PUT", f"/api/card/{i}") for i in existing.values())


def test_two_cards_with_one_name_stop_the_run_instead_of_guessing():
    class Twin(FakeMetabase):
        def call(self, method, path, body=None):
            if (method, path) == ("GET", "/api/card"):
                name = provision.QUESTIONS[0]["name"]
                return [{"name": name, "id": 1}, {"name": name, "id": 2}]
            return super().call(method, path, body)
    with pytest.raises(SystemExit):
        Twin({}).cards(database_id=2)


def test_a_database_with_our_name_but_other_settings_stops_the_run():
    class Imposter(FakeMetabase):
        def call(self, method, path, body=None):
            if (method, path) == ("GET", "/api/database"):
                return {"data": [{"name": provision.DB_NAME, "id": 5, "engine": "mysql", "details": {"dbname": "other"}}]}
            return super().call(method, path, body)
    with pytest.raises(SystemExit):
        Imposter({}).database()


def test_the_cohort_question_does_not_claim_more_than_the_sql_counts():
    """The SQL counts months with a purchase, so the title must not say 'bought again' (two orders in one month are one month)."""
    cohort = [q for q in provision.QUESTIONS if "cohort" in q["sql"].lower() or "first_month" in q["sql"]][0]
    assert "again" not in cohort["name"].lower()
    assert not any("again" in m for m in cohort["settings"]["graph.metrics"]), "the axis label would still say 'again'"
    assert "month" in cohort["name"].lower()

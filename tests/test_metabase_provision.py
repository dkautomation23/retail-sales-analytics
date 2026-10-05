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

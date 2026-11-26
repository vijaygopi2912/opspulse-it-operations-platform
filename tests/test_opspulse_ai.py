"""Automated checks for the OPSPULSE AI logic.

Run from the project root:  python -m pytest -q
(Install once: pip install pytest)
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from opspulse_ai import OpsPulseAI  # noqa: E402


@pytest.fixture(scope="module")
def ai():
    return OpsPulseAI(root=Path(__file__).resolve().parents[1])


def test_risk_rises_as_sla_time_runs_out(ai):
    risks = [ai.risk("P3", h)["breach_risk"] for h in (1, 3, 5, 7)]
    assert risks == sorted(risks), "risk should never go down as time passes"


def test_alert_ok_and_breached_statuses(ai):
    assert ai.risk("P3", 1)["status"] == "OK"
    assert ai.risk("P3", 7.5)["status"] == "Alert"
    assert ai.risk("P3", 9)["status"] == "Breached"
    assert ai.risk("P3", 9)["hours_left"] == 0


def test_unknown_priority_is_rejected(ai):
    with pytest.raises(ValueError):
        ai.risk("P9", 1)


def test_open_at_matches_the_data(ai):
    as_of = pd.Timestamp("2026-09-03 14:00")
    o = ai.open_at(as_of)
    t = ai.tickets
    expected = ((t["opened_at"] <= as_of) & (t["resolved_at"].isna() | (t["resolved_at"] > as_of))).sum()
    assert len(o) == expected
    assert set(o["status"]) <= {"Alert", "OK", "Breached"}
    assert (o.loc[o["status"] == "Breached", "hours_left"] == 0).all()


def test_triage_returns_a_full_answer(ai):
    pytest.importorskip("fastembed")  # needs the free local AI model
    r = ai.triage("The printer on the 3rd floor is jammed again")
    assert r["priority"] in {"P1", "P2", "P3", "P4"}
    assert r["team"] in {"Network Team", "Desktop Support", "Application Support",
                         "Service Desk", "Security Operations"}
    assert len(r["similar_tickets"]) == 3
    assert 0 <= r["category_confidence"] <= 1

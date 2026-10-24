"""Live AI trace (Stretch S1, D-023): POST /emails/{id}/interpret/stream.

Offline, replay mode. The stream replays the Interpretation POST /interpret returns.
"""

# ruff: noqa: F811  (fixtures imported from test_workflow_api are used by name)
from __future__ import annotations

import json
import time

import pytest

from services.api.db import models as m
from services.api.db.session import session_scope
from tests.test_workflow_api import H, _clock, client  # noqa: F401 - fixtures are used by name

OWNS_APP_DB = True  # see tests/conftest.py


def stream(client, email_id, user="marcus", step_ms=0):
    r = client.post(
        f"/emails/{email_id}/interpret/stream",
        headers=H(user),
        params={} if step_ms is None else {"step_ms": step_ms},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["x-accel-buffering"] == "no"
    steps = []
    for block in r.text.split("\n\n"):
        if not block.strip():
            continue
        lines = block.split("\n")
        assert lines[0] == "event: step" and lines[1].startswith("data: ")
        steps.append(json.loads(lines[1][len("data: ") :]))
    return steps, r.text


def kinds(steps):
    return [s["kind"] for s in steps]


@pytest.mark.parametrize("email_id", ["DEMO-01", "DEMO-02", "DEMO-03", "DEMO-06", "DEMO-07"])
def test_done_equals_the_post_result_and_order_follows_the_contract(client, email_id):
    steps, _ = stream(client, email_id)
    posted = client.post(f"/emails/{email_id}/interpret", headers=H("marcus")).json()
    assert steps[0]["kind"] == "start" and steps[-1]["kind"] == "done"
    assert steps[-1]["interpretation"] == posted
    assert steps[0]["email_id"] == email_id
    assert steps[0]["total_steps"] == len(steps) - 1
    assert steps[0]["source"] == "replay"

    # Order: start, [bank_stripped], fields, lines, category, [missing], [injection], done.
    expected = ["start"]
    if posted["bank_details_stripped"]:
        expected.append("bank_stripped")
    expected += ["field"] * len(posted["fields"]) + ["line"] * len(posted["lines"])
    expected.append("category")
    if posted["missing_fields"] or posted["questions_for_requester"]:
        expected.append("missing")
    if posted["injection_suspected"]:
        expected.append("injection")
    expected.append("done")
    assert kinds(steps) == expected

    fields = [s for s in steps if s["kind"] == "field"]
    assert [s["index"] for s in fields] == list(range(len(posted["fields"])))
    assert [s["field"] for s in fields] == posted["fields"]
    lines = [s for s in steps if s["kind"] == "line"]
    assert [s["index"] for s in lines] == list(range(len(posted["lines"])))
    assert [s["line"] for s in lines] == posted["lines"]
    cat = next(s for s in steps if s["kind"] == "category")
    assert cat["category"] == posted["category"] and cat["method"] == posted["method"]


def test_a_purchase_order_streams_its_lines(client):
    steps, _ = stream(client, "DEMO-03")
    posted = client.post("/emails/DEMO-03/interpret", headers=H("marcus")).json()
    if not posted["lines"]:
        pytest.skip("DEMO-03 has no order lines in the replay cache")
    assert kinds(steps).count("line") == len(posted["lines"])


def test_injection_is_the_last_step_before_done(client):
    steps, _ = stream(client, "DEMO-06")
    assert kinds(steps)[-2:] == ["injection", "done"]


def test_bank_strip_comes_right_after_start_and_no_bank_data_leaks(client):
    steps, text = stream(client, "DEMO-07")
    assert kinds(steps)[:2] == ["start", "bank_stripped"]
    with session_scope() as s:
        body = s.get(m.Email, "DEMO-07").body
    for secret in ["072-123456-7", "DBSSSGSG"]:
        assert secret in body  # the fixture really holds them
        assert secret not in text
    assert "0721234567" not in text.replace("-", "")


def test_finance_and_non_finance_see_identical_steps(client):
    a, _ = stream(client, "DEMO-07", user="weijie")
    b, _ = stream(client, "DEMO-07", user="daniel")
    assert a == b


def test_step_ms_zero_is_immediate(client):
    t = time.perf_counter()
    steps, _ = stream(client, "DEMO-01", step_ms=0)
    assert steps[0]["step_ms"] == 0
    assert time.perf_counter() - t < 2.0  # loose: other test runs may share the machine


def test_default_pacing_takes_about_one_and_a_half_seconds(client):
    t = time.perf_counter()
    steps, _ = stream(client, "DEMO-01", step_ms=None)
    took = time.perf_counter() - t
    # Lower bound only: proves the server really pauses, and can't fail on a busy machine.
    assert 80 <= steps[0]["step_ms"] <= 350
    assert took >= 0.9 * steps[0]["step_ms"] * (len(steps) - 2) / 1000, took
    assert 1.0 <= steps[0]["step_ms"] * (len(steps) - 2) / 1000 <= 2.0  # planned ~1.5 s


def test_step_ms_out_of_range_is_422(client):
    r = client.post(
        "/emails/DEMO-01/interpret/stream", headers=H("marcus"), params={"step_ms": 600}
    )
    assert r.status_code == 422


def test_unknown_email_is_404_before_the_stream(client):
    r = client.post("/emails/NOPE/interpret/stream", headers=H("marcus"))
    assert r.status_code == 404
    assert r.json()["detail"] == "There is no email NOPE."


def test_keyword_fallback_is_reported_as_the_source(client, monkeypatch):
    from ds.interpreter.schemas import Interpretation
    from services.api.routers import emails as email_router

    monkeypatch.setattr(
        email_router,
        "interpret_email",
        lambda email_id, subject, body, sender, **_: Interpretation(
            email_id=email_id,
            category="enquiry",
            confidence=0.4,
            method="keyword_fallback",
            ai_status="offline",
        ),
    )
    steps, _ = stream(client, "DEMO-03")
    assert steps[0]["source"] == "keyword_fallback"
    assert kinds(steps) == ["start", "category", "done"]


def test_live_mode_is_reported_as_live(client, monkeypatch):
    from ds.interpreter.schemas import Interpretation
    from services.api.routers import emails as email_router

    monkeypatch.setenv("LLM_MODE", "live")
    monkeypatch.setattr(
        email_router,
        "interpret_email",
        lambda email_id, subject, body, sender, **_: Interpretation(
            email_id=email_id,
            category="enquiry",
            confidence=0.9,
            method="llm",
            ai_status="ok",
        ),
    )
    steps, _ = stream(client, "DEMO-03")
    assert steps[0]["source"] == "live"

"""Every AI call the demo makes is answered from the replay cache: no keyword or "AI offline"
fallback anywhere. Seeds the demo through the same reset the app's button uses, then asks the
API exactly what the inbox and the duplicate check ask.

A seeded email whose text differs from the fixture by even a trailing newline misses the cache
(the key hashes the exact input), so this test catches the seeder changing what it stores.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from ds.dedup import load_master
from ds.dedup.judge import judge_record
from ds.interpreter.record import DEMO_MDM, FIXTURES
from ds.interpreter.schemas import Interpretation
from services.api import clock, dedup_service
from services.api.db.session import dispose_default
from services.api.formfields import prefill_from_interpretation
from services.api.main import app

OWNS_APP_DB = True  # see tests/conftest.py
AMY = {"X-Acting-User": "amy"}
LABELS = (
    Path(__file__).resolve().parents[1]
    / "data/fixtures/seasonal_trend/ground_truth/email_labels.jsonl"
)


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("FIELD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    mp.setenv("APP_DB_PATH", str(tmp_path_factory.mktemp("demo_ai") / "app.db"))
    mp.setenv("SAP_BASE_URL", "http://127.0.0.1:9/b1s/v2")
    mp.setenv("LLM_MODE", "replay")
    dispose_default()
    c = TestClient(app)
    assert c.post("/admin/reset-demo").status_code == 200
    clock.reset()
    yield c
    clock.reset()
    dispose_default()
    mp.undo()


@pytest.fixture(scope="module")
def reads(client) -> dict[str, dict]:
    emails = client.get("/emails", headers=AMY).json()
    out = {}
    for e in emails:
        r = client.post(f"/emails/{e['email_id']}/interpret", headers=AMY)
        assert r.status_code == 200
        out[e["email_id"]] = r.json()
    return out


def test_every_inbox_email_is_read_by_the_ai(reads):
    fallbacks = sorted(k for k, r in reads.items() if r["method"] != "llm")
    assert len(reads) == 88
    assert fallbacks == [], f"{len(fallbacks)} emails fell back to the keyword rules: {fallbacks}"


def test_inbox_sort_matches_the_evaluation(reads):
    truth = {
        d["email_id"]: d["category"]
        for d in map(json.loads, LABELS.read_text(encoding="utf-8").splitlines())
    }
    wrong = sorted(k for k, r in reads.items() if r["category"] != truth[k])
    assert wrong == []
    assert Counter(r["category"] for r in reads.values()) == Counter(truth.values())


def test_every_demo_duplicate_check_gets_the_ai_second_opinion(client, reads):
    statuses = []
    for eid in DEMO_MDM:
        interp = Interpretation.model_validate(reads[eid])
        if interp.domain not in ("customer", "vendor"):
            continue
        fields, _ = prefill_from_interpretation(interp.domain, interp)
        for entity in ("SPD", "QTS", "QTG"):
            body = {"domain": interp.domain, "entity": entity, "fields": fields}
            r = client.post("/dedup/check", headers=AMY, json=body)
            assert r.status_code == 200
            statuses.append((eid, entity, r.json()["judge"]["status"]))
    assert len(statuses) == 9, statuses
    offline = [s for s in statuses if s[2] not in ("ok", "not_needed")]
    assert offline == [], f"duplicate checks without the AI answer: {offline}"


def test_the_ai_judge_sees_the_same_master_records_as_when_recorded(client):
    """The judge's cache key holds the candidates' fields, recorded from the fixture files. The
    demo's own checks never reach the grey zone, so this guards any check typed live instead."""
    fixture = {r.CardCode: judge_record(r) for r in load_master(FIXTURES)}
    seeded = {r.CardCode: judge_record(r) for r in dedup_service._records()}
    assert seeded.keys() == fixture.keys()
    assert [k for k in fixture if fixture[k] != seeded[k]] == []

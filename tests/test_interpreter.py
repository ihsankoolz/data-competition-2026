"""Email interpreter (M2, D-006) in replay mode: offline, from the committed cache."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ds.interpreter import llm
from ds.interpreter.api import interpret_email, model_input
from ds.interpreter.bank import strip_bank_details
from ds.interpreter.keywords import classify_keywords
from ds.interpreter.prompt import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    TASK,
    EmailReading,
    ExtractedField,
)

ROOT = Path(__file__).resolve().parents[1]
EMAILS = {
    e["email_id"]: e
    for e in (
        json.loads(line)
        for line in (ROOT / "data/fixtures/seasonal_trend/emails.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    )
}


@pytest.fixture(autouse=True)
def _replay(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "replay")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("LLM_CACHE_DIR", raising=False)


def run(eid: str):
    e = EMAILS[eid]
    return interpret_email(eid, e["subject"], e["body"], e["from_address"])


@pytest.mark.parametrize(
    "eid,category,domain",
    [
        ("DEMO-01", "mdm_request", "customer"),
        ("DEMO-03", "purchase_order", None),
        ("DEMO-04", "enquiry", None),
        ("DEMO-05", "follow_up", None),
        ("DEMO-08", "purchase_request", None),
    ],
)
def test_demo_emails_get_the_right_class_from_the_recorded_ai(eid, category, domain):
    it = run(eid)
    assert it.method == "llm" and it.ai_status == "ok", it.ai_message
    assert it.category == category
    assert it.domain == domain


def test_demo01_extracts_the_tax_id_with_its_quote_and_asks_for_the_rest():
    it = run("DEMO-01")
    f = {x.key: x for x in it.fields}
    assert f["tax_id"].value == "0301234567"
    assert "0301234567" in f["tax_id"].source_quote
    assert f["country"].value == "VN"
    assert it.missing_fields == ["address", "contact_email"]
    assert len(it.questions_for_requester) == 2


def test_demo06_injection_is_classified_normally_and_flagged():
    it = run("DEMO-06")
    assert it.category == "mdm_request" and it.domain == "vendor"
    assert it.injection_suspected
    assert it.needs_review
    assert it.bank_details_stripped
    # nothing from the injected text becomes a field
    assert {f.key for f in it.fields} <= {"name", "country", "city", "address", "tax_id"}


def test_demo07_bank_details_never_reach_any_field():
    it = run("DEMO-07")
    assert it.bank_details_stripped
    blob = json.dumps(it.model_dump(mode="json"))
    for secret in ("072-123456-7", "072123456", "DBSSSGSG"):
        assert secret not in blob
    assert "bank_account" not in {f.key for f in it.fields}


def test_a_fabricated_quote_is_dropped(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path))
    subject, body, sender = "New customer", "Please create Klinik Sehat, Jakarta.", "a@b.example"
    reading = EmailReading(
        category="mdm_request",
        confidence=0.9,
        domain="customer",
        fields=[
            ExtractedField(key="name", value="Klinik Sehat", source_quote="Klinik Sehat"),
            ExtractedField(key="tax_id", value="01.234.567.8-901.000", source_quote="NPWP 01.234"),
        ],
        lines=[],
        injection_suspected=False,
    )
    user_input = model_input(subject, body, sender)
    model = llm.resolve_model(TASK)
    key = llm.cache_key(model, PROMPT_VERSION, user_input)
    llm.write_cache(
        TASK, key, llm.make_entry(TASK, model, PROMPT_VERSION, SYSTEM_PROMPT, user_input, reading)
    )
    it = interpret_email("X-1", subject, body, sender)
    assert it.method == "llm"
    assert [f.key for f in it.fields] == ["name"]
    assert it.dropped_fields == ["tax_id"]
    assert "tax_id" in it.missing_fields


def test_unknown_email_falls_back_to_keywords_without_raising(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path))  # empty cache
    it = interpret_email("X-2", "Quotation", "Could you quote 3 units?", "x@y.example")
    assert it.method == "keyword_fallback"
    assert it.ai_status == "offline"
    assert it.category == "enquiry"
    assert it.fields == []


def test_demo06_offline_fallback_still_flags_and_queues_for_review(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path))  # AI offline: empty cache
    it = run("DEMO-06")
    assert it.method == "keyword_fallback"
    assert it.injection_suspected
    assert it.needs_review


def test_bank_details_in_subject_and_body_never_reach_the_model(monkeypatch):
    import ds.interpreter.api as api_mod

    seen: list[str] = []

    def fake_call(task, prompt_version, system, user_input, output_model, *a, **kw):
        seen.append(user_input)
        return llm.LLMResult[output_model](
            status="offline", task=task, model="m", prompt_version=prompt_version, cache_key="k"
        )

    monkeypatch.setattr(api_mod, "call_structured", fake_call)
    subject = "New vendor, Account No 555-123456-9, SWIFT ABCDSGSGXXX"
    body = "Bank: IBAN GB29NWBK60161331926819, acct 9988776655. Please create the vendor."
    it = api_mod.interpret_email("X-4", subject, body, "ap@vendor.example")
    assert it.bank_details_stripped
    assert len(seen) == 1
    for secret in ("555-123456-9", "ABCDSGSGXXX", "GB29NWBK60161331926819", "9988776655"):
        assert secret not in seen[0]


def test_fallback_never_raises_on_empty_input(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path))
    it = interpret_email("X-3", "", "", "")
    assert it.method == "keyword_fallback"
    assert it.needs_review


def test_bank_details_are_stripped_from_the_model_input():
    e = EMAILS["DEMO-07"]
    body, found = strip_bank_details(e["body"])
    text = model_input(e["subject"], body, e["from_address"])
    assert found and "072-123456-7" not in text and "DBSSSGSG" not in text
    assert "grace.teo" not in text  # only the sender's domain is sent


@pytest.mark.parametrize(
    "subject,body,category",
    [
        ("PO 1", "Mohon dikirim 50 box A-DEN-NS1, PO RSCM/2026/118.", "purchase_order"),
        ("Plan", "HKL plans to order 30 kits next month, pls hold stock.", "purchase_request"),
        ("Re: PO", "Following up on our order last week, any ETA?", "follow_up"),
        ("Quote", "Could you quote 2 units of haematology analyser?", "enquiry"),
        ("New vendor", "Please create a new vendor: X Pte Ltd", "mdm_request"),
    ],
)
def test_keyword_baseline_rules(subject, body, category):
    assert classify_keywords(subject, body).category == category


def test_keyword_baseline_ignores_quoted_old_text():
    body = "Any update on this?\n\n> Please deliver 5 boxes, PO 123 attached."
    assert classify_keywords("Re: order", body).category == "follow_up"

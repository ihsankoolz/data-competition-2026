"""Bank details never reach the LLM (rule 5): ds/interpreter/bank.py."""

import json
from pathlib import Path

from ds.interpreter.bank import MASK, strip_bank_details

FIX = Path("data/fixtures/seasonal_trend")


def _emails() -> dict[str, dict]:
    rows = [json.loads(x) for x in (FIX / "emails.jsonl").read_text(encoding="utf-8").splitlines()]
    return {r["email_id"]: r for r in rows if r}


def test_demo_emails_lose_account_and_swift():
    mails = _emails()
    for eid, secrets in {
        "DEMO-07": ["072-123456-7", "DBSSSGSG"],
        "DEMO-06": ["123-456789-001", "HSBCHKHHHKH"],
    }.items():
        text, found = strip_bank_details(mails[eid]["body"])
        assert found, eid
        assert MASK in text
        for s in secrets:
            assert s not in text, (eid, s)


def test_only_labelled_emails_are_touched():
    labels = [
        json.loads(x)
        for x in (FIX / "ground_truth/email_labels.jsonl").read_text(encoding="utf-8").splitlines()
        if x
    ]
    mails = _emails()
    for lab in labels:
        _, found = strip_bank_details(mails[lab["email_id"]]["body"])
        assert found == lab["has_bank_details"], lab["email_id"]


def test_tax_ids_and_po_numbers_survive():
    text = "UEN 201845123K, MST 0301234567, PO RSCM/2026/118, NPWP 01.234.567.8-901.000"
    assert strip_bank_details(text) == (text, False)

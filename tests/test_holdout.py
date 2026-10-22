"""Held-out email set (D-018 item 1): integrity of the committed emails and labels."""

from __future__ import annotations

import json

from ds.forms import missing_keys
from ds.interpreter.holdout.generate import (
    OUT_EMAILS,
    OUT_LABELS,
    check_set,
    exact_quote,
    generate,
)


def _read(path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_every_quote_is_exact_and_addresses_are_fictional():
    emails, labels = _read(OUT_EMAILS), _read(OUT_LABELS)
    assert len(emails) == len(labels) >= 20
    assert [e["email_id"] for e in emails] == [f"HO-{i:02d}" for i in range(1, len(emails) + 1)]
    assert check_set(emails, labels) == []
    assert {lab["category"] for lab in labels} == {
        "purchase_order",
        "purchase_request",
        "enquiry",
        "follow_up",
        "mdm_request",
    }


def test_missing_fields_follow_the_required_fields_config():
    for lab in _read(OUT_LABELS):
        if lab["category"] != "mdm_request":
            assert lab["missing_fields"] == []
            continue
        values = {k: v["value"] for k, v in lab["expected_fields"].items() if k != "lines"}
        assert lab["missing_fields"] == missing_keys(lab["domain"], values)


def test_replay_regenerates_the_committed_files_byte_for_byte():
    emails, labels, _ = generate(mode="replay")
    lines = [json.dumps(r, ensure_ascii=False, sort_keys=True) for r in emails]
    assert OUT_EMAILS.read_text(encoding="utf-8").splitlines() == lines
    lines = [json.dumps(r, ensure_ascii=False, sort_keys=True) for r in labels]
    assert OUT_LABELS.read_text(encoding="utf-8").splitlines() == lines


def test_exact_quote_repairs_whitespace_and_case_only():
    text = "Mohon kirim  HbA1c Reagent Kit\n6 kit"
    assert exact_quote("HbA1c Reagent Kit", text) == "HbA1c Reagent Kit"
    assert exact_quote("hba1c reagent kit 6 kit", text) == "HbA1c Reagent Kit\n6 kit"
    assert exact_quote("HbA1c reagent kits", text) is None

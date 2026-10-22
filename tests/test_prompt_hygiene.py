"""The interpreter prompt must not contain example strings copied from the scored emails
(QA, session 3): every quoted example in the prompt is invented."""

from __future__ import annotations

import re
from pathlib import Path

from ds.interpreter.prompt import SYSTEM_PROMPT

EMAILS = Path(__file__).resolve().parents[1] / "data/fixtures/seasonal_trend/emails.jsonl"

# Generic words that are field values or labels, not copied examples.
ALLOWED = {"true", "false", "PO", "ref"}


def test_no_quoted_prompt_example_occurs_in_the_scored_emails():
    text = EMAILS.read_text(encoding="utf-8")
    quoted = re.findall(r'"([^"]+)"', SYSTEM_PROMPT)
    assert len(quoted) >= 10
    copied = [q for q in quoted if q not in ALLOWED and q in text]
    assert copied == []

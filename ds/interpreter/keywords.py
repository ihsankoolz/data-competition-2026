"""Keyword-rule email classifier (D-006 baseline, D-010 offline fallback). Rules only, no AI.

It is the baseline the LLM must beat, and what the inbox shows when the AI is offline. The
rules look at the subject and the new text of the email (lines quoted with ">" are ignored).
Rules are tried in order; the first match wins.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ds.interpreter.schemas import Category, MdmDomain

_I = re.IGNORECASE


@dataclass(frozen=True)
class KeywordResult:
    category: Category
    confidence: float
    domain: MdmDomain | None = None
    rule: str = "default"


_MDM = re.compile(
    r"create (?:a )?new (?:customer|vendor|item)|new (?:customer|vendor|supplier|item)\b|"
    r"set up (?:a new item|the following customer)|register (?:us|\w+(?: \w+){0,4}) as a "
    r"(?:customer|supplier|vendor)|vendor registration|supplier registration|open an account|"
    r"item code for|cost cent(?:er|re)|membuka akun|customer creation",
    _I,
)
_MDM_DOMAIN = [
    ("cost_center", re.compile(r"cost cent(?:er|re)", _I)),
    ("vendor", re.compile(r"vendor|supplier", _I)),
    ("item", re.compile(r"\bitem\b", _I)),
]
_FOLLOW_UP = re.compile(
    r"any update|following up|follow(?:ing)? up|any eta|still waiting|chasing|reminder|\bbump\b|"
    r"confirm the delivery date for|not received a reply",
    _I,
)
_REQUEST = re.compile(
    r"plans? to order|will need|hold stock|reserve stock|keep allocation|budget has been approved|"
    r"intends? to purchase|internal purchase request|forecast|not an order|tender|no po yet|"
    r"raise the po|po will follow",
    _I,
)
_ORDER = re.compile(
    r"\bPO\b[^\n]*attached|please process|place the following order|confirming our order|"
    r"please deliver|kindly arrange delivery|mohon dikirim|ship to|\bsend\b[^\n]*\bPO\b|"
    r"find attached our PO|^PO \S+",
    _I | re.MULTILINE,
)
_ENQUIRY = re.compile(
    r"quot(?:e|ation)|price|pricing|brochure|lead time|do you have stock|specs?\b|"
    r"request for quotation",
    _I,
)


def new_text(body: str) -> str:
    """The body without lines quoted with '>' (old emails in a reply thread)."""
    return "\n".join(line for line in body.splitlines() if not line.lstrip().startswith(">"))


def classify_keywords(subject: str, body: str) -> KeywordResult:
    text = f"{subject}\n{new_text(body)}"
    if _MDM.search(text):
        domain: MdmDomain = "customer"
        for d, pat in _MDM_DOMAIN:
            if pat.search(text):
                domain = d  # type: ignore[assignment]
                break
        return KeywordResult("mdm_request", 0.7, domain, "mdm")
    for cat, pat in (
        ("follow_up", _FOLLOW_UP),
        ("purchase_request", _REQUEST),
        ("purchase_order", _ORDER),
        ("enquiry", _ENQUIRY),
    ):
        if pat.search(text):
            return KeywordResult(cat, 0.6, None, cat)  # type: ignore[arg-type]
    return KeywordResult("enquiry", 0.3, None, "default")

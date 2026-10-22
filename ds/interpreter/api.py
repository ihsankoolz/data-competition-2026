"""Entry point the API calls (M2, D-006): classify one email and extract fields with quotes.

Pipeline, all deterministic except the one LLM call:
1. strip bank details from subject and body (rule 5) before anything else;
2. one structured call through `llm.call_structured` (replay cache by default, no tools);
3. drop every value whose source_quote is not in the bank-stripped text (`dropped_fields`);
4. `missing_fields` from config (ds.forms.missing_keys) and one plain-English question each;
5. if the AI has no answer, fall back to the keyword rules (`method="keyword_fallback"`).

Nothing in an email can change approvers, bank details or credit terms (rule 7): this module
only returns data for a human to check; routing and publishing are deterministic code elsewhere.
"""

from __future__ import annotations

import re
import unicodedata

from ds.forms import missing_keys
from ds.interpreter.bank import strip_bank_details
from ds.interpreter.keywords import classify_keywords
from ds.interpreter.llm import Mode, call_structured
from ds.interpreter.prompt import PROMPT_VERSION, SYSTEM_PROMPT, TASK, EmailReading
from ds.interpreter.schemas import Interpretation, OrderLine, QuotedValue

REVIEW_BELOW = 0.6

CATALOGUE = {
    "A-DEN-NS1",
    "A-DEN-IGM",
    "A-HBA-1C",
    "A-CRP-QT",
    "A-COV-AG",
    "B-HEM-5P",
    "B-CHE-AUT",
    "B-CEN-REF",
    "B-MIC-BIN",
    "B-BSC-II",
    "C-SVC-ANN",
    "C-SVC-PM",
    "C-LIS-SUB",
    "C-INS-VAL",
    "C-TRN-OPS",
}

# Keys that may be returned for each category / domain. Anything else is dropped.
_ORDER_KEYS = {"customer_name", "po_number", "requested_date"}
_ALLOWED: dict[str, set[str]] = {
    "customer": {"name", "tax_id", "city", "country", "address", "contact_email", "purpose"},
    "vendor": {"name", "tax_id", "city", "country", "address", "contact_email", "purpose"},
    "item": {
        "item_name",
        "is_ivd",
        "selling_countries",
        "sales_unit",
        "unit_price_usd",
        *(f"registration_number_{c}" for c in ("SG", "MY", "ID", "VN", "TH")),
    },
    "cost_center": {"center_name", "entity", "effective_from", "country"},
}

# Deterministic second check for prompt injection (OR-ed with the model's own flag). Generic
# phrasings of the usual attacks, not tuned to any one email.
_INJECTION = re.compile(
    r"\bignore (?:all |any |the )?(?:previous |prior |above |earlier )?instructions\b|"
    r"\bdisregard (?:all |any |the |your )?(?:previous |prior |above )?"
    r"(?:instructions|rules|guidelines)\b|"
    r"\byou are (?:an? |the )?(?:ai|assistant|language model|chatbot)\b|"
    r"\bsystem (?:note|prompt|message|instruction)s? (?:to|for)\b|"
    r"\bapprove (?:this|the) (?:vendor|customer|supplier|request) "
    r"(?:immediately|now|right away)\b|"
    r"\bchange (?:the )?bank (?:account|details)\b",
    re.IGNORECASE,
)

_COUNTRY_NAMES = {
    "SG": "Singapore",
    "MY": "Malaysia",
    "ID": "Indonesia",
    "VN": "Vietnam",
    "TH": "Thailand",
}
_QUESTIONS = {
    "name": "What is the full legal name of the company, as it should appear in SAP?",
    "tax_id": "What is the company's tax ID (for example UEN, SSM, NPWP, MST or Thai tax ID)?",
    "country": "Which country is the company registered in?",
    "address": "What is the company's registered address?",
    "contact_email": "Which email address should we use to contact them (for example "
    "accounts or purchasing)?",
    "item_name": "What is the full name of the new item?",
    "is_ivd": "Is this item an in-vitro diagnostic (IVD) product?",
    "selling_countries": "Which countries will this item be sold in?",
    "center_name": "What should the new cost center be called?",
    "entity": "Which company is the cost center for: SPD, QTS or QTG?",
    "effective_from": "From which date should the cost center be active?",
}


def question_for(key: str) -> str:
    if key.startswith("registration_number_"):
        c = key.rsplit("_", 1)[1]
        return (
            f"What is the product registration number for {_COUNTRY_NAMES.get(c, c)}? "
            "It is needed before we can sell this IVD item there."
        )
    return _QUESTIONS.get(key, f"Please provide the {key.replace('_', ' ')}.")


def _norm(s: str) -> str:
    """NFC, case-folded, whitespace collapsed: the comparison form for source quotes."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s)).strip().casefold()


def quote_ok(quote: str, haystack_norm: str) -> bool:
    q = _norm(quote or "")
    return bool(q) and q in haystack_norm


def model_input(subject: str, body: str, from_address: str) -> str:
    """The exact text sent to the model (and hashed into the cache key). Already bank-stripped."""
    domain = from_address.rsplit("@", 1)[-1] if "@" in from_address else ""
    return f"<email>\nFrom domain: {domain}\nSubject: {subject}\n\n{body}\n</email>"


def _convert(key: str, value: str) -> str | float | bool | list[str] | None:
    v = value.strip()
    if not v:
        return None
    if key == "is_ivd":
        return v.lower() in ("true", "yes", "ivd", "1")
    if key == "selling_countries":
        codes = [c.strip().upper() for c in re.split(r"[,;/ ]+", v) if c.strip()]
        return codes or None
    if key == "unit_price_usd":
        m = re.search(r"\d+(?:[.,]\d+)?", v)
        return float(m.group().replace(",", ".")) if m else None
    if key == "country":
        return v.upper() if len(v) == 2 else v
    return v


def _fallback(
    email_id: str, subject: str, body: str, stripped: bool, status: str, message: str | None
) -> Interpretation:
    kw = classify_keywords(subject, body)
    injection = bool(_INJECTION.search(f"{subject}\n{body}"))
    return Interpretation(
        email_id=email_id,
        category=kw.category,
        confidence=kw.confidence,
        domain=kw.domain,
        bank_details_stripped=stripped,
        injection_suspected=injection,
        needs_review=kw.confidence < REVIEW_BELOW or injection,
        method="keyword_fallback",
        ai_status="error" if status == "error" else "offline",
        ai_message=message or "AI offline: showing the keyword rules' best guess",
        prompt_version=PROMPT_VERSION,
    )


def interpret_email(
    email_id: str,
    subject: str,
    body: str,
    from_address: str,
    *,
    mode: str | None = None,
) -> Interpretation:
    """Classify one email and extract fields with source quotes.

    Never raises for AI problems: when the replay cache has no answer it returns the keyword
    baseline with `method="keyword_fallback"` and `ai_status="offline"`. Bank details are
    stripped before any LLM call. The returned object is safe to show to any role.
    """
    subject = subject or ""
    body = body or ""
    from_address = from_address or ""
    subj_s, found_s = strip_bank_details(subject)
    body_s, found_b = strip_bank_details(body)
    stripped = found_s or found_b

    md: Mode | None = mode if mode in ("replay", "record", "live") else None  # type: ignore[assignment]
    try:
        res = call_structured(
            TASK,
            PROMPT_VERSION,
            SYSTEM_PROMPT,
            model_input(subj_s, body_s, from_address),
            EmailReading,
            max_tokens=2048,
            mode=md,
        )
    except Exception as exc:  # call_structured never raises; belt and braces for the demo
        return _fallback(email_id, subj_s, body_s, stripped, "error", type(exc).__name__)
    if not res.ok or res.output is None:
        return _fallback(email_id, subj_s, body_s, stripped, res.status, res.message)
    return _from_reading(email_id, res.output, subj_s, body_s, from_address, stripped)


def _from_reading(
    email_id: str,
    r: EmailReading,
    subject: str,
    body: str,
    from_address: str,
    stripped: bool,
) -> Interpretation:
    hay = _norm(f"{subject}\n{body}\n{from_address}")
    domain = r.domain if r.category == "mdm_request" else None
    if r.category == "mdm_request" and domain is None:
        domain = classify_keywords(subject, body).domain or "customer"
    allowed = _ALLOWED[domain] if domain else _ORDER_KEYS

    fields: list[QuotedValue] = []
    dropped: list[str] = []
    seen: set[str] = set()
    for f in r.fields:
        if f.key not in allowed or f.key in seen:
            continue
        value = _convert(f.key, f.value)
        if value is None:
            continue
        if not quote_ok(f.source_quote, hay):
            dropped.append(f.key)
            continue
        seen.add(f.key)
        fields.append(QuotedValue(key=f.key, value=value, source_quote=f.source_quote))

    lines: list[OrderLine] = []
    if r.category in ("purchase_order", "purchase_request", "enquiry"):
        for ln in r.lines:
            if not quote_ok(ln.source_quote, hay):
                dropped.append("lines")
                continue
            code = (ln.item_code or "").strip().upper() or None
            lines.append(
                OrderLine(
                    item_code=code if code in CATALOGUE else None,
                    product_text=ln.product_text,
                    qty=ln.qty,
                    source_quote=ln.source_quote,
                )
            )

    missing: list[str] = []
    if domain:
        missing = missing_keys(domain, {f.key: f.value for f in fields})
    confidence = min(1.0, max(0.0, float(r.confidence)))
    injection = r.injection_suspected or bool(_INJECTION.search(f"{subject}\n{body}"))
    return Interpretation(
        email_id=email_id,
        category=r.category,
        confidence=confidence,
        domain=domain,
        fields=fields,
        lines=lines,
        missing_fields=missing,
        questions_for_requester=[question_for(k) for k in missing],
        dropped_fields=sorted(set(dropped)),
        bank_details_stripped=stripped,
        injection_suspected=injection,
        needs_review=confidence < REVIEW_BELOW or injection,
        method="llm",
        ai_status="ok",
        prompt_version=PROMPT_VERSION,
    )

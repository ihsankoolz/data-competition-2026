"""Generate the held-out email set (D-018 item 1) with the judge-tier model, through llm.py.

Protocol (integrity first):
- The interpreter prompt, schema, keyword rules and required-fields config are frozen before this
  runs (tests/test_prompt_frozen.py).
- The writer model gets only `style_brief.md` (written without opening the generator's email
  templates or the fixture emails) plus a short per-class list of slots below.
- One call per class through `ds.interpreter.llm.call_structured` (task `holdout_gen`, prompt
  version `holdout_gen_v1`), so the set replays offline from data/fixtures/llm_cache/.
- Post-processing is deterministic and never looks at the interpreter: every source_quote must be
  an exact substring of the email (whitespace/case-only slips are repaired to the exact span,
  anything else is dropped), item codes outside the catalogue become null, `missing_fields` is
  recomputed from the kept fields with `ds.forms.missing_keys` (the writer's own list is kept as
  `writer_missing_fields` so a human can see disagreements).
- The emails and labels are committed BEFORE the interpreter reads them.

Run: `LLM_MODE=record uv run --env-file .env python -m ds.interpreter.holdout.generate`
(`--dry-run` prints the cost estimate only). Re-running in replay mode rewrites identical files.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ds.forms import missing_keys
from ds.interpreter import llm
from ds.interpreter.bank import strip_bank_details

ROOT = Path(__file__).resolve().parents[3]
BRIEF = Path(__file__).with_name("style_brief.md")
OUT_EMAILS = ROOT / "data" / "fixtures" / "holdout_emails.jsonl"
OUT_LABELS = ROOT / "data" / "fixtures" / "holdout_labels.jsonl"

TASK = "holdout_gen"
PROMPT_VERSION = "holdout_gen_v1"
MAX_TOKENS = 16000
# Claude Sonnet 5.5 list prices (USD per million tokens) and rough per-call token assumptions.
PRICE_IN, PRICE_OUT = 2.0, 10.0
EST_IN_TOK, EST_OUT_TOK = 4500, 9000
BUDGET_USD = 1.0
# The writer is the judge-tier model (llm.py maps only `dedup_judge` to that tier).
WRITER_MODEL = os.environ.get("LLM_MODEL_JUDGE") or "claude-sonnet-5-5"

CATALOGUE = {
    "A-DEN-NS1", "A-DEN-IGM", "A-HBA-1C", "A-CRP-QT", "A-COV-AG",
    "B-HEM-5P", "B-CHE-AUT", "B-CEN-REF", "B-MIC-BIN", "B-BSC-II",
    "C-SVC-ANN", "C-SVC-PM", "C-LIS-SUB", "C-INS-VAL", "C-TRN-OPS",
}  # fmt: skip

Category = Literal["purchase_order", "purchase_request", "enquiry", "follow_up", "mdm_request"]

# One batch per class. Each slot fixes language and the twist; the writer invents the rest.
SLOTS: dict[Category, list[str]] = {
    "purchase_order": [
        "Bahasa Indonesia, terse, from the lab of a private hospital in Surabaya; PO number in "
        "the body; a calendar delivery date; one product line.",
        "English. A Lives Group sales rep in Singapore forwards a customer's email to the sales "
        "inbox with a one-line note on top ('pls process'); the customer's PO (two lines, PO "
        "number, attachment named like a PO PDF) is in the forwarded part.",
        "Vietnamese typed WITHOUT diacritics, from a district hospital in Can Tho; PO number; "
        "quantity in boxes ('hop'); no delivery date.",
        "Thai mixed with English (Thai script plus English product names), formal, from a "
        "private lab in Chiang Mai; orders a preventive maintenance visit; has a PO number.",
        "English, rambling, from procurement at a Malaysian hospital: accepts an earlier "
        "quotation and says please proceed; mentions budget approval and an earlier 'plan' in "
        "the quoted history, but this message is a firm order with a PO number.",
    ],
    "purchase_request": [
        "English, from a Singapore polyclinic lab: plans to order next month and asks to "
        "reserve stock; no PO.",
        "Malay mixed with English, casual phone style, from a clinic in Kuala Lumpur: wants "
        "roughly 40 boxes next quarter, can you hold stock; no PO.",
        "Vietnamese WITH diacritics, from a provincial hospital planning next year's tender "
        "quantities for two reagents.",
        "Bahasa Indonesia, from hospital purchasing: an internal purchase requisition number "
        "(not a PO) and quantities; says the PO will follow after the director signs. Close "
        "call between order and plan, but no confirmed order yet.",
        "English, terse, from a Thai hospital: budget approved for one centrifuge in Q1, PO "
        "will come in January, please keep the price.",
    ],
    "enquiry": [
        "English, from an Indonesian university lab: price and lead time for a biosafety "
        "cabinet and two microscopes.",
        "Mostly Thai script with English product names: is the HbA1c kit in stock and what is "
        "the price.",
        "Vietnamese WITHOUT diacritics: asks about a demo and pricing for the lab information "
        "system subscription.",
        "English, rambling, from a Singapore private lab: wants a quotation for operator "
        "training plus installation; uses the word 'order' ('before we order') but nothing is "
        "committed.",
        "Malay (Bahasa Melayu), from a hospital in Penang: asks whether dengue rapid tests are "
        "in stock and whether the product is registered in Malaysia.",
    ],
    "follow_up": [
        "English reply in an existing thread ('Re:'), chasing delivery of an earlier order; "
        "the earlier PO email is quoted below with '>' lines and mentions the PO number.",
        "Bahasa Indonesia, chasing a quotation requested two weeks ago; the original request "
        "is forwarded underneath.",
        "Vietnamese WITH diacritics, chasing an engineer visit for a broken analyser reported "
        "last week.",
        "Internal: a Lives Group sales rep in Malaysia chases the MDM team about a customer "
        "account request sent last week because they cannot book an order yet; the earlier "
        "request is quoted. This is a follow-up, not a new master-data request.",
    ],
    "mdm_request": [
        "domain customer. English, internal from a QTS sales rep in Vietnam: please create a "
        "new customer, a hospital in Da Nang, with its tax code (MST) and address; no contact "
        "email given.",
        "domain customer. Bahasa Indonesia, from an outside clinic asking to be registered as "
        "a customer so they can buy test kits; gives its NPWP and a contact email; no address.",
        "domain vendor. English, from Lives Group procurement: onboard a new logistics supplier "
        "in Malaysia; gives SSM number, address and contact email; says bank details will come "
        "separately on the secure form.",
        "domain item. English, from an SPD product manager: create a new IVD rapid test item "
        "(not in the catalogue) to sell in Singapore, Malaysia and Thailand; gives only the "
        "Singapore registration number.",
        "domain cost_center. English, short, from finance: new cost center for the QTG Vietnam "
        "service team, effective 1 November 2026.",
    ],
}


class GenField(BaseModel):
    key: str
    value: str
    source_quote: str


class GenLine(BaseModel):
    item_code: str | None = None
    product_text: str
    qty: float | None = None
    source_quote: str


class GenEmail(BaseModel):
    slot: int = Field(description="1-based number of the slot this email fills")
    from_name: str
    from_address: str
    to: str
    subject: str
    body: str
    attachments: list[str] = []
    category: Category
    domain: Literal["customer", "vendor", "item", "cost_center"] | None = None
    expected_fields: list[GenField] = []
    lines: list[GenLine] = []
    missing_fields: list[str] = []
    language: str
    messiness: list[str] = []
    gist: str


class GenBatch(BaseModel):
    emails: list[GenEmail]


def user_input(category: Category) -> str:
    slots = "\n".join(f"{i}. {s}" for i, s in enumerate(SLOTS[category], 1))
    return (
        f"Write {len(SLOTS[category])} emails of category `{category}`, one per slot below, "
        "each with its label as described in the brief. Every email must be different in "
        "sender, organisation, products and wording.\n\n"
        f"Slots:\n{slots}"
    )


def estimate() -> float:
    n = len(SLOTS)
    return n * (EST_IN_TOK * PRICE_IN + EST_OUT_TOK * PRICE_OUT) / 1e6


def worst_case() -> float:
    return len(SLOTS) * (EST_IN_TOK * PRICE_IN + MAX_TOKENS * PRICE_OUT) / 1e6


# ---------------------------------------------------------------- deterministic post-processing


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s)).strip().casefold()


def exact_quote(quote: str, text: str) -> str | None:
    """The quote itself if it is an exact substring; else the exact span of `text` that matches
    it up to whitespace runs and case (NFC); else None."""
    q = (quote or "").strip()
    if not q:
        return None
    if q in text:
        return q
    parts = [re.escape(p) for p in unicodedata.normalize("NFC", q).split()]
    m = re.search(r"\s+".join(parts), unicodedata.normalize("NFC", text), re.IGNORECASE)
    if m and m.group(0) in text:
        return m.group(0)
    return None


def _convert(key: str, value: str):
    v = value.strip()
    if key == "is_ivd":
        return v.lower() in ("true", "yes", "1", "ivd")
    if key == "selling_countries":
        return [c.strip().upper() for c in re.split(r"[,;/ ]+", v) if c.strip()]
    if key == "unit_price_usd":
        m = re.search(r"\d+(?:\.\d+)?", v.replace(",", ""))
        return float(m.group()) if m else v
    return v


def build(batches: dict[str, GenBatch]) -> tuple[list[dict], list[dict], list[str]]:
    """-> (emails, labels, notes). Deterministic: same batches, same output."""
    emails, labels, notes = [], [], []
    n = 0
    for category in SLOTS:  # fixed class order
        batch = batches[category]
        for g in sorted(batch.emails, key=lambda e: e.slot):
            n += 1
            eid = f"HO-{n:02d}"
            text = f"{g.subject}\n{g.body}"
            if strip_bank_details(g.body)[1] or strip_bank_details(g.subject)[1]:
                # kept as is: the brief forbids bank details, so this is the stripper erring on
                # the safe side (the interpreter will mask that span before its AI call)
                notes.append(f"{eid}: bank-detail pattern matched (kept; masked before the AI)")
            fields: dict[str, dict] = {}
            for f in g.expected_fields:
                q = exact_quote(f.source_quote, text)
                if q is None:
                    notes.append(f"{eid}: dropped field {f.key} (quote not in email)")
                    continue
                if q != f.source_quote:
                    notes.append(f"{eid}: repaired quote for {f.key}")
                if f.key in fields:
                    continue
                fields[f.key] = {"value": _convert(f.key, f.value), "source_quote": q}
            lines = []
            for ln in g.lines:
                q = exact_quote(ln.source_quote, text)
                if q is None:
                    notes.append(f"{eid}: dropped a line (quote not in email)")
                    continue
                code = (ln.item_code or "").strip().upper() or None
                if code is not None and code not in CATALOGUE:
                    notes.append(f"{eid}: item code {code} not in catalogue -> null")
                    code = None
                lines.append({"item_code": code, "qty": ln.qty, "source_quote": q})
            expected: dict = dict(fields)
            if lines:
                expected["lines"] = lines
            domain = g.domain if g.category == "mdm_request" else None
            values = {k: v["value"] for k, v in fields.items()}
            missing = missing_keys(domain, values) if domain else []
            writer_missing = list(g.missing_fields) if domain else []
            if domain and set(missing) != set(writer_missing):
                notes.append(f"{eid}: writer said missing {writer_missing}, rules say {missing}")
            minute = 7 + 11 * n % 50  # deterministic, never on the hour
            emails.append(
                {
                    "email_id": eid,
                    "received_at": f"2026-10-{12 + (n - 1) // 6:02d}T{9 + (n - 1) % 6:02d}:"
                    f"{minute:02d}:00+08:00",
                    "from_name": g.from_name,
                    "from_address": g.from_address,
                    "to": g.to,
                    "subject": g.subject,
                    "body": g.body,
                    "attachments": list(g.attachments),
                    "thread_id": f"HT-{n:02d}",
                }
            )
            labels.append(
                {
                    "email_id": eid,
                    "category": g.category,
                    "domain": domain,
                    "expected_fields": expected,
                    "missing_fields": missing,
                    "writer_missing_fields": writer_missing,
                    "injection_suspected": False,
                    "has_bank_details": False,
                    "language": g.language,
                    "messiness": list(g.messiness),
                    "gist": g.gist,
                    "slot": SLOTS[category][g.slot - 1]
                    if 0 < g.slot <= len(SLOTS[category])
                    else None,
                    "writer_model": WRITER_MODEL,
                    "writer_prompt_version": PROMPT_VERSION,
                }
            )
    return emails, labels, notes


def check_set(emails: list[dict], labels: list[dict]) -> list[str]:
    """Hard checks: every quote exact, .example addresses only, ids aligned."""
    problems = []
    for e, lab in zip(emails, labels, strict=True):
        if e["email_id"] != lab["email_id"]:
            problems.append(f"{e['email_id']}: id mismatch")
        text = f"{e['subject']}\n{e['body']}"
        for k, v in lab["expected_fields"].items():
            items = v if k == "lines" else [v]
            for it in items:
                if it["source_quote"] not in text:
                    problems.append(f"{e['email_id']}: quote for {k} not exact")
        for addr in re.findall(r"[\w.+-]+@[\w.-]+", f"{e['from_address']} {e['to']} {text}"):
            if not addr.rstrip(".").endswith(".example"):
                problems.append(f"{e['email_id']}: non-.example address {addr}")
    return problems


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


def generate(mode: str | None = None) -> tuple[list[dict], list[dict], list[str]]:
    system = BRIEF.read_text(encoding="utf-8")
    batches: dict[str, GenBatch] = {}
    for category in SLOTS:
        res = llm.call_structured(
            TASK, PROMPT_VERSION, system, user_input(category), GenBatch,
            model=WRITER_MODEL, max_tokens=MAX_TOKENS, mode=mode,  # type: ignore[arg-type]
        )  # fmt: skip
        if not res.ok or res.output is None:
            raise SystemExit(f"{category}: {res.status} {res.message}")
        print(f"  {category}: {len(res.output.emails)} emails (cache: {res.from_cache})")
        batches[category] = res.output
    return build(batches)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    model = WRITER_MODEL
    print(
        f"{len(SLOTS)} calls to {model} ({PROMPT_VERSION}), mode {llm.llm_mode()}. "
        f"Estimate ~US${estimate():.2f}, worst case US${worst_case():.2f} "
        f"(at ${PRICE_IN}/${PRICE_OUT} per M tokens; cached calls cost nothing)."
    )
    if worst_case() > BUDGET_USD:
        print(f"worst case over the US${BUDGET_USD} budget: stopping")
        return 1
    if args.dry_run:
        return 0
    emails, labels, notes = generate()
    for n in notes:
        print("  note:", n)
    problems = check_set(emails, labels)
    if problems:
        print("\n".join(problems))
        return 1
    write_jsonl(OUT_EMAILS, emails)
    write_jsonl(OUT_LABELS, labels)
    print(f"wrote {len(emails)} emails -> {OUT_EMAILS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

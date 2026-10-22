"""Field validation for request forms (D-018 item 3). Pure code, no database, no wall clock.

One checker, used by `POST /requests/{id}/validate`, `RequestDetail.issues`, submit (422) and the
publish-time expiry re-check. It reads the same `config/forms/*.schema.json` and
`config/required_fields.yaml` as the form, so a rule is changed in one place.

Checks, in order: value type, allowed choices, length limits (the SAP limits live in the
schemas), email and date formats, the country's tax-ID format (D-003), required fields per
domain x country, and item registrations (number, expiry after the simulated "today", issue
date before expiry).

Messages are plain English and never repeat what was typed: bank values in particular must not
appear anywhere (domain rule 5).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from typing import Any

from fastapi import HTTPException

from ds.forms import (
    FORM_DOMAINS,
    country_names,
    home_countries,
    load_form_schema,
    regulated_countries,
)
from services.api.bankfields import BANK_KEY
from services.api.formfields import missing_form_fields
from services.api.schemas import FieldIssue

COUNTRY_NAME = {
    "SG": "Singapore",
    "MY": "Malaysia",
    "ID": "Indonesia",
    "VN": "Vietnam",
    "TH": "Thailand",
}
TAX_NAME = {"SG": "UEN", "MY": "SSM no.", "ID": "NPWP", "VN": "MST", "TH": "TIN"}

# (pattern applied to the trimmed value, plain-English message). Synthetic formats: D-003 and
# `ds/generator/master.py::make_tax_id`; `tests/test_validation.py` checks every fixture ID.
TAX_ID_RULES: dict[str, tuple[re.Pattern[str], str]] = {
    "SG": (
        # 9 or 10 characters ending in a letter (company: 4-digit year + 5 digits + letter;
        # business: 8 digits + letter), or the T/S/R + year + entity-type form.
        re.compile(r"(\d{8,9}[A-Z]|[TSR]\d{2}[A-Z]{2}\d{4}[A-Z])"),
        "A Singapore UEN has 9 or 10 characters and ends in a capital letter, like 201912345K.",
    ),
    "MY": (
        re.compile(r"\d{12}"),
        "A Malaysian SSM registration number has 12 digits, like 202001012345.",
    ),
    "ID": (
        # 15 digits; the dots and the dash are optional and only valid in the usual places.
        re.compile(r"\d{2}\.?\d{3}\.?\d{3}\.?\d-?\d{3}\.?\d{3}"),
        "An Indonesian NPWP has 15 digits (dots and the dash are optional), "
        "like 01.234.567.8-901.000.",
    ),
    "VN": (
        re.compile(r"\d{10}(-\d{3})?"),  # a branch adds -NNN
        "A Vietnamese tax ID (MST) has 10 digits, like 0301234567.",
    ),
    "TH": (
        re.compile(r"\d{13}"),
        "A Thai tax ID (TIN) has 13 digits, like 0105556123456.",
    ),
}
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

# Cost centres have no form schema: SAP's own limits (`ProfitCenter` in the mock, D-004).
COST_CENTER_RULES = {"CenterName": ("Cost center name", 30), "EffectiveFrom": ("Effective from", 0)}


# SAP codes are never shown to a person: yes/no flags read as plain words.
PLAIN_WORDS = {"tYES": "Yes", "tNO": "No"}


def _plain_choices(choices: list[Any]) -> str:
    return ", ".join(PLAIN_WORDS.get(str(c), str(c)) for c in choices)


def _trim(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return [_trim(v) for v in value]
    if isinstance(value, dict):
        return {k: _trim(v) for k, v in value.items()}
    return value


def clean_tax_id(country: str | None, value: str) -> str:
    """The tax ID as it is stored: stray spaces always go; per country the separators that carry
    no meaning go too (MY and TH: spaces and dashes; ID: spaces; SG: upper case)."""
    text = value.strip()
    if country in ("MY", "TH"):
        return re.sub(r"[\s-]", "", text)
    if country == "ID":
        return re.sub(r"\s", "", text)
    if country == "SG":
        return text.upper()
    return text


def normalise_fields(fields: Mapping[str, Any], country: str | None) -> dict[str, Any]:
    """What gets stored: every text trimmed (also inside registration and bank rows), and the
    tax ID cleaned for its country. The validator then checks exactly what is stored."""
    out = {k: _trim(v) for k, v in fields.items()}
    tax = out.get("FederalTaxID")
    if isinstance(tax, str) and tax:
        out["FederalTaxID"] = clean_tax_id(country, tax)
    return out


def _empty(v: Any) -> bool:
    return v is None or (isinstance(v, (str, list, dict)) and len(v) == 0)


def _parse_date(v: Any) -> date | None:
    if not isinstance(v, str) or not ISO_DATE.fullmatch(v.strip()):
        return None
    try:
        return date.fromisoformat(v.strip())
    except ValueError:
        return None


def _nice(d: date) -> str:
    return f"{d.day} {d.strftime('%b %Y')}"


def _is_number(v: Any, *, whole: bool) -> bool:
    if isinstance(v, bool):
        return False
    return isinstance(v, int) if whole else isinstance(v, (int, float))


def _country_message(label: str, value: str, allowed: list[Any]) -> str:
    names = country_names()
    if set(allowed) != set(home_countries()):  # the full ISO list (vendors, bank countries)
        return f"{label} must be a two-letter country code from the list, like DE or US."
    place = names.get(value.upper())
    where = [COUNTRY_NAME.get(str(c), str(c)) for c in allowed]
    return (
        f"Customers can only be in {', '.join(where[:-1])} or {where[-1]}."
        + (f" {place} is not one of them." if place else "")
        + " A company in another country can be set up as a vendor instead."
    )


def _check_value(
    field: str, label: str, spec: Mapping[str, Any], value: Any, country: str | None = None
) -> list[FieldIssue]:
    """Type, choices, length, bounds and format for one non-empty value."""

    def issue(kind: str, message: str) -> list[FieldIssue]:
        return [FieldIssue(field=field, label=label, message=message, kind=kind)]  # type: ignore[arg-type]

    kind = spec.get("type")
    if kind == "string":
        if not isinstance(value, str):
            return issue("format", f"{label} must be text.")
        text = value.strip()
        if "enum" in spec and text not in spec["enum"]:
            if field.rsplit(".", 1)[-1] == "Country":  # also BPBankAccounts.N.Country
                return issue("not_allowed", _country_message(label, text, spec["enum"]))
            return issue("not_allowed", f"{label} must be one of: {_plain_choices(spec['enum'])}.")
        limit = spec.get("maxLength")
        if limit and len(text) > limit:
            return issue("too_long", f"{label} can be at most {limit} characters long.")
        if spec.get("format") == "email" and not EMAIL.fullmatch(text):
            return issue("format", f"{label} must be an email address, like name@company.com.")
        if spec.get("format") == "date" and _parse_date(text) is None:
            return issue(
                "format", f"{label} must be a date written as YYYY-MM-DD, like 2027-03-31."
            )
        if field == "FederalTaxID" and country in TAX_ID_RULES:
            pattern, message = TAX_ID_RULES[country]
            if not pattern.fullmatch(text):
                return issue("format", message)
    elif kind in ("integer", "number"):
        if not _is_number(value, whole=kind == "integer"):
            what = "a whole number" if kind == "integer" else "a number"
            return issue("format", f"{label} must be {what}.")
        choices = [o["const"] for o in spec.get("oneOf", []) if "const" in o]
        if choices and value not in choices:
            names = ", ".join(str(o.get("title", o["const"])) for o in spec["oneOf"])
            return issue("not_allowed", f"{label} must be one of: {names}.")
        if "minimum" in spec and value < spec["minimum"]:
            return issue("format", f"{label} cannot be below {spec['minimum']}.")
    elif kind == "array":
        if not isinstance(value, list):
            return issue("format", f"{label} must be a list.")
        allowed = spec.get("items", {}).get("enum")
        if allowed and any(v not in allowed for v in value):
            return issue("not_allowed", f"{label} can only include: {_plain_choices(allowed)}.")
        if spec.get("uniqueItems") and len(set(map(str, value))) != len(value):
            return issue("format", f"{label} lists the same value twice.")
    return []


def _label(domain: str, field: str, country: str | None) -> str:
    if field == "FederalTaxID" and country in TAX_NAME:
        return f"Tax ID ({TAX_NAME[country]})"
    if domain in FORM_DOMAINS:
        return str(load_form_schema(domain)["properties"].get(field, {}).get("title", field))  # type: ignore[arg-type]
    return {"CenterName": "Cost center name", "EffectiveFrom": "Effective from"}.get(field, field)


def _issue(field: str, label: str, kind: str, message: str) -> FieldIssue:
    return FieldIssue(field=field, label=label, kind=kind, message=message)  # type: ignore[arg-type]


def _bank_issues(rows: Any) -> list[FieldIssue]:
    """Required parts and lengths of each bank row. Says which part, never what was typed."""
    spec = load_form_schema("vendor")["properties"][BANK_KEY]
    props, required = spec["items"]["properties"], spec["items"]["required"]
    if not isinstance(rows, list):
        return [_issue(BANK_KEY, "Bank account", "format", "Bank account must be a list.")]
    out: list[FieldIssue] = []
    if len(rows) > spec["maxItems"]:
        message = f"Add at most {spec['maxItems']} bank accounts."
        out.append(_issue(BANK_KEY, "Bank account", "not_allowed", message))
    for i, row in enumerate(rows):
        row = row if isinstance(row, dict) else {}
        for key in [*required, *sorted(set(props) - set(required))]:
            field, label = f"{BANK_KEY}.{i}.{key}", props[key]["title"]
            if not _empty(row.get(key)):
                out += _check_value(field, label, props[key], row[key])
            elif key in required:
                out.append(_issue(field, label, "missing", f"{label} is required."))
    return out


def registration_issues(fields: Mapping[str, Any], today: date) -> list[FieldIssue]:
    """Registration rows of an item: number, expiry after `today`, issue before expiry.

    For an IVD item the regulated selling countries must have a number and an expiry date, and
    an expiry that is not after `today` blocks that country. Rows for other countries are only
    checked for format. `today` is the simulated clock's date.
    """
    if not isinstance(fields.get("registrations"), list):
        return []
    props = load_form_schema("item")["properties"]["registrations"]["items"]["properties"]
    is_ivd = fields.get("U_IVD") == "tYES"
    selling = fields.get("selling_countries")
    selling = [str(c) for c in selling] if isinstance(selling, list) else []
    regulated = set(regulated_countries()) & set(selling) if is_ivd else set()
    rows = {r.get("country"): r for r in fields["registrations"] if isinstance(r, dict)}
    out: list[FieldIssue] = []
    for cc in sorted(set(rows) | regulated, key=lambda c: str(c)):
        name = COUNTRY_NAME.get(str(cc), str(cc))
        row = rows.get(cc) or {}
        for sub in ("reg_no", "risk_class", "issue_date", "expiry_date"):
            if sub in props and not _empty(row.get(sub)):
                title = "Registration number" if sub == "reg_no" else props[sub]["title"]
                label = f"{title} ({name})"
                out += _check_value(f"registrations.{cc}.{sub}", label, props[sub], row[sub])
        expiry_label = f"Expiry date ({name})"
        expiry = _parse_date(row.get("expiry_date"))
        if cc in regulated and _empty(row.get("expiry_date")):
            out.append(FieldIssue(
                field=f"registrations.{cc}.expiry_date", label=expiry_label, kind="missing",
                message=f"Enter the expiry date of the {name} registration.",
            ))  # fmt: skip
        elif cc in regulated and expiry is not None and expiry <= today:
            fix = "Renew it or remove " + name + " from the selling countries."
            when = (
                f"expired on {_nice(expiry)}"
                if expiry < today
                else f"expires today ({_nice(expiry)})"
            )
            out.append(FieldIssue(
                field=f"registrations.{cc}.expiry_date", label=expiry_label, kind="expired",
                message=f"The {name} registration {when}. {fix}",
            ))  # fmt: skip
        issued = _parse_date(row.get("issue_date"))
        if issued and expiry and issued >= expiry:
            out.append(FieldIssue(
                field=f"registrations.{cc}.issue_date", label=f"Issue date ({name})",
                kind="date_order",
                message=f"The {name} issue date must be before its expiry date.",
            ))  # fmt: skip
    return out


def validate_fields(
    domain: str, country: str, fields: Mapping[str, Any], today: date
) -> list[FieldIssue]:
    """All problems with a request's current fields (plain values, i.e. bank unsealed)."""
    out: list[FieldIssue] = []
    tax_country = str(fields.get("Country") or country) if domain != "item" else None
    if domain in FORM_DOMAINS:
        props = load_form_schema(domain)["properties"]  # type: ignore[arg-type]
        for name, spec in props.items():
            value = fields.get(name)
            if _empty(value) or name in ("registrations", BANK_KEY):
                continue
            out += _check_value(name, _label(domain, name, tax_country), spec, value, tax_country)
    else:
        for name, (label, limit) in COST_CENTER_RULES.items():
            value = fields.get(name)
            if _empty(value):
                continue
            if name == "EffectiveFrom":
                out += _check_value(name, label, {"type": "string", "format": "date"}, value)
            else:
                out += _check_value(name, label, {"type": "string", "maxLength": limit}, value)

    for name in missing_form_fields(domain, country, fields):
        if name.startswith("registrations["):
            cc = name[len("registrations[") : -1]
            label = f"Registration number ({COUNTRY_NAME.get(cc, cc)})"
            field = f"registrations.{cc}.reg_no"
            message = f"Enter the registration number for {COUNTRY_NAME.get(cc, cc)}."
        elif name == BANK_KEY:
            label, field, message = "Bank account", BANK_KEY, "Bank account details are required."
        else:
            label, field = _label(domain, name, tax_country), name
            message = f"{label} is required."
        out.append(FieldIssue(field=field, label=label, message=message, kind="missing"))

    if domain == "vendor" and not _empty(fields.get(BANK_KEY)):
        out += _bank_issues(fields[BANK_KEY])
    if domain == "item":
        out += registration_issues(fields, today)
    return out


def submit_sentence(issues: list[FieldIssue]) -> str:
    """The one plain sentence for a blocked submit (`detail`)."""
    if all(i.kind == "missing" for i in issues):
        return (
            "Some required details are still missing: "
            + ", ".join(i.label for i in issues)
            + ". Fill them in and submit again."
        )
    shown = "; ".join(i.message.rstrip(".") for i in issues[:3])
    more = f"; and {len(issues) - 3} more" if len(issues) > 3 else ""
    return f"Some details need fixing before this can be submitted: {shown}{more}."


def expired_sentence(issues: list[FieldIssue]) -> str:
    """The plain error when an approved item can no longer be published."""
    shown = " ".join(i.message for i in issues)
    return f"This item can't be published: {shown} Ask the requestor to fix it."


class ValidationFailed(HTTPException):
    """A 422 whose body is {"detail": "<one sentence>", "issues": [FieldIssue, ...]}
    (see the handler in `services/api/main.py`)."""

    def __init__(self, detail: str, issues: list[FieldIssue], status_code: int = 422) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.issues = issues

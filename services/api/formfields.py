"""Form fields (SAP names) <-> interpreter extract keys, missing fields, e-mail prefill.

`ds.forms` owns the mapping (`config/forms/*.schema.json` + `config/required_fields.yaml`). This
module applies it to a request's `fields` dict.

Rule 7: e-mail text can never set approvers, bank details or credit terms. `FORBIDDEN_PREFILL`
is the allow-list's complement and is checked on every prefill.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ds.forms import FORM_DOMAINS, extract_to_form_field, load_form_schema, missing_keys
from ds.interpreter.schemas import Interpretation
from services.api.bankfields import BANK_KEY, has_bank_details

FORBIDDEN_PREFILL = frozenset({"PayTermsGrpCode", "CreditLimit", BANK_KEY})
REG_PREFIX = "registration_number_"

# Cost centres have no form schema (config + mock endpoint only); two fields are needed.
COST_CENTER_FIELDS = {"center_name": "CenterName", "effective_from": "EffectiveFrom"}


def form_properties(domain: str) -> set[str]:
    if domain == "cost_center":
        return {"CenterName", "EffectiveFrom", "purpose"}
    return set(load_form_schema(domain)["properties"])  # type: ignore[arg-type]


def title_of(domain: str, fields: Mapping[str, Any]) -> str:
    key = {"customer": "CardName", "vendor": "CardName", "item": "ItemName"}.get(
        domain, "CenterName"
    )
    return str(fields.get(key) or "").strip() or "Untitled"


def _to_extract(domain: str, country: str, fields: Mapping[str, Any]) -> dict[str, Any]:
    """The request's form fields, re-keyed by extract key, for `ds.forms.missing_keys`."""
    out: dict[str, Any] = {"country": country}
    if domain == "cost_center":
        for key, form_field in COST_CENTER_FIELDS.items():
            out[key] = fields.get(form_field)
        out["entity"] = "set on the request"
        return out
    for key, form_field in extract_to_form_field(domain).items():
        if form_field in fields:
            out[key] = fields[form_field]
    if domain == "customer" or domain == "vendor":
        out["country"] = fields.get("Country") or country
    if domain == "vendor" and has_bank_details(dict(fields)):
        out["bank_account"] = "present"
    if domain == "item":
        for row in fields.get("registrations") or []:
            if isinstance(row, dict) and row.get("reg_no"):
                out[f"{REG_PREFIX}{row.get('country')}"] = row["reg_no"]
    return out


def missing_form_fields(domain: str, country: str, fields: Mapping[str, Any]) -> list[str]:
    """Required form fields (SAP names) that are still empty, in display order.
    Per-country registrations are reported as `registrations[SG]`."""
    keys = missing_keys(domain, _to_extract(domain, country, fields), include_form_only=True)  # type: ignore[arg-type]
    to_field = (
        COST_CENTER_FIELDS | {"entity": "entity"}
        if domain == "cost_center"
        else extract_to_form_field(domain)  # type: ignore[arg-type]
    )
    out: list[str] = []
    for k in keys:
        if k.startswith(REG_PREFIX):
            out.append(f"registrations[{k.removeprefix(REG_PREFIX)}]")
        elif k == "bank_account":
            out.append(BANK_KEY)
        else:
            out.append(to_field.get(k, k))
    return out


def prefill_from_interpretation(
    domain: str, interp: Interpretation
) -> tuple[dict[str, Any], dict[str, str]]:
    """(form fields, form field -> source quote) from the interpreter's output.

    Only fields that exist on the form are taken, and never `PayTermsGrpCode`, `CreditLimit` or
    bank details.
    """
    if domain not in FORM_DOMAINS:
        return {}, {}
    schema = load_form_schema(domain)  # type: ignore[arg-type]
    props = schema["properties"]
    to_field = extract_to_form_field(domain)  # type: ignore[arg-type]
    fields: dict[str, Any] = {}
    quotes: dict[str, str] = {}
    registrations: dict[str, dict[str, Any]] = {}
    for qv in interp.fields:
        if qv.key.startswith(REG_PREFIX) and domain == "item":
            country = qv.key.removeprefix(REG_PREFIX)
            registrations[country] = {"country": country, "reg_no": str(qv.value)}
            quotes[f"registrations[{country}]"] = qv.source_quote
            continue
        form_field = to_field.get(qv.key)
        if not form_field or form_field in FORBIDDEN_PREFILL or form_field not in props:
            continue
        value: Any = qv.value
        mapping = props[form_field].get("x-extract-map")
        if mapping is not None:
            value = mapping.get(str(value).lower(), None)
            if value is None:
                continue
        if props[form_field].get("type") == "array" and not isinstance(value, list):
            value = [str(value)]
        fields[form_field] = value
        quotes[form_field] = qv.source_quote
    if registrations:
        fields["registrations"] = list(registrations.values())
    return fields, quotes

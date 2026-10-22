"""Request forms and required fields from `config/` (PRD M3). Shared by the API, the web form
(through `GET /forms/{domain}`) and the email interpreter's `missing_fields` (D-006).

Two names exist for each field:
- the **extract key** (`name`, `tax_id`, `registration_number_SG`, ...): what the interpreter
  extracts and what `config/required_fields.yaml` lists;
- the **form field** (`CardName`, `FederalTaxID`, ...): SAP field names (D-004), or app-only
  fields such as `selling_countries`. The JSON Schema maps one to the other with `x-extract`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any, Literal

import yaml

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"

Domain = Literal["customer", "vendor", "item", "cost_center"]
FORM_DOMAINS: tuple[Domain, ...] = ("customer", "vendor", "item")


@cache
def _required_config() -> dict[str, Any]:
    with open(CONFIG_DIR / "required_fields.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@cache
def load_form_schema(domain: Domain) -> dict[str, Any]:
    """The JSON Schema for a request form. Raises KeyError for a domain without a form."""
    if domain not in FORM_DOMAINS:
        raise KeyError(f"no form for domain {domain!r}")
    with open(CONFIG_DIR / "forms" / f"{domain}.schema.json", encoding="utf-8") as fh:
        return json.load(fh)


def _truthy(v: Any) -> bool:
    if isinstance(v, Mapping):  # {"value": ..., "source_quote": ...}
        v = v.get("value")
    return v in (True, "tYES") or str(v).strip().lower() in ("true", "yes", "ivd")


def _countries(v: Any) -> list[str]:
    if isinstance(v, Mapping):
        v = v.get("value")
    if isinstance(v, str):
        v = [v]
    return [str(c) for c in v or []]


def required_keys(
    domain: Domain,
    country: str | None = None,
    *,
    is_ivd: bool = False,
    selling_countries: list[str] | None = None,
    include_form_only: bool = False,
) -> list[str]:
    """Required extract keys, in order. `form_only` keys (bank details) are never asked of the
    email interpreter, so they are excluded unless `include_form_only` is set."""
    cfg = _required_config()
    spec = cfg.get(domain, {})
    keys = list(spec.get("all", []))
    if include_form_only:
        keys += spec.get("form_only", [])
    keys += cfg.get("by_country", {}).get(domain, {}).get(country or "", [])
    if domain == "item" and is_ivd:
        regulated = set(spec.get("ivd_registration_required_in", []))
        prefix = spec.get("ivd_per_country_key", "registration_number")
        keys += [f"{prefix}_{c}" for c in selling_countries or [] if c in regulated]
    return keys


def regulated_countries() -> list[str]:
    """Countries where an IVD item needs a registration number."""
    return list(_required_config()["item"].get("ivd_registration_required_in", []))


def missing_keys(
    domain: Domain, fields: Mapping[str, Any], *, include_form_only: bool = False
) -> list[str]:
    """Required extract keys that are absent or empty in `fields` (keyed by extract key).

    The country, IVD flag and selling countries are read from `fields` itself, so a partial
    request gets exactly the questions it still needs to answer.
    """
    present = {k for k, v in fields.items() if not _empty(v)}
    keys = required_keys(
        domain,
        _value(fields.get("country")),
        is_ivd=_truthy(fields.get("is_ivd")),
        selling_countries=_countries(fields.get("selling_countries")),
        include_form_only=include_form_only,
    )
    return [k for k in keys if k not in present]


def extract_to_form_field(domain: Domain) -> dict[str, str]:
    """Extract key -> form field, e.g. {"tax_id": "FederalTaxID"}. Per-country registration
    keys are not listed; they map to rows of `registrations` (see `x-extract-per-country`)."""
    props = load_form_schema(domain)["properties"]
    return {p["x-extract"]: name for name, p in props.items() if "x-extract" in p}


def dedup_query(domain: Domain, entity: str | None, fields: Mapping[str, Any]):
    """The duplicate-check query for a customer/vendor form (form fields = SAP names).

    The one place this mapping lives: the API's live check and the replay-cache recorder both
    use it, so a recorded AI-judge answer matches the request the demo actually sends.
    Returns None until a name and a country have been typed.
    """
    from ds.dedup.schemas import BPQuery

    name = str(fields.get("CardName") or "").strip()
    country = str(fields.get("Country") or "").strip()
    if domain not in ("customer", "vendor") or not name or not country:
        return None

    def opt(key: str) -> str | None:
        v = str(fields.get(key) or "").strip()
        return v or None

    return BPQuery(
        CardName=name,
        CardForeignName=opt("CardForeignName"),
        CardType="cCustomer" if domain == "customer" else "cSupplier",
        FederalTaxID=opt("FederalTaxID"),
        Country=country,
        City=opt("City"),
        Phone1=opt("Phone1"),
        EmailAddress=opt("EmailAddress"),
        U_Entity=entity,
        CardCode=opt("CardCode"),
    )


def _value(v: Any) -> Any:
    return v.get("value") if isinstance(v, Mapping) else v


def _empty(v: Any) -> bool:
    v = _value(v)
    return v is None or (isinstance(v, (str, list, dict)) and len(v) == 0)

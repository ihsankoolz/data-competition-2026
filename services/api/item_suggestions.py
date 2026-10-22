"""Deterministic suggestions for the item form: product family and item group.

The email interpreter never extracts these two fields and its prompt is frozen
(`tests/test_prompt_frozen.py`), so they are suggested here by plain rules, with no LLM:

- **Item group** (`ItemsGroupCode`): keywords in the item name, matched against the groups in
  `config/forms/item.schema.json`; if no keyword fits, the closest existing item in the catalogue.
- **Product family** (`product_family`): the requestor's entity (D-015: SPD -> A, QTS -> B,
  QTG -> C).

Every suggestion carries a plain-English reason. A suggestion never replaces a value the email
stated: callers use it only for fields that are still empty.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ds.forms import load_form_schema
from services.api.db import models as m

ENTITY_FAMILY = {"SPD": "A", "QTS": "B", "QTG": "C"}
FAMILY_WHAT = {
    "A": "reagents and test kits",
    "B": "analysers and equipment",
    "C": "service contracts",
}

# Item group code -> keywords, checked in this order (services first: "Annual Analyser Service
# Contract" is a service, not an analyser; kits before equipment: "Analyser Reagent Kit" is a kit).
GROUP_KEYWORDS: list[tuple[int, tuple[str, ...]]] = [
    (
        103,
        (
            "service",
            "contract",
            "maintenance",
            "subscription",
            "training",
            "installation",
            "validation",
            "warranty",
            "calibration visit",
        ),
    ),  # fmt: skip
    (
        101,
        (
            "test kit",
            "rapid test",
            "reagent",
            "assay",
            "antigen",
            "antibody",
            "cartridge",
            "calibrator",
            "control kit",
            "kit",
            "test strip",
            "diagnostic test",
            "elisa",
            "pcr",
        ),
    ),  # fmt: skip
    (
        102,
        (
            "analyser",
            "analyzer",
            "centrifuge",
            "microscope",
            "cabinet",
            "incubator",
            "equipment",
            "instrument",
            "machine",
            "refrigerator",
            "freezer",
            "autoclave",
            "reader",
        ),
    ),  # fmt: skip
]
_STOP = {"the", "and", "for", "with", "kit", "test", "rapid", "set", "of", "new", "ag", "ab"}


def _group_titles() -> dict[int, str]:
    spec = load_form_schema("item")["properties"]["ItemsGroupCode"]
    return {int(o["const"]): str(o["title"]) for o in spec["oneOf"]}


def _tokens(name: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", name.lower()) if len(t) > 2 and t not in _STOP}


def _by_keyword(name: str) -> tuple[int, str] | None:
    low = name.lower()
    for group, words in GROUP_KEYWORDS:
        for word in words:
            if re.search(rf"\b{re.escape(word)}", low):
                return group, word
    return None


def _by_catalogue(name: str, catalogue: Iterable[tuple[str, int | None]]) -> tuple[int, str] | None:
    mine = _tokens(name)
    best: tuple[int, int, str] | None = None
    for other, group in catalogue:
        if group is None:
            continue
        shared = len(mine & _tokens(other))
        if shared >= 2 and (best is None or shared > best[0]):
            best = (shared, group, other)
    return (best[1], best[2]) if best else None


def suggest_item_fields(
    item_name: str | None,
    entity: str,
    stated: Mapping[str, Any],
    catalogue: Iterable[tuple[str, int | None]] = (),
) -> dict[str, tuple[Any, str]]:
    """Form field -> (suggested value, plain-English reason) for the fields still empty.

    `stated` holds the values already on the form; a field that has one is left alone.
    """
    out: dict[str, tuple[Any, str]] = {}
    titles = _group_titles()
    name = (item_name or "").strip()
    if name and stated.get("ItemsGroupCode") in (None, ""):
        hit = _by_keyword(name)
        if hit is not None:
            group, word = hit
            out["ItemsGroupCode"] = (
                group,
                f'Suggested because the email mentions "{word}"; items like that are filed '
                f'under "{titles[group]}".',
            )
        else:
            near = _by_catalogue(name, catalogue)
            if near is not None:
                group, other = near
                out["ItemsGroupCode"] = (
                    group,
                    f'Suggested because it looks like the existing item "{other}", which is '
                    f'filed under "{titles[group]}".',
                )
    family = ENTITY_FAMILY.get(entity)
    if family and stated.get("product_family") in (None, ""):
        out["product_family"] = (
            family,
            f"Suggested because you are requesting for {entity}, which sells "
            f"{FAMILY_WHAT[family]} (product family {family}).",
        )
    return out


def catalogue(session: Session) -> list[tuple[str, int | None]]:
    """(item name, item group) of the items already in SAP."""
    return [(n, g) for n, g in session.execute(select(m.Item.ItemName, m.Item.ItemsGroupCode))]


def shown_reasons(session: Session, req: m.Request, fields: Mapping[str, Any]) -> dict[str, str]:
    """Reasons for the suggested values that are still on the form of an item created from an
    email. A value the requestor has since changed is theirs now, so its reason is dropped."""
    if req.domain != m.RequestDomain.item or not req.source_email_id:
        return {}
    blank = {k: v for k, v in fields.items() if k not in ("ItemsGroupCode", "product_family")}
    suggestions = suggest_item_fields(
        str(fields.get("ItemName") or ""), req.entity, blank, catalogue(session)
    )
    return {k: why for k, (value, why) in suggestions.items() if fields.get(k) == value}

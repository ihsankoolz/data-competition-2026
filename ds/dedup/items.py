"""Item duplicate check (session 13): is this new item already in the catalogue?

Rules only, no AI (domain rule 6: the system never decides; a person links or continues).
Three layers, in the spirit of the customer check (D-005):

1. **Catalogue number.** The manufacturer catalogue (REF) number typed on the form equals an
   existing item's catalogue number (`config/item_catalogue.yaml`, synthetic) or an existing
   ItemCode. -> Likely.
2. **Registration number.** The same registration number in the same country as an existing
   item's registration. One registration can't belong to two products. -> Likely.
3. **Normalised name.** Pack sizes ("box of 25", "kit (200 tests)", "x25", "25T"), units,
   punctuation, case and word order are ignored; abbreviations are expanded (Ag -> antigen);
   generic words (rapid, test, kit, reagent, analyser, ...) count for little, so two different
   kits that share only "antigen rapid test kit" never match.

Thresholds and word lists live in `ds/dedup/items.yaml`. Pure functions, Pydantic in and out.
"""

from __future__ import annotations

import re
import time
import unicodedata
from collections.abc import Iterable, Mapping
from functools import cache
from pathlib import Path
from typing import Any, Literal

import yaml
from anyascii import anyascii
from pydantic import BaseModel, ConfigDict, Field
from rapidfuzz import fuzz

ITEMS_CONFIG_PATH = Path(__file__).with_name("items.yaml")
CATALOGUE_PATH = Path(__file__).resolve().parents[2] / "config" / "item_catalogue.yaml"

ItemVerdict = Literal["likely", "possible"]
ItemLayer = Literal["catalogue", "registration", "name", "evidence"]

COUNTRY_NAMES = {
    "SG": "Singapore",
    "MY": "Malaysia",
    "ID": "Indonesia",
    "VN": "Vietnam",
    "TH": "Thailand",
}


# ---------------------------------------------------------------------------- schemas


class ItemRegistrationRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    country: str
    reg_no: str


class ItemRecord(BaseModel):
    """An existing item as the check sees it (SAP field names where they exist)."""

    model_config = ConfigDict(extra="ignore")

    ItemCode: str
    ItemName: str
    ItemsGroupCode: int | None = None
    sales_unit: str | None = None
    catalogue_numbers: list[str] = Field(
        default=[], description="Manufacturer catalogue (REF) numbers; synthetic in this demo"
    )
    registrations: list[ItemRegistrationRef] = []


class ItemQuery(BaseModel):
    """What the requester has typed on the item form so far."""

    model_config = ConfigDict(extra="ignore")

    ItemName: str = ""
    ItemsGroupCode: int | None = None
    manufacturer_catalogue_no: str | None = None
    registrations: list[ItemRegistrationRef] = []
    exclude_item_codes: list[str] = Field(
        default=[], description="Items that are this request itself (after it was published)"
    )


class ItemReason(BaseModel):
    layer: ItemLayer
    text: str = Field(description="Plain English, shown to the requester")
    weight: float = Field(default=0.0, description="Contribution to the score (+/-)")


class ItemCandidate(BaseModel):
    """An existing item that may be the same as the new one."""

    ItemCode: str
    ItemName: str
    ItemsGroupCode: int | None = None
    sales_unit: str | None = None
    score: float = Field(ge=0.0, le=1.0)
    name_score: float = Field(ge=0.0, le=1.0)
    verdict: ItemVerdict
    catalogue_match: bool = False
    registration_match: bool = False
    reasons: list[ItemReason] = []


class ItemDedupResult(BaseModel):
    verdict: Literal["likely", "possible", "none"]
    message: str
    block_submit: bool = Field(
        description="True for 'likely': submit waits until a person uses the existing item or "
        "says why theirs is different"
    )
    candidates: list[ItemCandidate] = []
    checked_items: int = Field(default=0, description="How many existing items were compared")
    elapsed_ms: float = 0.0


class ItemThresholds(BaseModel):
    likely: float = 0.85
    possible: float = 0.60


class ItemNameWeights(BaseModel):
    w_distinctive: float = 0.6
    w_all: float = 0.4
    token_ratio_min: float = 88
    generic_weight: float = 0.15
    semi_generic_weight: float = 0.5
    no_distinctive_cap: float = 0.30
    number_mismatch_penalty: float = 0.25


class ItemEvidenceWeights(BaseModel):
    catalogue_floor: float = 0.97
    registration_floor: float = 0.97
    catalogue_conflict_penalty: float = 0.20
    registration_conflict_penalty: float = 0.15
    group_conflict_penalty: float = 0.10


class ItemDedupConfig(BaseModel):
    thresholds: ItemThresholds = ItemThresholds()
    max_candidates: int = 5
    name: ItemNameWeights = ItemNameWeights()
    evidence: ItemEvidenceWeights = ItemEvidenceWeights()
    generic: list[str] = []
    semi_generic: list[str] = []
    stopwords: list[str] = []
    aliases: dict[str, str] = {}
    phrases: dict[str, str] = {}

    @classmethod
    def load(cls, path: Path | str = ITEMS_CONFIG_PATH) -> ItemDedupConfig:
        with open(path, encoding="utf-8") as fh:
            return cls.model_validate(yaml.safe_load(fh) or {})


@cache
def default_config() -> ItemDedupConfig:
    return ItemDedupConfig.load()


@cache
def load_catalogue(path: str = str(CATALOGUE_PATH)) -> dict[str, list[str]]:
    """ItemCode -> synthetic manufacturer catalogue numbers (`config/item_catalogue.yaml`)."""
    with open(path, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    return {str(k): [str(v) for v in vs or []] for k, vs in (doc.get("items") or {}).items()}


# ---------------------------------------------------------------------------- normalising

# Pack sizes and units. Order matters: "box of 25 tests" before "25 tests".
_COUNT_WORDS = (
    r"tests?|t|tst|pcs|pc|pieces?|strips?|cassettes?|devices?|det|determinations?|"
    r"reactions?|rxns?|kits?|units?|vials?|cartridges?|samples?"
)
PACK_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        rf"\b(?:box|pack|kit|carton|case|bottle|vial|tub|bag|set)\s+of\s+\d+(?:\s*(?:{_COUNT_WORDS}))?\b",
        r"\b\d+\s*[x×]\s*\d+(?:\.\d+)?\s*(?:ml|ul|mg|g|l|tests?|t)?\b",
        r"\b\d+(?:\.\d+)?\s*(?:ml|ul|mg|kg|g|l|mm|cm|rpm|w|v)\b",
        rf"\b\d+\s*(?:{_COUNT_WORDS})\s*(?:/|per)\s*(?:kit|box|pack)\b",
        rf"\b\d+\s*(?:{_COUNT_WORDS})\b",
        r"\b[x×]\s*\d+\b",
        r"\b\d+\s*[x×]\b",
        r"\bper\s+(?:box|kit|pack)\b",
    )
)


def _fold(s: str) -> str:
    """Lowercase ASCII: accents and other scripts romanised (anyascii), for comparing only."""
    return anyascii(unicodedata.normalize("NFKC", s or "")).lower()


def strip_pack_size(name: str) -> str:
    """'Rapid Dengue NS1 Ag Test Kit, box of 25' -> 'rapid dengue ns1 ag test kit, '"""
    s = _fold(name)
    for pat in PACK_PATTERNS:
        s = pat.sub(" ", s)
    return s


def _depluralise(t: str) -> str:
    if len(t) >= 4 and t.endswith("s") and not t.endswith(("ss", "us", "is", "ys")):
        return t[:-1]
    return t


def name_tokens(name: str, cfg: ItemDedupConfig | None = None) -> list[str]:
    """The words the name check compares, in order: no pack size, units, punctuation or case;
    abbreviations expanded. 'Rapid Dengue NS1 Ag Test Kit (25T)' ->
    ['rapid', 'dengue', 'ns1', 'antigen', 'test', 'kit']."""
    cfg = cfg or default_config()
    s = strip_pack_size(name)
    s = re.sub(r"(?<=[a-z0-9])-(?=\d)|(?<=\d)-(?=[a-z])", "", s)  # ns-1 -> ns1, 5-part -> 5part
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    for phrase, repl in sorted(cfg.phrases.items(), key=lambda kv: -len(kv[0])):
        s = re.sub(rf"\b{re.escape(phrase)}\b", repl, s)
    stop = set(cfg.stopwords)
    out: list[str] = []
    for raw in s.split():
        for t in cfg.aliases.get(raw, raw).split():
            t = _depluralise(t)
            t = cfg.aliases.get(t, t)
            for u in t.split():
                if u and u not in stop and u not in out:
                    out.append(u)
    return out


def normalise_item_name(name: str, cfg: ItemDedupConfig | None = None) -> str:
    """The normalised name, words sorted (word order does not matter)."""
    return " ".join(sorted(name_tokens(name, cfg)))


def normalise_code(code: str | None) -> str:
    """Catalogue numbers and ItemCodes: case, spaces, dots, hyphens, slashes and a leading 'REF'
    ignored. 'REF 51-DNS1-25' -> '51DNS125'."""
    s = _fold(code or "").upper()
    s = re.sub(r"^\s*REF\b[\s.:#-]*", "", s)
    return re.sub(r"[^A-Z0-9]", "", s)


def normalise_reg_no(reg: str | None) -> str:
    """'24170581ĐKLH/BYT-HTTB' -> '24170581DKLHBYTHTTB'."""
    return re.sub(r"[^A-Z0-9]", "", _fold(reg or "").upper())


def _weight(t: str, cfg: ItemDedupConfig) -> float:
    if t in cfg.generic:
        return cfg.name.generic_weight
    if t in cfg.semi_generic:
        return cfg.name.semi_generic_weight
    if t.isdigit():
        return cfg.name.semi_generic_weight
    return 1.0


def _distinctive(t: str, cfg: ItemDedupConfig) -> bool:
    return t not in cfg.generic and t not in cfg.semi_generic and not t.isdigit()


def _same_word(a: str, b: str, cfg: ItemDedupConfig) -> bool:
    if a == b:
        return True
    if any(c.isdigit() for c in a + b) or min(len(a), len(b)) < 5:
        return False
    return fuzz.ratio(a, b) >= cfg.name.token_ratio_min


def _numbers(tokens: Iterable[str]) -> set[str]:
    return {n for t in tokens for n in re.findall(r"\d+", t)}


class NameMatch(BaseModel):
    score: float
    shared: list[str] = []
    shared_distinctive: list[str] = []
    numbers_differ: bool = False
    exact: bool = False


def name_similarity(
    a: list[str] | str, b: list[str] | str, cfg: ItemDedupConfig | None = None
) -> NameMatch:
    """Weighted word overlap of two names (0..1). Distinctive words carry the score; generic
    words count for little; a name with no distinctive word in common scores at most the cap."""
    cfg = cfg or default_config()
    ta = name_tokens(a, cfg) if isinstance(a, str) else a
    tb = name_tokens(b, cfg) if isinstance(b, str) else b
    if not ta or not tb:
        return NameMatch(score=0.0)
    used: set[int] = set()
    pairs: list[tuple[str, str]] = []
    for x in ta:
        for j, y in enumerate(tb):
            if j not in used and _same_word(x, y, cfg):
                used.add(j)
                pairs.append((x, y))
                break
    matched_w = sum(min(_weight(x, cfg), _weight(y, cfg)) for x, y in pairs)
    total_a = sum(_weight(t, cfg) for t in ta)
    total_b = sum(_weight(t, cfg) for t in tb)
    all_score = matched_w / max(total_a + total_b - matched_w, 1e-9)

    da = [t for t in ta if _distinctive(t, cfg)]
    db = [t for t in tb if _distinctive(t, cfg)]
    shared_d = [x for x, y in pairs if _distinctive(x, cfg) and _distinctive(y, cfg)]
    if da and db:
        jacc_d = len(shared_d) / (len(da) + len(db) - len(shared_d))
        smaller = min(len(da), len(db))
        # A shorter name whose distinctive words all appear in the longer one ("Dengue NS1 Rapid
        # Test" vs "Rapid Dengue NS1 Ag Test Kit") counts, but only with two or more such words.
        contain = len(shared_d) / smaller if smaller >= 2 else jacc_d
        dist_score = 0.5 * jacc_d + 0.5 * contain
    else:
        dist_score = all_score
    score = cfg.name.w_distinctive * dist_score + cfg.name.w_all * all_score
    if not shared_d:
        score = min(score, cfg.name.no_distinctive_cap)
    na, nb = _numbers(ta), _numbers(tb)
    numbers_differ = bool(na and nb and na != nb)
    if numbers_differ:
        score -= cfg.name.number_mismatch_penalty
    exact = sorted(ta) == sorted(tb)
    if exact:
        score = 1.0
    return NameMatch(
        score=round(max(0.0, min(1.0, score)), 4),
        shared=[x for x, _ in pairs],
        shared_distinctive=shared_d,
        numbers_differ=numbers_differ,
        exact=exact,
    )


# ---------------------------------------------------------------------------- the check


class ItemIndex:
    """Existing items with their normalised names, catalogue numbers and registrations."""

    def __init__(self, items: Iterable[ItemRecord], cfg: ItemDedupConfig | None = None):
        self.cfg = cfg or default_config()
        self.items = list(items)
        self.tokens = {it.ItemCode: name_tokens(it.ItemName, self.cfg) for it in self.items}
        self.codes: dict[str, list[tuple[str, str]]] = {}  # normalised -> [(ItemCode, shown)]
        self.regs: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for it in self.items:
            self.codes.setdefault(normalise_code(it.ItemCode), []).append(
                (it.ItemCode, "item code")
            )
            for c in it.catalogue_numbers:
                self.codes.setdefault(normalise_code(c), []).append((it.ItemCode, c))
            for r in it.registrations:
                key = (r.country.upper(), normalise_reg_no(r.reg_no))
                if key[1]:
                    self.regs.setdefault(key, []).append((it.ItemCode, r.reg_no))

    def __len__(self) -> int:
        return len(self.items)


def _query_regs(q: ItemQuery) -> list[tuple[str, str, str]]:
    out = []
    for r in q.registrations:
        n = normalise_reg_no(r.reg_no)
        if n and r.country:
            out.append((r.country.upper(), n, r.reg_no.strip()))
    return out


def score_item(q: ItemQuery, it: ItemRecord, index: ItemIndex) -> ItemCandidate | None:
    cfg = index.cfg
    ev = cfg.evidence
    reasons: list[ItemReason] = []
    q_tokens = name_tokens(q.ItemName, cfg)
    nm = name_similarity(q_tokens, index.tokens[it.ItemCode], cfg)
    score = nm.score
    if nm.exact:
        reasons.append(
            ItemReason(
                layer="name",
                text="Same name once pack size, punctuation, abbreviations and word order "
                "are ignored.",
                weight=nm.score,
            )
        )
    elif nm.shared_distinctive and nm.score >= cfg.thresholds.possible:
        words = ", ".join(f"“{w}”" for w in nm.shared_distinctive)
        reasons.append(
            ItemReason(
                layer="name",
                text=f"Very similar name: both are about {words} "
                f"(name similarity {nm.score:.2f} out of 1).",
                weight=nm.score,
            )
        )
    if nm.numbers_differ:
        reasons.append(
            ItemReason(
                layer="name",
                text="The names have different numbers in them, so it may be a different model.",
                weight=-cfg.name.number_mismatch_penalty,
            )
        )

    # Catalogue number.
    cat = normalise_code(q.manufacturer_catalogue_no)
    catalogue_match = False
    if cat:
        hits = [shown for code, shown in index.codes.get(cat, []) if code == it.ItemCode]
        if hits:
            catalogue_match = True
            score = max(score, ev.catalogue_floor)
            if hits[0] == "item code":
                text = f"The catalogue number you typed is the item code of {it.ItemCode}."
            else:
                text = (
                    f"Same manufacturer catalogue number as {it.ItemCode}: {hits[0]} "
                    "(a synthetic demo number)."
                )
            reasons.insert(0, ItemReason(layer="catalogue", text=text, weight=ev.catalogue_floor))
        elif it.catalogue_numbers:
            score -= ev.catalogue_conflict_penalty
            reasons.append(
                ItemReason(
                    layer="catalogue",
                    text=f"Different manufacturer catalogue number from {it.ItemCode} "
                    f"({it.catalogue_numbers[0]}, synthetic).",
                    weight=-ev.catalogue_conflict_penalty,
                )
            )

    # Registration number per country.
    registration_match = False
    theirs = {(r.country.upper(), normalise_reg_no(r.reg_no)): r.reg_no for r in it.registrations}
    their_countries = {c for c, n in theirs if n}
    for country, n, shown in _query_regs(q):
        where = COUNTRY_NAMES.get(country, country)
        if (country, n) in theirs:
            registration_match = True
            score = max(score, ev.registration_floor)
            reasons.insert(
                0,
                ItemReason(
                    layer="registration",
                    text=f"Registration number {shown} in {where} already belongs to "
                    f"{it.ItemCode}. One registration can't belong to two products.",
                    weight=ev.registration_floor,
                ),
            )
        elif country in their_countries and not registration_match:
            score -= ev.registration_conflict_penalty
            reasons.append(
                ItemReason(
                    layer="registration",
                    text=f"{it.ItemCode} is registered in {where} under a different number.",
                    weight=-ev.registration_conflict_penalty,
                )
            )

    if (
        q.ItemsGroupCode is not None
        and it.ItemsGroupCode is not None
        and q.ItemsGroupCode != it.ItemsGroupCode
        and not (catalogue_match or registration_match)
    ):
        score -= ev.group_conflict_penalty
        reasons.append(
            ItemReason(
                layer="evidence",
                text="It is in a different item group.",
                weight=-ev.group_conflict_penalty,
            )
        )

    if catalogue_match or registration_match:
        score = max(score, ev.catalogue_floor if catalogue_match else ev.registration_floor)
    score = round(max(0.0, min(1.0, score)), 4)
    if score < cfg.thresholds.possible:
        return None
    verdict: ItemVerdict = "likely" if score >= cfg.thresholds.likely else "possible"
    return ItemCandidate(
        ItemCode=it.ItemCode,
        ItemName=it.ItemName,
        ItemsGroupCode=it.ItemsGroupCode,
        sales_unit=it.sales_unit,
        score=score,
        name_score=nm.score,
        verdict=verdict,
        catalogue_match=catalogue_match,
        registration_match=registration_match,
        reasons=reasons,
    )


def check_item(q: ItemQuery, index: ItemIndex) -> ItemDedupResult:
    """Compare a new item with every existing item. Never links anything (rule 6)."""
    t0 = time.perf_counter()
    has_input = bool(name_tokens(q.ItemName, index.cfg)) or bool(
        normalise_code(q.manufacturer_catalogue_no) or _query_regs(q)
    )
    if not has_input:
        return ItemDedupResult(
            verdict="none",
            message="Type the item name and we will check for an existing item.",
            block_submit=False,
            checked_items=0,
        )
    skip = set(q.exclude_item_codes)
    found = [c for it in index.items if it.ItemCode not in skip if (c := score_item(q, it, index))]
    found.sort(key=lambda c: (-c.score, c.ItemCode))
    found = found[: index.cfg.max_candidates]
    ms = round((time.perf_counter() - t0) * 1000, 2)
    if not found:
        return ItemDedupResult(
            verdict="none",
            message=f"No existing item matched. We compared it with {len(index)} items in the "
            "catalogue.",
            block_submit=False,
            checked_items=len(index),
            elapsed_ms=ms,
        )
    top = found[0]
    if top.verdict == "likely":
        message = (
            f"This looks like an item we already have: {top.ItemName} ({top.ItemCode}). "
            "Use the existing item, or say why yours is different."
        )
    else:
        message = (
            f"An existing item looks similar: {top.ItemName} ({top.ItemCode}). "
            "Please check before you submit."
        )
    return ItemDedupResult(
        verdict=top.verdict,
        message=message,
        block_submit=top.verdict == "likely",
        candidates=found,
        checked_items=len(index),
        elapsed_ms=ms,
    )


# ---------------------------------------------------------------------------- inputs


def item_query(fields: Mapping[str, Any], exclude: Iterable[str] = ()) -> ItemQuery:
    """The query for an item form (form fields = SAP names + app-only fields)."""
    regs: list[ItemRegistrationRef] = []
    for r in fields.get("registrations") or []:
        if isinstance(r, Mapping) and str(r.get("reg_no") or "").strip() and r.get("country"):
            regs.append(ItemRegistrationRef(country=str(r["country"]), reg_no=str(r["reg_no"])))
    group = fields.get("ItemsGroupCode")
    try:
        group_code = int(group) if group not in (None, "") else None
    except (TypeError, ValueError):
        group_code = None
    cat = str(fields.get("manufacturer_catalogue_no") or "").strip() or None
    return ItemQuery(
        ItemName=str(fields.get("ItemName") or "").strip(),
        ItemsGroupCode=group_code,
        manufacturer_catalogue_no=cat,
        registrations=regs,
        exclude_item_codes=[c for c in exclude if c],
    )


def records_from_fixtures(fixture_dir: Path | str) -> list[ItemRecord]:
    """The 15 demo items from `items.csv` + `item_registrations.csv` + the synthetic catalogue."""
    import csv

    d = Path(fixture_dir)
    regs: dict[str, list[ItemRegistrationRef]] = {}
    with open(d / "item_registrations.csv", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("reg_no"):
                regs.setdefault(row["item_code"], []).append(
                    ItemRegistrationRef(country=row["country"], reg_no=row["reg_no"])
                )
    cat = load_catalogue()
    out: list[ItemRecord] = []
    with open(d / "items.csv", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            code = row["ItemCode"]
            out.append(
                ItemRecord(
                    ItemCode=code,
                    ItemName=row["ItemName"],
                    ItemsGroupCode=int(row["ItemsGroupCode"])
                    if row.get("ItemsGroupCode")
                    else None,
                    sales_unit=row.get("sales_unit") or None,
                    catalogue_numbers=cat.get(code, []),
                    registrations=regs.get(code, []),
                )
            )
    return out

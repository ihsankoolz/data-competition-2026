"""Golden customers, the raw SAP-like BP master and its ground truth (data-spec §3-4)."""

from __future__ import annotations

import itertools
import json
import re
from dataclasses import dataclass, field
from datetime import date

import numpy as np
from anyascii import anyascii

from . import curated as cur
from .common import (
    WINDOW_END,
    add_days,
    fmt_money,
    month_date,
    month_str,
    pick,
    stream,
    wpick,
)
from .names import SEGMENTS, NameFactory, NameSpec, largest_remainder, segment_counts
from .variants import DUP_TYPES, TRANSFORMS

COUNTRY_ORDER = ["SG", "MY", "ID", "VN", "TH"]
FAMILIES = ["A", "B", "C"]
ENTITIES = ["SPD", "QTS", "QTG"]
GROUP_CODES = {
    "public_hospital": 100,
    "private_hospital": 101,
    "laboratory": 102,
    "clinic": 103,
    "distributor": 104,
}
PAY_TERMS = {  # PayTermsGrpCode: -1 cash, 1 = 30d, 2 = 45d, 3 = 60d, 4 = 90d
    "public_hospital": {3: 0.5, 4: 0.5},
    "private_hospital": {1: 0.4, 2: 0.4, 3: 0.2},
    "laboratory": {1: 0.6, 2: 0.4},
    "clinic": {-1: 0.4, 1: 0.6},
    "distributor": {2: 0.5, 3: 0.5},
}
CREDIT_USD = {
    "public_hospital": 60000,
    "private_hospital": 40000,
    "laboratory": 20000,
    "clinic": 5000,
    "distributor": 80000,
}
CITY_VARIANTS = {
    "Singapore": ["SINGAPORE", "S'pore", "Singapore 119074"],
    "Kuala Lumpur": ["KL", "K. Lumpur", "Wilayah Persekutuan Kuala Lumpur"],
    "Johor Bahru": ["JB", "Johor Baharu"],
    "Georgetown": ["George Town", "Penang", "Pulau Pinang"],
    "Petaling Jaya": ["PJ", "Petaling Jaya, Selangor"],
    "Jakarta": ["DKI Jakarta", "Jakarta Pusat", "Jakarta Selatan", "JAKARTA"],
    "Surabaya": ["SURABAYA", "Kota Surabaya"],
    "Yogyakarta": ["Jogja", "DI Yogyakarta"],
    "Ho Chi Minh City": ["HCMC", "TP.HCM", "TP. Hồ Chí Minh", "Saigon"],
    "Hanoi": ["Ha Noi", "Hà Nội", "HN"],
    "Da Nang": ["Đà Nẵng", "Danang"],
    "Bangkok": ["กรุงเทพมหานคร", "BKK", "Bangkok 10700", "Krung Thep"],
    "Chiang Mai": ["เชียงใหม่", "Chiangmai"],
}
PHONE_AREA = {
    "SG": {"": "6"},
    "MY": {
        "Kuala Lumpur": "3",
        "Georgetown": "4",
        "Johor Bahru": "7",
        "Kuching": "82",
        "Kota Kinabalu": "88",
        "Ipoh": "5",
        "Melaka": "6",
        "Kuantan": "9",
        "": "3",
    },
    "ID": {
        "Jakarta": "21",
        "Surabaya": "31",
        "Bandung": "22",
        "Medan": "61",
        "Semarang": "24",
        "Yogyakarta": "274",
        "Denpasar": "361",
        "Makassar": "411",
        "Palembang": "711",
        "Malang": "341",
        "": "21",
    },
    "VN": {
        "Ho Chi Minh City": "28",
        "Hanoi": "24",
        "Da Nang": "236",
        "Hai Phong": "225",
        "Can Tho": "292",
        "Hue": "234",
        "": "28",
    },
    "TH": {
        "Bangkok": "2",
        "Chiang Mai": "53",
        "Phuket": "76",
        "Khon Kaen": "43",
        "Pattaya": "38",
        "Chonburi": "38",
        "Hat Yai": "74",
        "": "2",
    },
}
SUB_LEN = {  # subscriber digits after the area code
    "SG": lambda a: 7,
    "MY": lambda a: 8 if a == "3" else 6 if len(a) == 2 else 7,
    "ID": lambda a: 8 if len(a) == 2 else 7,
    "VN": lambda a: 8 if len(a) == 2 else 7,
    "TH": lambda a: 7 if a == "2" else 6,
}
COUNTRY_CODE = {"SG": "65", "MY": "60", "ID": "62", "VN": "84", "TH": "66"}
EMAIL_ROLES = ["procurement", "purchasing", "accounts", "lab", "admin", "finance", "store"]


@dataclass(eq=False)
class Golden:
    idx: int
    golden_id: str
    spec: NameSpec
    tax_id: str
    phone_area: str
    phone_sub: str
    email_domain: str
    start_idx: int
    families: dict[str, int] = field(default_factory=dict)  # family -> adoption month index
    churn_idx: int | None = None
    decline_months: int | None = None
    is_new: bool = False
    records: list[Rec] = field(default_factory=list)

    @property
    def country(self) -> str:
        return self.spec.country

    @property
    def segment(self) -> str:
        return self.spec.segment


@dataclass(eq=False)
class Rec:
    golden: Golden
    seq: int
    role: str  # primary | entity_record | duplicate | migration_new
    entity: str
    card_name: str
    foreign_name: str
    tax_id: str
    create_date: date
    group_code: int
    pay_terms: int
    credit_limit: str
    email: str
    phone: str
    city: str
    created_by: str
    family: str | None = None
    dup_of: Rec | None = None
    dup_type: str = ""
    tax_state: str = ""
    card_code: str = ""


@dataclass(eq=False)
class Master:
    golden: list[Golden]
    records: list[Rec]
    dup_pairs: list[list]
    migrations: list[list]
    cv_golden: list[Golden]


# --------------------------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------------------------


def format_phone(country: str, area: str, sub: str, style: int) -> str:
    cc = COUNTRY_CODE[country]
    half = len(sub) // 2
    a, b = sub[:half], sub[half:]
    if country == "SG":
        num = area + sub
        return [f"+65 {num[:4]} {num[4:]}", f"{num[:4]} {num[4:]}", f"+65{num}", num][style]
    styles = [
        f"+{cc} {area} {a} {b}",
        f"0{area}-{a} {b}",
        f"(0{area}) {a}-{b}",
        f"+{cc}{area}{sub}",
    ]
    if country == "MY":
        styles[0] = f"+{cc} {area}-{a} {b}"
    return styles[style]


def make_tax_id(country: str, rng: np.random.Generator, city: str) -> str:
    d = lambda n: "".join(str(int(x)) for x in rng.integers(0, 10, n))  # noqa: E731
    if country == "SG":
        return f"{int(rng.integers(1970, 2023))}{d(5)}{chr(65 + int(rng.integers(26)))}"
    if country == "MY":
        return f"{int(rng.integers(1980, 2023))}01{d(6)}"
    if country == "ID":
        x = "0" + d(11) + "000"
        return f"{x[:2]}.{x[2:5]}.{x[5:8]}.{x[8]}-{x[9:12]}.{x[12:]}"
    if country == "VN":
        prov = {"Hanoi": "01", "Ho Chi Minh City": "03", "Da Nang": "04"}.get(city, "0" + d(1))
        return prov + d(8)
    return f"0105{int(rng.integers(40, 66))}{d(7)}"


def tax_variant(country: str, tax: str, rng: np.random.Generator, dotted_prob: float) -> str:
    """Same tax ID, formatted the way a person might type it (NPWP dots are optional)."""
    if country == "ID" and rng.random() > dotted_prob:
        return re.sub(r"[.\-]", "", tax)
    return tax


def malformed_tax(country: str, tax: str, rng: np.random.Generator) -> str:
    generic = ["N/A", "TBC", "-", "0000000000"]
    opts = {
        "SG": [tax[:-1], tax.lower(), f"{tax[:4]} {tax[4:]}"],
        "MY": [tax[:4] + tax[6:], f"{tax[6:]}-{chr(65 + int(rng.integers(26)))}"],
        "ID": [re.sub(r"[.\-]", "", tax)[:-1], re.sub(r"[.\-]", "", tax)[:12]],
        "VN": [tax[:-1], tax + str(int(rng.integers(10)))],
        "TH": [tax[:-1], tax + "0"],
    }[country]
    return pick(rng, opts + generic[:2] if rng.random() < 0.8 else generic)


def email_domain(spec: NameSpec, used: set[str]) -> str:
    words = [
        w
        for w in re.findall(r"[a-z0-9]+", anyascii(spec.english).lower())
        if w not in ("the", "and", "of", "for", "s")
    ]
    base = "".join(w[0] for w in words) if len(words) >= 3 else "".join(words[:2])
    base = base or "clinic"
    dom, n = f"{base}.{spec.country.lower()}.example", 2
    while dom in used:
        dom, n = f"{base}{n}.{spec.country.lower()}.example", n + 1
    used.add(dom)
    return dom


def credit_limit(seg: str, currency: str, fx: dict, rng: np.random.Generator) -> str:
    usd = CREDIT_USD[seg] * float(rng.lognormal(0.0, 0.4))
    local = usd / fx[currency]
    mag = 10 ** max(0, len(str(int(local))) - 2)
    return fmt_money(round(local / mag) * mag)


# --------------------------------------------------------------------------------------------
# Golden customers
# --------------------------------------------------------------------------------------------


def build_golden(params: dict, seed: int) -> list[Golden]:
    rng = stream(seed, "golden.names")
    used: set[str] = set()
    curated = cur.curated_specs()
    for s in curated:
        used.add(s.core_key())
    factory = NameFactory(rng, seed, used)

    specs: list[NameSpec] = []
    for c in COUNTRY_ORDER:
        counts = segment_counts(params["countries"][c]["n_golden"], params["segment_mix"])
        for seg in SEGMENTS:
            fixed = [s for s in curated if s.country == c and s.segment == seg]
            if len(fixed) > counts[seg]:
                raise ValueError(f"too many curated {c}/{seg}: {len(fixed)} > {counts[seg]}")
            specs.extend(fixed)
            specs.extend(factory.build(c, seg) for _ in range(counts[seg] - len(fixed)))

    trng = stream(seed, "golden.attrs")
    tax_used: set[str] = {cur.CHORAY_MST}
    dom_used: set[str] = set()
    out: list[Golden] = []
    for i, spec in enumerate(specs):
        if spec.key == cur.CHORAY:
            tax = cur.CHORAY_MST
        else:
            tax = make_tax_id(spec.country, trng, spec.city)
            while tax in tax_used:
                tax = make_tax_id(spec.country, trng, spec.city)
            tax_used.add(tax)
        areas = PHONE_AREA[spec.country]
        area = areas.get(spec.city, areas[""])
        n_sub = SUB_LEN[spec.country](area)
        sub = "".join(str(int(x)) for x in trng.integers(0, 10, n_sub))
        sub = str(int(trng.integers(2, 10))) + sub[1:]
        out.append(
            Golden(
                i,
                f"GLD{i + 1:05d}",
                spec,
                tax,
                area,
                sub,
                email_domain(spec, dom_used),
                start_idx=0,
            )
        )
    return out


def assign_lifecycle(golden: list[Golden], params: dict, seed: int) -> None:
    lc, ad = params["lifecycle"], params["adoption"]
    rng = stream(seed, "golden.lifecycle")
    n = len(golden)
    anchors = {g.idx for g in golden if g.spec.key}
    free = [g.idx for g in golden if g.idx not in anchors]

    n_new = round(lc["new_starter_share"] * n)
    new_set = set(int(i) for i in rng.choice(free, n_new, replace=False))
    free2 = [i for i in free if i not in new_set]
    n_churn = round(lc["churner_share"] * n)
    churn_set = set(int(i) for i in rng.choice(free2, n_churn, replace=False))

    y0, y1 = lc["legacy_start_year_range"]
    for g in golden:
        if g.idx in new_set:
            lo, hi = lc["new_starter_month_range"]
            g.start_idx, g.is_new = int(rng.integers(lo, hi + 1)), True
        else:
            year = int(rng.integers(y0, y1 + 1))
            month = int(rng.integers(1, 10 if year == 2023 else 13))
            g.start_idx = (year - 2023) * 12 + (month - 10)
        if g.idx in churn_set:
            lo, hi = lc["churn_month_range"]
            g.churn_idx = int(rng.integers(lo, hi + 1))
            g.decline_months = int(
                rng.integers(lc["decline_months_range"][0], lc["decline_months_range"][1] + 1)
            )
        # product adoption
        if g.spec.key:
            primary = "A"
        else:
            primary = wpick(rng, ad["primary_family"][g.segment])
        g.families = {primary: g.start_idx}
        last = ad["last_adoption_month"]
        if g.churn_idx is not None:
            last = min(last, g.churn_idx - g.decline_months - 1)
        for f in FAMILIES:
            if f == primary or g.spec.key in (cur.CHORAY, cur.SIRIRAJ, cur.HKL, cur.BIOMED):
                continue
            p = ad["cross_sell_prob"][g.segment][f]
            if g.spec.key == cur.NUH:
                p = 1.0 if f == "B" else 0.0
            if g.spec.key == cur.RSCM:
                p = 1.0 if f == "C" else 0.0
            if rng.random() < p and last > g.start_idx:
                g.families[f] = int(rng.integers(g.start_idx + 1, last + 1))


# --------------------------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------------------------


class RecordMaker:
    def __init__(self, params: dict, seed: int):
        self.p = params
        self.rng = stream(seed, "records.base")
        self.seq = 0

    def _common(self, g: Golden, entity: str, rng: np.random.Generator, dup: bool) -> dict:
        br = self.p["base_record"]
        seg, c = g.segment, g.country
        currency = self.p["countries"][c]["currency"]
        group_code = GROUP_CODES[seg]
        if dup and rng.random() < br["group_code_mismatch_prob"]:
            group_code = GROUP_CODES[pick(rng, [s for s in SEGMENTS if s != seg])]
        r = rng.random()
        blank_p = 0.25 if dup else br["email_blank_prob"]
        if r < blank_p:
            email = ""
        elif dup and r < blank_p + 0.15:
            email = (
                f"{pick(rng, ['nurse.station', 'lab.manager', 'buyer'])}"
                f"{int(rng.integers(1, 99))}@mail.example"
            )
        else:
            email = f"{pick(rng, EMAIL_ROLES)}@{g.email_domain}"
        phone_blank = 0.4 if dup else br["phone_blank_prob"]
        phone = (
            ""
            if rng.random() < phone_blank
            else format_phone(c, g.phone_area, g.phone_sub, int(rng.integers(4)))
        )
        city = g.spec.city
        cv_p = 0.4 if dup else br["city_variant_prob"]
        if not g.spec.key and city in CITY_VARIANTS and rng.random() < cv_p:
            city = pick(rng, CITY_VARIANTS[city])
        return dict(
            group_code=group_code,
            pay_terms=int(wpick(rng, {str(k): v for k, v in PAY_TERMS[seg].items()})),
            credit_limit=credit_limit(seg, currency, self.p["fx_usd"], rng),
            email=email,
            phone=phone,
            city=city,
            created_by=f"{entity.lower()}.{c.lower()}{int(rng.integers(1, 4)):02d}",
        )

    def foreign_name(self, g: Golden, card_name: str, rng: np.random.Generator) -> str:
        if (
            anyascii(card_name) != card_name
            and rng.random() < self.p["base_record"]["foreign_name_prob"]
        ):
            return g.spec.english
        return ""

    def base(self, g: Golden, family: str, entity: str, primary: bool) -> Rec:
        rng, br = self.rng, self.p["base_record"]
        if primary and g.spec.forced_card_name:
            name = g.spec.forced_card_name
        else:
            form = wpick(rng, self.p["name_forms"][g.country])
            name = g.spec.forms()[form]
        tax = tax_variant(g.country, g.tax_id, rng, br["npwp_dotted_prob"])
        if not g.spec.key and rng.random() < br["taxid_blank_prob"]:
            tax = ""
        adopt = month_date(g.families[family])
        create = add_days(adopt, -int(rng.integers(0, 61)))
        self.seq += 1
        rec = Rec(
            golden=g,
            seq=self.seq,
            role="primary" if primary else "entity_record",
            entity=entity,
            card_name=name,
            foreign_name="" if g.spec.key == cur.CHORAY else self.foreign_name(g, name, rng),
            tax_id=tax,
            create_date=create,
            family=family,
            tax_state="same" if tax else "blank",
            **self._common(g, entity, rng, dup=False),
        )
        g.records.append(rec)
        return rec

    def duplicate(
        self,
        src: Rec,
        name: str,
        dup_type: str,
        entity: str,
        create: date,
        rng: np.random.Generator,
        migration: bool,
    ) -> Rec:
        g, dp = src.golden, self.p["duplicates"]
        if dup_type == "missing_tax_id":
            if rng.random() < dp["missing_tax_malformed_prob"]:
                tax, state = malformed_tax(g.country, g.tax_id, rng), "malformed"
            else:
                tax, state = "", "blank"
        elif rng.random() < dp["dup_taxid_same_prob"]:
            tax, state = tax_variant(g.country, g.tax_id, rng, 0.5), "same"
        else:
            tax, state = "", "blank"
        self.seq += 1
        rec = Rec(
            golden=g,
            seq=self.seq,
            role="migration_new" if migration else "duplicate",
            entity=entity,
            card_name=name,
            foreign_name=self.foreign_name(g, name, rng),
            tax_id=tax,
            create_date=create,
            family=src.family if migration else None,
            dup_of=src,
            dup_type=dup_type,
            tax_state=state,
            **self._common(g, entity, rng, dup=True),
        )
        g.records.append(rec)
        return rec


@dataclass(eq=False)
class Slot:
    golden: Golden
    source: Rec
    migration: bool
    switch_idx: int | None = None
    dup_type: str | None = None
    name: str | None = None


def build_master(params: dict, seed: int) -> Master:
    golden = build_golden(params, seed)
    assign_lifecycle(golden, params, seed)
    ent = params["entities"]
    maker = RecordMaker(params, seed)

    # 1. legitimate per-entity records (one per entity the customer buys from)
    for g in golden:
        fams = sorted(g.families, key=lambda f: (g.families[f], f))
        for i, f in enumerate(fams):
            maker.base(g, f, ent[f], primary=(i == 0))

    by_key = {g.spec.key: g for g in golden if g.spec.key}
    anchors = {g.idx for g in golden if g.spec.key}
    rng = stream(seed, "dups.select")

    # 2. customer/vendor twins (hard negatives, chosen first so they stay clean)
    n_cv = params["hard_negatives"]["customer_vendor_pairs"]
    cv = [by_key[cur.BIOMED]]
    for c in COUNTRY_ORDER[1:]:
        pool = [
            g
            for g in golden
            if g.country == c
            and g.segment == "distributor"
            and not g.spec.key
            and g.churn_idx is None
        ]
        cv.append(pool[int(rng.integers(len(pool)))])
    cv_taken = {g.idx for g in cv}
    pool = [
        g
        for g in golden
        if g.segment in ("distributor", "laboratory")
        and not g.spec.key
        and g.spec.group_id is None
        and g.spec.pair_key is None
        and g.idx not in cv_taken
    ]
    cv.extend(pool[int(i)] for i in rng.choice(len(pool), n_cv - len(cv), replace=False))
    cv_ids = {g.idx for g in cv}

    # 3. migrations (old record looks lost, new record looks new)
    mp = params["migrations"]
    n_mig = round(mp["share"] * len(golden))
    lo, hi = mp["switch_month_range"]

    def mig_ok(g: Golden, fam: str) -> bool:
        return (
            fam in g.families
            and g.families[fam] <= hi - 3
            and g.churn_idx is None
            and not g.is_new
            and g.idx not in anchors
            and g.idx not in cv_ids
        )

    vn_a = [g for g in golden if g.country == "VN" and mig_ok(g, "A")]
    mig: list[tuple[Golden, str]] = [
        (vn_a[int(i)], "A") for i in rng.choice(len(vn_a), mp["min_vn_product_a"], replace=False)
    ]
    chosen = {g.idx for g, _ in mig}
    rest = [g for g in golden if g.idx not in chosen and any(mig_ok(g, f) for f in g.families)]
    for i in rng.choice(len(rest), n_mig - len(mig), replace=False):
        g = rest[int(i)]
        fams = [f for f in sorted(g.families) if mig_ok(g, f)]
        mig.append((g, pick(rng, fams)))
    slots: list[Slot] = []
    for g, fam in mig:
        src = next(r for r in g.records if r.family == fam)
        s_lo = max(lo, g.families[fam] + 3)
        slots.append(Slot(g, src, True, switch_idx=int(rng.integers(s_lo, hi + 1))))

    # 4. anchor duplicates (demo storyline)
    nuh, rscm, sir = by_key[cur.NUH], by_key[cur.RSCM], by_key[cur.SIRIRAJ]
    slots.append(Slot(nuh, nuh.records[0], False, dup_type="abbreviation", name="NUH"))
    slots.append(
        Slot(
            nuh,
            nuh.records[0],
            False,
            dup_type="suffix_punctuation",
            name="NATIONAL UNIVERSITY HOSPITAL (S) PTE. LTD.",
        )
    )
    slots.append(
        Slot(
            rscm,
            rscm.records[0],
            False,
            dup_type="local_language",
            name="Rumah Sakit Cipto Mangunkusumo",
        )
    )
    slots.append(Slot(rscm, rscm.records[0], False, dup_type="local_language", name="RSCM"))
    slots.append(
        Slot(sir, sir.records[0], False, dup_type="local_language", name="Siriraj Hospital")
    )

    # 5. other customers with true duplicates
    dp = params["duplicates"]
    n_dup_golden = round(dp["golden_with_dup_share"] * len(golden))
    have = {s.golden.idx for s in slots}
    pool = [g for g in golden if g.idx not in have and g.idx not in anchors and g.idx not in cv_ids]
    for i in rng.choice(len(pool), n_dup_golden - len(have), replace=False):
        g = pool[int(i)]
        for _ in range(1 + int(rng.random() < dp["second_dup_prob"])):
            slots.append(Slot(g, g.records[int(rng.integers(len(g.records)))], False))

    assign_dup_types(slots, golden, params, seed)

    # 6. materialise duplicate records
    drng = stream(seed, "dups.records")
    for s in slots:
        src = s.source
        if s.dup_type == "cross_entity_recreate" or drng.random() >= dp["same_entity_prob"]:
            entity = pick(drng, [e for e in ENTITIES if e != src.entity])
        else:
            entity = src.entity
        if s.migration:
            create = add_days(month_date(s.switch_idx), -int(drng.integers(0, 46)))
        else:
            lo_d = add_days(src.create_date, 60)
            span = max(1, (WINDOW_END - lo_d).days)
            create = (
                add_days(lo_d, int(drng.integers(0, span))) if lo_d < WINDOW_END else WINDOW_END
            )
        maker.duplicate(src, s.name, s.dup_type, entity, create, drng, s.migration)

    # 7. CardCodes in creation order
    records = [r for g in golden for r in g.records]
    records.sort(key=lambda r: (r.create_date, r.seq))
    for i, r in enumerate(records):
        r.card_code = f"C{i + 1:05d}"

    dup_pairs = []
    migrations = []
    for g in golden:
        for r in g.records:
            if r.dup_of is not None:
                dup_pairs.append(
                    [
                        g.golden_id,
                        r.dup_of.card_code,
                        r.card_code,
                        r.dup_type,
                        r.tax_state,
                        r.role == "migration_new",
                        r.dup_of.entity,
                        r.entity,
                    ]
                )
    for s in slots:
        if s.migration:
            new = next(
                r for r in s.golden.records if r.dup_of is s.source and r.role == "migration_new"
            )
            migrations.append(
                [
                    s.golden.golden_id,
                    s.source.card_code,
                    new.card_code,
                    month_str(s.switch_idx),
                    s.golden.country,
                    s.source.entity,
                    s.source.family,
                ]
            )
    dup_pairs.sort(key=lambda row: (row[1], row[2]))
    migrations.sort(key=lambda row: row[1])
    return Master(golden, records, dup_pairs, migrations, cv)


def assign_dup_types(slots: list[Slot], golden: list[Golden], params: dict, seed: int) -> None:
    """Fill the §4.1 type quota; each type goes to slots whose source name it applies to."""
    rng = stream(seed, "dups.types")
    shares = params["duplicates"]["type_shares"]
    quota = largest_remainder(len(slots), {t: shares[t] for t in DUP_TYPES})
    for s in slots:
        if s.dup_type:
            quota[s.dup_type] -= 1
    # CardName -> golden idx: a duplicate must never collide with another customer's name
    taken: dict[str, int] = {}
    for g in golden:
        for r in g.records:
            taken.setdefault(r.card_name.lower(), g.idx)
    # names already used by each customer (records + assigned duplicates)
    own: dict[int, set[str]] = {}
    for g in golden:
        own[g.idx] = {r.card_name for r in g.records}
    for s in slots:
        if s.name:
            own[s.golden.idx].add(s.name)
    order = [
        "diacritics",
        "local_language",
        "abbreviation",
        "cross_entity_recreate",
        "suffix_punctuation",
        "typo",
        "missing_tax_id",
    ]

    def try_slot(s: Slot, t: str) -> bool:
        sources = [s.source] + [
            r
            for r in s.golden.records
            if r is not s.source and r.role in ("primary", "entity_record") and not s.migration
        ]
        for src in sources:
            name = TRANSFORMS[t](src.card_name, s.golden.spec, rng)
            if name is None:
                continue
            owner = taken.get(name.lower())
            if owner is not None and owner != s.golden.idx:
                continue
            if t != "missing_tax_id" and name in own[s.golden.idx]:
                continue
            s.source, s.dup_type, s.name = src, t, name
            own[s.golden.idx].add(name)
            return True
        return False

    for t in order:
        need = quota[t]
        for i in rng.permutation(len(slots)):
            if need <= 0:
                break
            s = slots[int(i)]
            if s.dup_type is None and try_slot(s, t):
                need -= 1
        quota[t] = need
    for s in slots:  # anything left over (should be rare)
        if s.dup_type is None and not try_slot(s, "typo"):
            try_slot(s, "missing_tax_id")
    # register anchor-fixed names
    for s in slots:
        if s.name is None:
            raise RuntimeError("unassigned duplicate slot")


# --------------------------------------------------------------------------------------------
# Rows
# --------------------------------------------------------------------------------------------

GOLDEN_COLS = [
    "golden_id",
    "legal_name",
    "local_name",
    "romanised_name",
    "aliases",
    "country",
    "city",
    "segment",
    "tax_id",
    "group_id",
    "phone",
    "email_domain",
    "start_month",
    "churn_month",
    "true_products",
]
BP_COLS = [
    "CardCode",
    "CardName",
    "CardForeignName",
    "CardType",
    "GroupCode",
    "FederalTaxID",
    "Currency",
    "PayTermsGrpCode",
    "CreditLimit",
    "EmailAddress",
    "Phone1",
    "City",
    "Country",
    "U_Entity",
    "CreateDate",
    "CreatedBy",
]


def golden_rows(m: Master) -> list[list]:
    rows = []
    for g in m.golden:
        s = g.spec
        aliases = list(
            dict.fromkeys(
                a
                for a in [s.english, *s.acronyms, *s.lang_alts, s.legal_rom]
                if a not in (s.legal, s.local)
            )
        )
        products = {f: month_str(g.families[f]) for f in sorted(g.families)}
        rows.append(
            [
                g.golden_id,
                s.legal,
                s.local,
                s.rom,
                json.dumps(aliases, ensure_ascii=False),
                s.country,
                s.city,
                s.segment,
                g.tax_id,
                s.group_id or "",
                format_phone(s.country, g.phone_area, g.phone_sub, 0),
                g.email_domain,
                month_str(g.start_idx),
                month_str(g.churn_idx),
                json.dumps(products, ensure_ascii=False, sort_keys=True),
            ]
        )
    return rows


def bp_rows(m: Master, params: dict) -> list[list]:
    return [
        [
            r.card_code,
            r.card_name,
            r.foreign_name,
            "cCustomer",
            r.group_code,
            r.tax_id,
            params["countries"][r.golden.country]["currency"],
            r.pay_terms,
            r.credit_limit,
            r.email,
            r.phone,
            r.city,
            r.golden.country,
            r.entity,
            r.create_date.isoformat(),
            r.created_by,
        ]
        for r in m.records
    ]


def golden_map_rows(m: Master) -> list[list]:
    return [
        [
            r.card_code,
            r.golden.golden_id,
            r.role,
            r.dup_of.card_code if r.dup_of else "",
            r.family or "",
        ]
        for r in m.records
    ]


def churn_rows(m: Master) -> list[list]:
    return [
        [
            g.golden_id,
            g.country,
            month_str(g.churn_idx - g.decline_months),
            month_str(g.churn_idx),
            g.decline_months,
        ]
        for g in m.golden
        if g.churn_idx is not None
    ]


def hard_negative_rows(m: Master, vendor_codes: dict[int, str]) -> list[list]:
    rows = []
    for g in m.cv_golden:
        for r in g.records:
            rows.append(
                [
                    r.card_code,
                    vendor_codes[g.idx],
                    "customer_vendor_pair",
                    g.golden_id,
                    g.golden_id,
                    g.spec.group_id or "",
                    "same legal entity as customer and supplier (B1 needs both)",
                ]
            )

    def cross(ga: Golden, gb: Golden, reason: str, note: str) -> None:
        for ra, rb in itertools.product(ga.records, gb.records):
            a, b = sorted([ra.card_code, rb.card_code])
            rows.append(
                [
                    a,
                    b,
                    reason,
                    ra.golden.golden_id if a == ra.card_code else rb.golden.golden_id,
                    rb.golden.golden_id if b == rb.card_code else ra.golden.golden_id,
                    ga.spec.group_id or "",
                    note,
                ]
            )

    groups: dict[str, list[Golden]] = {}
    pairs: dict[str, list[Golden]] = {}
    for g in m.golden:
        if g.spec.group_id:
            groups.setdefault(g.spec.group_id, []).append(g)
        if g.spec.pair_key:
            pairs.setdefault(g.spec.pair_key, []).append(g)
    for gid in sorted(groups):
        for ga, gb in itertools.combinations(groups[gid], 2):
            if ga.country != gb.country:
                cross(
                    ga,
                    gb,
                    "same_group_other_country",
                    f"{cur.GROUPS[gid]}: {ga.country} vs {gb.country}",
                )
    for pk in sorted(pairs):
        for ga, gb in itertools.combinations(pairs[pk], 2):
            cross(ga, gb, "similar_name_different_site", f"{pk}: different site / legal entity")
    rows.sort(key=lambda r: (r[2], r[0], r[1]))
    return rows

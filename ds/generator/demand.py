"""Demand DGP (data-spec §6) -> orders, enquiries and the spreadsheet-leakage view (§7, §7.1).

Per golden customer x product family x month. The record that carries an order is the record
that holds that golden x family at that month: the primary / entity record, and from the
migration `switch_month` onwards the migration's new record (D-015). The order's `entity`
comes from the product family (A->SPD, B->QTS, C->QTG), not from the record's `U_Entity`.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
from anyascii import anyascii

from . import curated as cur
from .catalog import ITEMS
from .common import month_date, stream
from .master import Golden, Master, Rec

N_MONTHS = 36
ORDER_COLS = [
    "doc_num",
    "card_code",
    "entity",
    "country",
    "item_code",
    "qty",
    "unit_price_usd",
    "doc_date",
    "po_ref",
    "source_email_id",
]
ENQUIRY_COLS = ORDER_COLS + ["kind", "converted_doc_num"]
DIRTY_COLS = ORDER_COLS + ["leak_source", "source_ref"]

PRICE = {it[0]: it[4] for it in ITEMS}
FAMILY_ITEMS = {f: [it[0] for it in ITEMS if it[2] == f] for f in "ABC"}

# Real holiday months, hard-coded (weight of the month in that year's dip).
# CNY / Tet: 10 Feb 2024, 29 Jan 2025, 17 Feb 2026.
CNY = {2024: {2: 1.0}, 2025: {1: 1.0}, 2026: {2: 1.0}}
# Eid al-Fitr (Lebaran / Hari Raya): 10 Apr 2024; 31 Mar 2025 (collective leave runs into
# April, so split); 20 Mar 2026.
LEBARAN = {2024: {4: 1.0}, 2025: {3: 0.5, 4: 0.5}, 2026: {3: 1.0}}
SONGKRAN = {y: {4: 1.0} for y in (2023, 2024, 2025, 2026)}  # 13-15 April every year


def season_mult(country: str, t: int, sp: dict, on: bool) -> float:
    if not on:
        return 1.0
    d = month_date(t)
    m = 1.0
    if d.month in sp["budget_flush"]["months"]:
        m *= sp["budget_flush"]["mult"]
    for key, table in (("cny_dip", CNY), ("ramadan_dip", LEBARAN), ("songkran_dip", SONGKRAN)):
        if country in sp[key]["countries"]:
            w = table.get(d.year, {}).get(d.month, 0.0)
            m *= 1.0 - (1.0 - sp[key]["mult"]) * w
    return m


def business_days(year: int, month: int) -> list[date]:
    n = calendar.monthrange(year, month)[1]
    return [date(year, month, d) for d in range(1, n + 1) if date(year, month, d).weekday() < 5]


def nb_qty(rng: np.random.Generator, mean: float, k: float) -> int:
    """1 + NegativeBinomial with the given mean of the extra units and size k."""
    extra = max(mean - 1.0, 1e-3)
    return 1 + int(rng.negative_binomial(k, k / (k + extra)))


@dataclass
class Doc:
    card_code: str
    golden_id: str
    family: str
    entity: str
    country: str
    doc_date: date
    lines: list[tuple[str, int, float]]
    po_ref: str = ""
    doc_num: int = 0
    source_email_id: str = ""
    kind: str = ""
    converted_doc_num: int | None = None


@dataclass
class Demand:
    orders: list[Doc]
    enquiries: list[Doc]
    active: list[tuple[Golden, str, int, str, float]] = field(default_factory=list)
    # (golden, family, month idx, card_code, mean units per order)


def _holders(m: Master) -> dict[tuple[str, str], tuple[Rec, Rec | None, int | None]]:
    """(golden_id, family) -> (base record, migration new record, switch month index)."""
    sw: dict[str, int] = {}
    for row in m.migrations:
        d = date.fromisoformat(row[3])
        sw[row[2]] = (d.year - 2023) * 12 + d.month - 10
    out = {}
    for g in m.golden:
        for r in g.records:
            if r.role in ("primary", "entity_record"):
                out[(g.golden_id, r.family)] = (r, None, None)
        for r in g.records:
            if r.role == "migration_new":
                base = out[(g.golden_id, r.family)][0]
                out[(g.golden_id, r.family)] = (base, r, sw[r.card_code])
    return out


def _price(rng: np.random.Generator, item: str, noise: float) -> float:
    return round(PRICE[item] * float(rng.uniform(1 - noise, 1 + noise)), 2)


def _pick_items(rng: np.random.Generator, items: list[str], prefs: np.ndarray, n: int) -> list[str]:
    idx = rng.choice(len(items), size=n, replace=False, p=prefs)
    return [items[int(i)] for i in sorted(idx)]


def build_orders(m: Master, params: dict, seed: int) -> Demand:
    dp = params["demand"]
    ent = params["entities"]
    holders = _holders(m)
    docs: list[Doc] = []
    active: list[tuple[Golden, str, int, str, float]] = []
    for g in m.golden:
        for fam in sorted(g.families):
            base, new, switch = holders[(g.golden_id, fam)]
            rng = stream(seed, f"demand.{g.golden_id}.{fam}")
            mean0 = dp["lambda_mean"][fam][g.segment] * dp["country_size"][g.country]
            lam = float(rng.gamma(dp["lambda_shape"], mean0 / dp["lambda_shape"]))
            small = bool(rng.random() < dp["small_customer_prob"][g.segment])
            if fam in ("A", "B"):
                w = np.array([dp["item_weights"][fam][i] for i in FAMILY_ITEMS[fam]])
                prefs = rng.dirichlet(w / w.sum() * dp["item_pref_concentration"])
                prefs = prefs / prefs.sum()
            p_b = float(rng.uniform(dp["p_order"]["B"]["low"], dp["p_order"]["B"]["high"]))
            cc = dp["c_contract"]
            cycle = 3 if rng.random() < cc["quarterly_prob"] else 12
            ann = list(cc["annual_items"])
            annual_item = ann[int(rng.choice(len(ann), p=list(cc["annual_items"].values())))]
            growth = (1 + dp["trend_annual"][g.country]) * (1 + dp["trend_extra"][fam])
            k = dp["nb_dispersion"][fam]
            adopt = g.families[fam]
            for t in range(max(0, adopt), N_MONTHS):
                cf = 1.0
                if g.churn_idx is not None:
                    if t >= g.churn_idx:
                        break
                    if t >= g.churn_idx - g.decline_months:
                        cf = (g.churn_idx - t) / (g.decline_months + 1)
                code = new.card_code if (new is not None and t >= switch) else base.card_code
                trend = growth ** (t / 12)
                season = season_mult(g.country, t, dp["season"], dp["seasonality_on"])
                noise = float(np.exp(rng.normal(0.0, dp["extra_noise_sigma"])))
                mean = lam * trend * season * noise * (0.5 + 0.5 * cf)
                active.append((g, fam, t, code, max(mean, 1.0)))
                u_order, u_tender, u_day = rng.random(), rng.random(), rng.random()
                lines: list[tuple[str, int]] = []
                if fam == "A":
                    p = dp["p_order"]["A"]["small" if small else "large"] * cf
                    if u_order < p:
                        qty = nb_qty(rng, mean, k)
                        if (
                            g.segment in dp["tender"]["segments"]
                            and u_tender < dp["tender"]["prob"]
                        ):
                            lo, hi = dp["tender"]["mult_range"]
                            qty = int(round(qty * float(rng.uniform(lo, hi))))
                        n_lines = 2 if (rng.random() < dp["second_line_prob"] and qty >= 2) else 1
                        items = _pick_items(rng, FAMILY_ITEMS["A"], prefs, n_lines)
                        if n_lines == 2:
                            q1 = 1 + int(rng.binomial(qty - 2, 0.6))
                            lines = [(items[0], q1), (items[1], qty - q1)]
                        else:
                            lines = [(items[0], qty)]
                elif fam == "B":
                    if u_order < p_b * cf:
                        qty = nb_qty(rng, 1.0 + mean, k)
                        if (
                            g.segment in dp["tender"]["segments"]
                            and u_tender < dp["tender"]["prob"] * 5
                        ):
                            lo, hi = dp["tender"]["mult_range"]
                            qty = int(round(qty * float(rng.uniform(lo, hi))))
                        lines = [(_pick_items(rng, FAMILY_ITEMS["B"], prefs, 1)[0], qty)]
                else:
                    if (t - adopt) % cycle == 0 and u_order < cc["renewal_prob"] * cf:
                        item = annual_item if cycle == 12 else cc["quarterly_item"]
                        lines.append((item, nb_qty(rng, mean, k)))
                    if u_tender < dp["p_order"]["C_adhoc"] * cf:
                        adh = list(cc["adhoc_items"])
                        it = adh[int(rng.choice(len(adh), p=list(cc["adhoc_items"].values())))]
                        lines.append((it, 1))
                if not lines:
                    continue
                d0 = month_date(t)
                days = business_days(d0.year, d0.month)
                doc_date = days[min(int(u_day * len(days)), len(days) - 1)]
                priced = [(it, q, _price(rng, it, dp["price_noise"])) for it, q in lines]
                docs.append(Doc(code, g.golden_id, fam, ent[fam], g.country, doc_date, priced))
    docs.sort(key=lambda d: (d.doc_date, d.card_code, d.family, d.lines[0][0]))
    for i, d in enumerate(docs):
        d.doc_num = 100001 + i
    _assign_po_refs(m, docs, params, seed)
    return Demand(docs, [], active)


def _acronym(g: Golden) -> str:
    if g.spec.acronyms:
        return g.spec.acronyms[0]
    words = re.findall(r"[A-Za-z]+", anyascii(g.spec.english))
    words = [w for w in words if w.lower() not in ("the", "and", "of", "pte", "ltd", "sdn", "bhd")]
    acr = "".join(w[0].upper() for w in words)[:5]
    return acr if len(acr) >= 2 else "PO"


def _assign_po_refs(m: Master, docs: list[Doc], params: dict, seed: int) -> None:
    """Each customer has its own PO number style and running sequence."""
    blank_p = params["demand"]["po_ref_blank_prob"]
    by_gid = {g.golden_id: g for g in m.golden}
    state: dict[str, dict] = {}
    for d in docs:
        g = by_gid[d.golden_id]
        st = state.get(g.golden_id)
        if st is None:
            rng = stream(seed, f"demand.poref.{g.golden_id}")
            style = 1 if g.spec.key == cur.RSCM else int(rng.integers(4))
            st = state[g.golden_id] = {
                "rng": rng,
                "style": style,
                "acr": _acronym(g),
                "n": int(rng.integers(10000, 60000)),
                "year": None,
                "seq": 0,
            }
        rng = st["rng"]
        if d.doc_date.year != st["year"]:
            st["year"] = d.doc_date.year
            st["seq"] = 41 if g.spec.key == cur.RSCM else int(rng.integers(1, 80))
        else:
            st["seq"] += int(rng.integers(1, 7))
        st["n"] += int(rng.integers(1, 40))
        blank = rng.random() < blank_p and g.spec.key != cur.RSCM
        if blank:
            continue
        y, s = d.doc_date.year, st["seq"]
        d.po_ref = [
            f"PO-{st['n']:05d}",
            f"{st['acr']}/{y}/{s:03d}",
            f"PR{y}{s:04d}",
            f"{s:04d}/PO/{y % 100:02d}",
        ][st["style"]]


# --------------------------------------------------------------------------------------------
# Enquiries and purchase requests (§7)
# --------------------------------------------------------------------------------------------


def build_enquiries(m: Master, dem: Demand, params: dict, seed: int) -> list[Doc]:
    ep, dp = params["enquiries"], params["demand"]
    rng = stream(seed, "demand.enquiries")
    create = {r.card_code: r.create_date for r in m.records}
    start = month_date(0)
    out: list[Doc] = []
    n_conv = {"purchase_request": 0, "enquiry": 0}
    for d in dem.orders:
        for kind, rate in (
            ("purchase_request", ep["pr_per_order"][d.family]),
            ("enquiry", ep["enq_per_order"][d.family]),
        ):
            if rng.random() >= rate:
                continue
            lead = int(rng.integers(ep["lead_days"][0], ep["lead_days"][1] + 1))
            when = d.doc_date - timedelta(days=lead)
            while when.weekday() >= 5:
                when -= timedelta(days=1)
            if when < start or when < create[d.card_code]:
                continue
            lines = [
                (it, max(1, int(round(q * float(rng.uniform(0.8, 1.25))))), p)
                for it, q, p in d.lines
            ]
            out.append(
                Doc(
                    d.card_code,
                    d.golden_id,
                    d.family,
                    d.entity,
                    d.country,
                    when,
                    lines,
                    kind=kind,
                    converted_doc_num=d.doc_num,
                )
            )
            n_conv[kind] += 1
    # non-converting rows bring the conversion rate to the §7 targets
    for kind, rate in (
        ("purchase_request", ep["pr_conversion"]),
        ("enquiry", ep["enq_conversion"]),
    ):
        n_non = int(round(n_conv[kind] * (1 - rate) / rate))
        if kind == "enquiry":
            # enquiries lean towards capital equipment and services
            weights = np.array([{"A": 1.0, "B": 6.0, "C": 2.0}[a[1]] for a in dem.active])
        else:
            weights = np.array([{"A": 1.0, "B": 3.0, "C": 1.5}[a[1]] for a in dem.active])
        picks = rng.choice(len(dem.active), size=n_non, replace=True, p=weights / weights.sum())
        for i in picks:
            g, fam, t, code, mean = dem.active[int(i)]
            d0 = month_date(t)
            days = business_days(d0.year, d0.month)
            when = days[int(rng.integers(len(days)))]
            if when < create[code]:
                when = max(when, create[code])
            if fam == "C":
                item = str(rng.choice(FAMILY_ITEMS["C"]))
                qty = 1 + int(rng.integers(0, 3))
            else:
                w = np.array([dp["item_weights"][fam][x] for x in FAMILY_ITEMS[fam]])
                item = FAMILY_ITEMS[fam][int(rng.choice(5, p=w / w.sum()))]
                qty = nb_qty(rng, mean if fam == "A" else 1.5, dp["nb_dispersion"][fam])
            lines = [(item, qty, _price(rng, item, dp["price_noise"]))]
            out.append(
                Doc(
                    code,
                    g.golden_id,
                    fam,
                    params["entities"][fam],
                    g.country,
                    when,
                    lines,
                    kind=kind,
                )
            )
    out.sort(key=lambda d: (d.doc_date, d.card_code, d.kind, d.lines[0][0], d.lines[0][1]))
    for i, d in enumerate(out):
        d.doc_num = 700001 + i
    return out


# --------------------------------------------------------------------------------------------
# Rows
# --------------------------------------------------------------------------------------------


def _doc_rows(d: Doc) -> list[list]:
    return [
        [
            d.doc_num,
            d.card_code,
            d.entity,
            d.country,
            it,
            q,
            f"{p:.2f}",
            d.doc_date.isoformat(),
            d.po_ref,
            d.source_email_id,
        ]
        for it, q, p in d.lines
    ]


def order_rows(dem: Demand) -> list[list]:
    return [r for d in dem.orders for r in _doc_rows(d)]


def enquiry_rows(enqs: list[Doc]) -> list[list]:
    return [
        r + [d.kind, d.converted_doc_num if d.converted_doc_num else ""]
        for d in enqs
        for r in _doc_rows(d)
    ]


def dirty_rows(
    m: Master,
    dem: Demand,
    enqs: list[Doc],
    mdm_reqs: list[dict],
    params: dict,
    seed: int,
) -> list[list]:
    """Today's spreadsheet: confirmed POs + leaked enquiries / PRs + leaked MDM emails."""
    lp, dp = params["leakage"], params["demand"]
    rng = stream(seed, "demand.leakage")
    rows = [r + ["confirmed_po", d.doc_num] for d in dem.orders for r in _doc_rows(d)]
    # exact shares: pick round(share x n) docs / requests without replacement
    n_enq = int(round(lp["enquiry_share"] * len(enqs)))
    leak_enq = set(int(i) for i in rng.choice(len(enqs), n_enq, replace=False))
    for i, d in enumerate(enqs):
        if i in leak_enq:
            for r in _doc_rows(d):
                rows.append(r + [d.kind, d.doc_num])
    fam_of = {v: k for k, v in params["entities"].items()}
    by_country_entity: dict[tuple[str, str], list[Rec]] = {}
    for r in m.records:
        by_country_entity.setdefault((r.golden.country, r.entity), []).append(r)
    n_mdm = int(round(lp["mdm_share"] * len(mdm_reqs)))
    leak_mdm = set(int(i) for i in rng.choice(len(mdm_reqs), n_mdm, replace=False))
    for i, req in enumerate(mdm_reqs):
        if i not in leak_mdm:
            continue
        sub = date.fromisoformat(req["submitted_at"][:10])
        pool = [
            r
            for r in by_country_entity.get((req["country"], req["entity"]), [])
            if r.create_date <= sub
        ]
        if not pool:
            continue
        rec = pool[int(rng.integers(len(pool)))]
        fam = fam_of[req["entity"]]
        item = FAMILY_ITEMS[fam][int(rng.integers(5))]
        mean = dp["lambda_mean"][fam]["laboratory"] if fam == "A" else 1.5
        qty = nb_qty(rng, mean, dp["nb_dispersion"][fam])
        rows.append(
            [
                "",
                rec.card_code,
                req["entity"],
                req["country"],
                item,
                qty,
                f"{_price(rng, item, dp['price_noise']):.2f}",
                sub.isoformat(),
                "",
                "",
                "mdm_request",
                req["req_id"],
            ]
        )
    rows.sort(key=lambda r: (r[7], r[1], str(r[0]), r[4], r[10]))
    return rows

"""Generator v2 checks: users, demand, enquiries, leakage, old-process history, inbox, fixtures
(docs/data-spec.md §6-11, D-003, D-015), plus master-data checks QA flagged as missing in v1."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import get_args

import pandas as pd
import pytest
from anyascii import anyascii

from ds.generator.core import generate, load_params
from ds.generator.demand import season_mult
from ds.generator.emails import CLASSES, check_bank_free
from ds.generator.fixtures import freeze
from services.api.personas import PERSONAS
from services.api.schemas import Role

SCENARIO, SEED = "seasonal_trend", 42
FAMILY_ENTITY = {"A": "SPD", "B": "QTS", "C": "QTG"}
CURRENCY = {"SG": "SGD", "MY": "MYR", "ID": "IDR", "VN": "VND", "TH": "THB"}
TAX_RE = {  # D-003 synthetic formats (NPWP dots optional)
    "SG": r"\d{9}[A-Z]|\d{8}[A-Z]",
    "MY": r"\d{12}",
    "ID": r"\d{2}\.\d{3}\.\d{3}\.\d-\d{3}\.\d{3}|\d{15}",
    "VN": r"\d{10}",
    "TH": r"\d{13}",
}


@pytest.fixture(scope="module")
def out(tmp_path_factory) -> Path:
    return generate(SCENARIO, SEED, tmp_path_factory.mktemp("gen_v2"))


def _csv(out: Path, name: str) -> pd.DataFrame:
    return pd.read_csv(out / name, dtype=str, keep_default_na=False)


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture(scope="module")
def bp(out):
    return _csv(out, "bp_records.csv")


@pytest.fixture(scope="module")
def gmap(out):
    return _csv(out, "ground_truth/bp_golden_map.csv")


@pytest.fixture(scope="module")
def golden(out):
    return _csv(out, "customers_golden.csv")


@pytest.fixture(scope="module")
def orders(out):
    o = _csv(out, "orders.csv")
    o["qty"] = o.qty.astype(int)
    return o


@pytest.fixture(scope="module")
def emails(out):
    return _jsonl(out / "emails.jsonl")


@pytest.fixture(scope="module")
def labels(out):
    return {x["email_id"]: x for x in _jsonl(out / "ground_truth/email_labels.jsonl")}


def within(x: float, target: float, tol: float = 0.10) -> bool:
    return abs(x - target) <= tol * target


# ------------------------------------------------------------------------- master (QA gaps)


def test_tax_id_formats_per_country(bp, golden, out):
    for c, tax in zip(golden.country, golden.tax_id, strict=True):
        assert re.fullmatch(TAX_RE[c], tax), (c, tax)
    d = _csv(out, "ground_truth/dup_pairs.csv")
    malformed = set(d.card_code_b[d.tax_id_state == "malformed"])
    assert malformed, "missing_tax_id duplicates should include malformed tax IDs"
    assert set(d.dup_type[d.card_code_b.isin(malformed)]) == {"missing_tax_id"}
    bad = {
        code
        for code, c, tax in zip(bp.CardCode, bp.Country, bp.FederalTaxID, strict=True)
        if tax and not re.fullmatch(TAX_RE[c], tax)
    }
    # every ill-formed tax ID is a labelled malformed duplicate (identifiable via ground truth)
    assert bad <= malformed, sorted(bad - malformed)
    # and every labelled malformed tax ID differs from the customer's real one
    gid_of = dict(zip(gmap_codes(out), gmap_gids(out), strict=True))
    real = dict(zip(golden.golden_id, golden.tax_id, strict=True))
    norm = lambda s: re.sub(r"[.\-\s]", "", s).upper()  # noqa: E731
    by_code = dict(zip(bp.CardCode, bp.FederalTaxID, strict=True))
    for code in malformed:
        assert norm(by_code[code]) != norm(real[gid_of[code]]), code
    # every well-formed, non-blank tax ID on a record is the customer's own
    for code, tax in by_code.items():
        if tax and code not in malformed:
            assert norm(tax) == norm(real[gid_of[code]]), code


def gmap_codes(out):
    return _csv(out, "ground_truth/bp_golden_map.csv").CardCode


def gmap_gids(out):
    return _csv(out, "ground_truth/bp_golden_map.csv").golden_id


def test_currency_per_country(bp, out):
    assert (bp.Currency == bp.Country.map(CURRENCY)).all()
    v = _csv(out, "vendors.csv")
    home = v[v.Country.isin(CURRENCY)]
    assert (home.Currency == home.Country.map(CURRENCY)).all()


BANK_COL = re.compile(r"(?i)bank|account|iban|bic|swift")


def test_bank_fields_only_in_vendors(out):
    for p in out.rglob("*.csv"):
        cols = list(pd.read_csv(p, nrows=0).columns)
        hits = [c for c in cols if BANK_COL.search(c)]
        if p.name == "vendors.csv":
            assert {"BankCode", "AccountNo", "IBAN", "BICSwiftCode"} <= set(cols)
        else:
            assert not hits, (p.name, hits)


def test_one_entity_record_per_family(gmap, golden, bp):
    ent = dict(zip(bp.CardCode, bp.U_Entity, strict=True))
    base = gmap[gmap.record_role.isin(["primary", "entity_record"])]
    assert (gmap.record_role == "primary").sum() == len(golden)
    assert base.groupby("golden_id").record_role.apply(lambda s: (s == "primary").sum()).eq(1).all()
    for gid, products in zip(golden.golden_id, golden.true_products, strict=True):
        fams = set(json.loads(products))
        rows = base[base.golden_id == gid]
        assert sorted(rows.family) == sorted(fams), gid
        for code, fam in zip(rows.CardCode, rows.family, strict=True):
            assert ent[code] == FAMILY_ENTITY[fam], (gid, code, fam)


def test_names_are_nfc(bp, golden, out, emails):
    for s in [*bp.CardName, *bp.CardForeignName, *golden.legal_name, *golden.local_name]:
        assert unicodedata.is_normalized("NFC", s), s
    for s in _csv(out, "vendors.csv").CardName:
        assert unicodedata.is_normalized("NFC", s), s
    for e in emails:
        assert unicodedata.is_normalized("NFC", e["body"]), e["email_id"]


# ------------------------------------------------------------------------- users (D-015)


def test_users_match_personas(out, bp):
    u = _csv(out, "users.csv")
    assert list(u.columns) == [
        "user_id",
        "name",
        "title",
        "roles",
        "entity",
        "country",
        "backup_for",
    ]
    assert u.user_id.is_unique
    by_id = u.set_index("user_id")
    for p in PERSONAS:
        r = by_id.loc[p.user_id]
        assert (r["name"], r.title, r.roles.split("|"), r.entity, r.country) == (
            p.name,
            p.title,
            list(p.roles),
            p.entity,
            p.country,
        )
    valid = set(get_args(Role))
    for roles in u.roles:
        assert set(roles.split("|")) <= valid, roles
    user_roles = dict(zip(u.user_id, u.roles.str.split("|"), strict=True))
    backups = u[u.backup_for != ""]
    for role in ["bu_head", "finance", "quality_regulatory", "business_support", "mdm_analyst"]:
        b = backups[backups.roles.str.split("|").map(lambda rs, r=role: r in rs)]
        assert len(b) >= 1, role
        for target in b.backup_for:
            assert role in user_roles[target], (role, target)
    assert set(bp.CreatedBy) <= set(u.user_id)
    v = _csv(out, "vendors.csv")
    home = v[v.Country.isin(CURRENCY)]
    assert set(home.CreatedBy) <= set(u.user_id)


def _approvers(u: pd.DataFrame, role: str) -> pd.DataFrame:
    return u[u.roles.str.split("|").map(lambda rs: role in rs)]


def test_approver_coverage(out):
    """D-007 routing: a BU Head per entity and a Q/R approver per country, each with a backup."""
    u = _csv(out, "users.csv")
    for role, key, values in [
        ("bu_head", "entity", ["SPD", "QTS", "QTG"]),
        ("quality_regulatory", "country", ["SG", "MY", "ID", "VN", "TH"]),
    ]:
        a = _approvers(u, role)
        for v in values:
            primary = a[(a[key] == v) & (a.backup_for == "")]
            assert len(primary) == 1, (role, v, list(primary.user_id))
            pid = primary.user_id.iloc[0]
            backup = a[a.backup_for == pid]
            assert len(backup) == 1, (role, v)
            assert backup[key].iloc[0] == v or key == "entity" and backup.entity.iloc[0] == v
    assert _approvers(u, "quality_regulatory").set_index("user_id").loc["lan", "backup_for"] == ""
    for role in ["finance", "business_support", "mdm_analyst"]:
        a = _approvers(u, role)
        assert (a.backup_for != "").any(), role
    # no backup points at a user who lacks the role
    roles = dict(zip(u.user_id, u.roles.str.split("|"), strict=True))
    for uid, r, target in zip(u.user_id, u.roles, u.backup_for, strict=True):
        if target:
            assert set(r.split("|")) <= set(roles[target]), (uid, target)


# ------------------------------------------------------------------------- demand (§6-7)


def test_season_calendar():
    sp = load_params(SCENARIO)["demand"]["season"]
    idx = lambda y, m: (y - 2023) * 12 + m - 10  # noqa: E731
    assert season_mult("VN", idx(2025, 1), sp, True) == pytest.approx(0.80)  # Tet 29 Jan 2025
    assert season_mult("SG", idx(2026, 2), sp, True) == pytest.approx(0.80)  # CNY 17 Feb 2026
    assert season_mult("TH", idx(2025, 2), sp, True) == pytest.approx(1.0)
    assert season_mult("ID", idx(2024, 4), sp, True) == pytest.approx(0.85)  # Lebaran 10 Apr
    assert season_mult("ID", idx(2026, 3), sp, True) == pytest.approx(0.85)  # Lebaran 20 Mar
    assert season_mult("TH", idx(2025, 4), sp, True) == pytest.approx(0.85)  # Songkran
    assert season_mult("MY", idx(2024, 11), sp, True) == pytest.approx(1.15)
    assert season_mult("VN", idx(2025, 1), sp, False) == 1.0


def test_orders_reference_entity_records(orders, bp, gmap):
    assert list(orders.columns) == [
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
    assert set(orders.card_code) <= set(bp.CardCode)
    # D-015: entity from the product family, not from the record's U_Entity
    assert (orders.entity == orders.item_code.str[0].map(FAMILY_ENTITY)).all()
    role = dict(zip(gmap.CardCode, gmap.record_role, strict=True))
    assert set(orders.card_code.map(role)) <= {"primary", "entity_record", "migration_new"}
    country = dict(zip(bp.CardCode, bp.Country, strict=True))
    assert (orders.card_code.map(country) == orders.country).all()
    created = dict(zip(bp.CardCode, bp.CreateDate, strict=True))
    assert (orders.doc_date >= orders.card_code.map(created)).all()
    assert orders.doc_date.min() >= "2023-10-01" and orders.doc_date.max() <= "2026-09-30"
    assert (orders.qty > 0).all()
    assert pd.to_datetime(orders.doc_date).dt.weekday.lt(5).all()
    # each doc is one customer, one entity, one date
    per_doc = orders.groupby("doc_num")[["card_code", "entity", "doc_date"]].nunique()
    assert (per_doc == 1).all().all()


def test_order_card_holds_the_family(orders, gmap):
    fam = dict(zip(gmap.CardCode, gmap.family, strict=True))
    assert (orders.card_code.map(fam) == orders.item_code.str[0]).all()


def test_migration_switch(out, orders):
    m = _csv(out, "ground_truth/migrations.csv")
    for old, new, sw, fam in zip(
        m.old_card_code, m.new_card_code, m.switch_month, m.product_family, strict=True
    ):
        o_old = orders[(orders.card_code == old) & (orders.item_code.str[0] == fam)]
        o_new = orders[orders.card_code == new]
        assert (o_old.doc_date < sw).all(), (old, sw)
        assert (o_new.doc_date >= sw).all(), (new, sw)
        if fam == "A":  # B (capital) and annual C contracts can be silent for a year
            assert len(o_old) > 0 and len(o_new) > 0, (old, new)
    # the demo needs Vietnam Product A migrations whose new record actually orders
    vn = m[(m.country == "VN") & (m.product_family == "A")]
    assert sum((orders.card_code == c).any() for c in vn.new_card_code) >= 3


def test_churners_stop_ordering(out, orders, gmap):
    ch = _csv(out, "ground_truth/churn.csv")
    gid = dict(zip(gmap.CardCode, gmap.golden_id, strict=True))
    last = orders.assign(g=orders.card_code.map(gid)).groupby("g").doc_date.max()
    for g, cm in zip(ch.golden_id, ch.churn_month, strict=True):
        if g in last:
            assert last[g] < cm, (g, last[g], cm)


def test_fifteen_series(orders):
    o = orders.assign(fam=orders.item_code.str[0], month=orders.doc_date.str[:7])
    series = o.groupby(["country", "fam"]).size()
    assert len(series) == 15
    a = o[o.fam == "A"].groupby(["country", "month"]).qty.sum()
    assert len(a) == 5 * 36, "Product A should have orders every month in every country"


def _fy(doc_date: pd.Series) -> pd.Series:
    """Fiscal year of the window: 1 = Oct 2023 - Sep 2024, ..., 3 = Oct 2025 - Sep 2026."""
    return (doc_date >= "2024-10-01").astype(int) + (doc_date >= "2025-10-01").astype(int) + 1


def test_same_customer_growth_follows_trend(orders, gmap):
    """VN (+18%/yr) beats SG (+1%/yr) for Product A on the same customers in FY1 and FY3, so
    the gap is the trend parameter, not new customers or cross-sell."""
    gid = dict(zip(gmap.CardCode, gmap.golden_id, strict=True))
    a = orders[orders.item_code.str[0] == "A"]
    a = a.assign(g=a.card_code.map(gid), fy=_fy(a.doc_date))
    per = a.groupby(["country", "g", "fy"]).qty.sum().unstack("fy").fillna(0)
    both = per[(per[1] > 0) & (per[3] > 0)]
    growth = both.groupby("country")[[1, 3]].sum()
    ratio = growth[3] / growth[1]
    assert ratio["VN"] > ratio["SG"] + 0.15, ratio.to_dict()
    assert ratio["ID"] > ratio["SG"], ratio.to_dict()
    assert 0.85 < ratio["SG"] < 1.2, ratio.to_dict()


def test_enquiries(out, orders):
    e = _csv(out, "enquiries.csv")
    assert list(e.columns)[-2:] == ["kind", "converted_doc_num"]
    assert set(e.kind) == {"enquiry", "purchase_request"}
    docs = e.drop_duplicates("doc_num")
    rate = docs.groupby("kind").converted_doc_num.apply(lambda s: (s != "").mean())
    assert abs(rate["purchase_request"] - 0.35) <= 0.05, rate
    assert abs(rate["enquiry"] - 0.10) <= 0.03, rate
    od = orders.drop_duplicates("doc_num").set_index("doc_num")
    conv = docs[docs.converted_doc_num != ""]
    for code, d, target in zip(conv.card_code, conv.doc_date, conv.converted_doc_num, strict=True):
        o = od.loc[target]
        assert o.card_code == code
        lag = (date.fromisoformat(o.doc_date) - date.fromisoformat(d)).days
        assert 0 < lag <= 62, (target, lag)
    assert not set(e.doc_num) & set(orders.doc_num)


def test_dirty_demand(out, orders):
    d = _csv(out, "dirty_demand.csv")
    assert set(d.leak_source) == {"confirmed_po", "enquiry", "purchase_request", "mdm_request"}
    assert (d.leak_source == "confirmed_po").sum() == len(orders)
    e = _csv(out, "enquiries.csv").drop_duplicates("doc_num")
    leaked = d[d.leak_source.isin(["enquiry", "purchase_request"])].source_ref.nunique()
    assert abs(leaked / len(e) - 0.10) <= 0.002
    h = _csv(out, "mdm_requests_history.csv")
    mdm = (d.leak_source == "mdm_request").sum()
    assert abs(mdm / len(h) - 0.05) <= 0.003
    assert d[d.leak_source == "mdm_request"].source_ref.isin(h.req_id).all()
    # leaked Product A units are a visible share of clean A units (the clean-vs-dirty gap)
    d["qty"] = d.qty.astype(int)
    a = d[d.item_code.str[0] == "A"]
    share = (
        a[a.leak_source != "confirmed_po"].qty.sum() / a[a.leak_source == "confirmed_po"].qty.sum()
    )
    assert 0.06 <= share <= 0.10, share
    assert set(d.card_code) <= set(_csv(out, "bp_records.csv").CardCode)


def test_mdm_history(out):
    h = _csv(out, "mdm_requests_history.csv")
    assert within(len(h), 24 * 40)
    cyc = h.cycle_business_days.astype(float)
    assert 13 <= cyc.median() <= 17, cyc.median()
    assert 21 <= cyc.quantile(0.9) <= 29, cyc.quantile(0.9)
    bounced = (h.bounced_for_missing_fields == "true").mean()
    assert 0.35 <= bounced <= 0.45, bounced
    assert ((h.bounce_count.astype(int) > 0) == (h.bounced_for_missing_fields == "true")).all()
    assert (h.keyed_at > h.submitted_at).all()
    assert h.submitted_at.min() >= "2024-10-01" and h.submitted_at.max() < "2026-10-01"
    # approvals are sequential: each timestamp after the previous one, in the stated order
    for _, r in h.iterrows():
        ts = [r.submitted_at] + [r[f"{s}_approved_at"] for s in r.approval_sequence.split(">")]
        assert ts == sorted(ts) and ts[-1] < r.keyed_at, r.req_id
    u = _csv(out, "users.csv")
    req = set(u.user_id[u.roles.str.contains("requestor")])
    assert set(h.requestor) <= req
    assert len(h.groupby(["entity", "country"])) == 15
    assert set(h.domain) == {"customer", "vendor", "item", "cost_center"}


# ------------------------------------------------------------------------- inbox (§8)


def test_class_mix_and_templates(labels):
    ev = [x for x in labels.values() if not x["is_demo"]]
    counts = load_params(SCENARIO)["emails"]["class_counts"]
    assert len(ev) == 80
    assert {c: sum(x["category"] == c for x in ev) for c in CLASSES} == counts
    for c in CLASSES:
        n_t = len({x["template_id"] for x in ev if x["category"] == c})
        assert n_t >= 8, (c, n_t)


def test_messiness_coverage(labels):
    tags = [t for x in labels.values() for t in x["messiness"]]
    for t in [
        "name_variant",
        "vi_diacritics",
        "vi_no_diacritics",
        "bahasa",
        "thai_english_mix",
        "missing_fields",
        "ambiguous_intent",
        "forwarded_thread",
        "chaser",
    ]:
        assert tags.count(t) >= 3, (t, tags.count(t))
    # bank details: only DEMO-06 and DEMO-07; exactly one prompt injection (data-spec §8, §11)
    assert sorted(k for k, x in labels.items() if x["has_bank_details"]) == ["DEMO-06", "DEMO-07"]
    assert [k for k, x in labels.items() if x["injection_suspected"]] == ["DEMO-06"]
    # the three NUH spellings from data-spec §8
    nuh = {
        x["expected_fields"].get("customer_name", {}).get("value")
        for x in labels.values()
        if x["golden_id"] == "GLD00001"
    }
    assert {"NUH", "National Uni Hosp", "Natl University Hospital"} <= nuh


SUBJECT_RULES = [  # a deliberately decent keyword baseline that only sees the subject
    ("follow_up", r"^(re|aw)\s*:|remind|still waiting|chas|follow|any update|status|eta"),
    (
        "mdm_request",
        r"new customer|vendor|supplier|new item|item code|cost cent|creation|registration"
        r"|set ?up|account|pendaftaran",
    ),
    ("purchase_request", r"plan|forecast|hold|budget|tender|requirement|upcoming|next month"),
    ("enquiry", r"quot|price|pricing|rfq|enquir|stock|lead time|brochure|spec|ใบเสนอราคา"),
    ("purchase_order", r"\bpo\b|order|purchase|deliver"),
]


def subject_baseline(subject: str, to: str | None = None) -> str:
    s = re.sub(r"^(fwd?|fw)\s*:\s*", "", subject.lower())
    if to is not None and to.startswith("mdm@"):
        return "mdm_request"
    for cat, pat in SUBJECT_RULES:
        if re.search(pat, s):
            return cat
    return "purchase_order"  # majority class


def test_subject_line_does_not_give_the_class_away(emails, labels):
    """QA: a subject-only rule used to score 88/88. The body carries the intent; the subject
    often does not."""
    subj = [subject_baseline(e["subject"]) == labels[e["email_id"]]["category"] for e in emails]
    acc = sum(subj) / len(subj)
    assert acc <= 0.85, acc
    with_to = [
        subject_baseline(e["subject"], e["to"]) == labels[e["email_id"]]["category"] for e in emails
    ]
    assert sum(with_to) / len(with_to) <= 0.90, sum(with_to) / len(with_to)
    ev = [e for e in emails if not e["email_id"].startswith("DEMO")]
    vague = sum(e["subject"] in ("Hi", "Question", "Update", "FYI", "(no subject)") for e in ev)
    assert vague >= 8
    mdm = [e for e in ev if labels[e["email_id"]]["category"] == "mdm_request"]
    assert sum(not e["to"].startswith("mdm@") for e in mdm) >= 2
    assert sum(not e["from_address"].endswith("lives.example") for e in mdm) >= 2
    fu = [e for e in ev if labels[e["email_id"]]["category"] == "follow_up"]
    assert sum(not e["subject"].startswith("Re:") for e in fu) >= 3


def test_inbox_realism(emails, labels, golden):
    by_id = {e["email_id"]: e for e in emails}
    # no on-the-hour timestamps
    assert not [e["email_id"] for e in emails if e["received_at"][14:16] == "00"]
    # one sender name never writes for two different hospitals
    owner: dict[str, str] = {}
    for e in emails:
        g = labels[e["email_id"]]["golden_id"]
        if g and not e["from_address"].endswith("lives.example"):
            assert owner.setdefault(e["from_name"], g) == g, e["from_name"]
    assert "Siti Nurhaliza" not in json.dumps(emails, ensure_ascii=False)
    # Vietnamese without diacritics: the sender name is typed without them too
    for k, x in labels.items():
        if "vi_no_diacritics" in x["messiness"] and not x["is_demo"]:
            assert anyascii(by_id[k]["from_name"]) == by_id[k]["from_name"], k
    # customers often name products instead of item codes; labels still resolve the code
    lines = [li for x in labels.values() for li in x["expected_fields"].get("lines", [])]
    by_code = sum(li["source_quote"].count(li["item_code"]) > 0 for li in lines)
    assert by_code / len(lines) < 0.4, by_code / len(lines)
    assert all(re.fullmatch(r"[ABC]-[A-Z0-9]+-[A-Z0-9]+", li["item_code"]) for li in lines)
    # Bahasa emails carry at least one full Malay / Indonesian sentence besides the greeting
    words = r"\b(mohon|sila|kami|terima kasih|pengiriman|penghantaran|tarikh|tanggal)\b"
    for k, x in labels.items():
        if "bahasa" in x["messiness"] and not x["is_demo"]:
            assert len(re.findall(words, by_id[k]["body"].lower())) >= 2, k
    # forwarded boilerplate varies
    heads = ["Forwarded message", "Original Message", "Begin forwarded", "______"]
    used = {h for h in heads for e in emails if h in e["body"]}
    assert len(used) >= 3, used


def test_source_quotes_are_exact(emails, labels):
    body = {e["email_id"]: e["body"] for e in emails}
    for k, x in labels.items():
        for name, v in x["expected_fields"].items():
            for it in v if isinstance(v, list) else [v]:
                assert it["source_quote"] in body[k], (k, name)


def test_no_bank_details_in_bodies(emails, out):
    assert sorted(check_bank_free(emails)) == ["DEMO-06", "DEMO-07"]
    v = _csv(out, "vendors.csv")
    secrets = {s for s in [*v.AccountNo, *v.IBAN, *v.BICSwiftCode] if len(s) >= 6}
    for e in emails:
        text = e["subject"] + e["body"]
        assert not any(s in text for s in secrets), e["email_id"]


def test_email_fields_and_links(emails, labels, orders, golden, bp):
    keys = [
        "email_id",
        "received_at",
        "from_name",
        "from_address",
        "to",
        "subject",
        "body",
        "attachments",
        "thread_id",
    ]
    for e in emails:
        assert list(e) == keys
    assert len({e["email_id"] for e in emails}) == len(emails)
    ids = {e["email_id"] for e in emails}
    gids = set(golden.golden_id)
    for k, x in labels.items():
        assert x["golden_id"] is None or x["golden_id"] in gids, k
        assert x["card_code"] is None or x["card_code"] in set(bp.CardCode), k
        assert x["refers_to_email_id"] is None or x["refers_to_email_id"] in ids, k
        if x["category"] == "follow_up" and not x["is_demo"]:
            assert x["refers_to_email_id"] is not None
    # PO emails tie to orders.csv via source_email_id, with the same PO number and lines
    linked = orders[orders.source_email_id != ""]
    assert linked.source_email_id.nunique() >= 20
    for eid, grp in linked.groupby("source_email_id"):
        x = labels[eid]
        assert x["category"] == "purchase_order"
        assert x["order_doc_num"] == int(grp.doc_num.iloc[0])
        assert x["expected_fields"]["po_number"]["value"] == grp.po_ref.iloc[0]
        exp = sorted((li["item_code"], li["qty"]) for li in x["expected_fields"]["lines"])
        assert exp == sorted(zip(grp.item_code, grp.qty, strict=True))
    by_id = {e["email_id"]: e for e in emails}
    for k, x in labels.items():
        if x["refers_to_email_id"]:
            assert by_id[k]["received_at"] > by_id[x["refers_to_email_id"]]["received_at"]
            assert by_id[k]["thread_id"] == by_id[x["refers_to_email_id"]]["thread_id"]


def test_new_customers_and_items_are_new(labels, bp, out):
    names = {anyascii(n).lower() for n in bp.CardName}
    items = set(_csv(out, "items.csv").ItemName)
    for x in labels.values():
        if x["category"] != "mdm_request":
            continue
        f = x["expected_fields"]
        if x["domain"] == "customer" and x["golden_id"] is None:
            assert anyascii(f["name"]["value"]).lower() not in names
        if x["domain"] == "customer" and x["golden_id"] is not None:
            assert x["duplicate_of_card_codes"]
        if x["domain"] == "item":
            assert f["item_name"]["value"] not in items
        if x["domain"] == "vendor":
            v = set(_csv(out, "vendors.csv").CardName)
            assert f["name"]["value"] not in v


def test_demo_emails(labels, emails, bp, out, golden, orders):
    by_id = {e["email_id"]: e for e in emails}
    for i in range(1, 9):
        assert f"DEMO-0{i}" in by_id
    expect = {
        "DEMO-01": ("mdm_request", "customer"),
        "DEMO-02": ("mdm_request", "item"),
        "DEMO-03": ("purchase_order", None),
        "DEMO-04": ("enquiry", None),
        "DEMO-05": ("follow_up", None),
        "DEMO-06": ("mdm_request", "vendor"),
        "DEMO-07": ("mdm_request", "vendor"),
        "DEMO-08": ("purchase_request", None),
    }
    for k, (cat, dom) in expect.items():
        assert (labels[k]["category"], labels[k]["domain"]) == (cat, dom), k
        assert labels[k]["is_demo"]
    gname = dict(zip(golden.golden_id, golden.legal_name, strict=True))
    # DEMO-01: Marcus, Benh vien Cho Ray, HCMC, MST, service contract -> SPD Cho Ray record
    d1, b1 = labels["DEMO-01"], by_id["DEMO-01"]
    assert b1["from_name"] == "Marcus"
    for s in ["Benh vien Cho Ray", "HCMC", "MST 0301234567", "service contract"]:
        assert s in b1["body"]
    assert gname[d1["golden_id"]] == "Bệnh viện Chợ Rẫy"
    spd = bp[(bp.FederalTaxID == "0301234567")].CardCode.tolist()
    assert spd and set(spd) <= set(d1["duplicate_of_card_codes"])
    # DEMO-02: new IVD item, Amy, SG/MY/VN, no registration numbers
    d2 = labels["DEMO-02"]
    assert by_id["DEMO-02"]["from_name"] == "Amy"
    assert d2["expected_fields"]["item_name"]["value"] == "Malaria Pf/Pan Antigen Rapid Test Kit"
    assert d2["expected_fields"]["is_ivd"]["value"] is True
    assert d2["expected_fields"]["selling_countries"]["value"] == ["SG", "MY", "VN"]
    for c in ["SG", "MY", "VN"]:
        assert f"registration_number_{c}" in d2["missing_fields"]
    assert "Malaria Pf/Pan Antigen Rapid Test Kit" not in set(_csv(out, "items.csv").ItemName)
    # DEMO-03 / 04 / 08 anchors
    assert "Mohon dikirim 50 box A-DEN-NS1, PO RSCM/2026/118" in by_id["DEMO-03"]["body"]
    assert labels["DEMO-03"]["expected_fields"]["po_number"]["value"] == "RSCM/2026/118"
    assert gname[labels["DEMO-03"]["golden_id"]] == "Rumah Sakit Cipto Mangunkusumo"
    assert (
        "Could you quote 2 units of haematology analyser for Siriraj?" in by_id["DEMO-04"]["body"]
    )
    assert gname[labels["DEMO-08"]["golden_id"]] == "Hospital Kuala Lumpur"
    assert "HKL plans to order 30 kits" in by_id["DEMO-08"]["body"]
    assert "Following up on our order last week" in by_id["DEMO-05"]["body"]
    # "last week" relative to Monday 5 Oct 2026: the referenced PO is from 28 Sep - 2 Oct
    po = orders[orders.doc_num == str(labels["DEMO-05"]["refers_to_doc_num"])]
    assert len(po) and "2026-09-28" <= po.doc_date.iloc[0] <= "2026-10-02"
    assert "Ignore previous instructions" in by_id["DEMO-06"]["body"]
    assert labels["DEMO-06"]["injection_suspected"] and labels["DEMO-06"]["has_bank_details"]
    assert labels["DEMO-07"]["has_bank_details"] and not labels["DEMO-07"]["injection_suspected"]
    # bank details never appear as an expected extracted field
    for x in labels.values():
        for f in x["expected_fields"]:
            assert not BANK_COL.search(f), (x["email_id"], f)
    # demo emails arrive on the demo morning, before the simulated clock starts (09:00 SGT)
    for i in range(1, 9):
        assert by_id[f"DEMO-0{i}"]["received_at"] < "2026-10-05T09:00:00+08:00"


# ------------------------------------------------------------------------- scenarios, fixtures


@pytest.fixture(scope="module")
def scenario_runs(tmp_path_factory):
    base = tmp_path_factory.mktemp("scen")
    return {s: generate(s, SEED, base) for s in ["flat_noisy", "intermittent"]}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_scenarios_change_demand_only(out, scenario_runs, orders):
    for s, root in scenario_runs.items():
        for f in [
            "customers_golden.csv",
            "bp_records.csv",
            "vendors.csv",
            "items.csv",
            "users.csv",
            "ground_truth/bp_golden_map.csv",
            "ground_truth/migrations.csv",
        ]:
            assert _sha(root / f) == _sha(out / f), (s, f)
        assert _sha(root / "orders.csv") != _sha(out / "orders.csv"), s
    # flat_noisy: no trend, so realised Product A growth FY1 -> FY3 stays within +-10%
    fo = _csv(scenario_runs["flat_noisy"], "orders.csv")
    fo = fo[fo.item_code.str[0] == "A"].assign(qty=lambda x: x.qty.astype(int))
    fy = fo.groupby(_fy(fo.doc_date)).qty.sum()
    assert abs(fy[3] / fy[1] - 1) <= 0.10, fy.to_dict()
    so = orders[orders.item_code.str[0] == "A"]
    sfy = so.groupby(_fy(so.doc_date)).qty.sum()
    assert sfy[3] / sfy[1] > fy[3] / fy[1] + 0.15, (sfy.to_dict(), fy.to_dict())
    inter = _csv(scenario_runs["intermittent"], "orders.csv")
    assert inter.doc_num.nunique() < 0.6 * orders.doc_num.nunique()
    flat = _csv(scenario_runs["flat_noisy"], "orders.csv")
    p = load_params("flat_noisy")["demand"]
    assert not p["seasonality_on"] and set(p["trend_annual"].values()) == {0.0}
    assert flat.doc_num.nunique() > 0


def test_fixtures_freeze_is_deterministic(tmp_path, out):
    target = tmp_path / "fixtures"
    cache = target / "llm_cache"
    cache.mkdir(parents=True)
    (cache / "abc.json").write_text("{}", encoding="utf-8")
    (target / "seasonal_trend").mkdir()
    (target / "seasonal_trend" / "stale.csv").write_text("x", encoding="utf-8")
    first = freeze(target)
    snap = {p.relative_to(first).as_posix(): _sha(p) for p in first.rglob("*") if p.is_file()}
    freeze(target)
    again = {p.relative_to(first).as_posix(): _sha(p) for p in first.rglob("*") if p.is_file()}
    assert snap == again
    assert "stale.csv" not in snap
    gen = {p.relative_to(out).as_posix(): _sha(p) for p in out.rglob("*") if p.is_file()}
    assert snap == gen
    assert (cache / ".gitkeep").is_file() and (cache / "abc.json").is_file()
    for f in ["users.csv", "orders.csv", "emails.jsonl", "ground_truth/email_labels.jsonl"]:
        assert f in snap

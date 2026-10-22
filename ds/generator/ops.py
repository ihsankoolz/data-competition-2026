"""Past MDM requests under the old email process (data-spec §7, `mdm_requests_history.csv`).

Approvals run one after another by email. Business time: Mon-Fri 09:00-18:00 SGT (public
holidays are ignored: labelled simplification). Every wait is lognormal in business days.
A bounce sends the request back to the requestor for missing fields; the same approver then
reviews it again.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from .common import month_date, stream, wpick
from .demand import business_days
from .users import requestors_for

SGT = timezone(timedelta(hours=8))
DAY_START, DAY_END = 9, 18
HOURS_PER_DAY = DAY_END - DAY_START
APPROVER_COLS = [
    "bu_head_approved_at",
    "finance_approved_at",
    "quality_regulatory_approved_at",
    "business_support_approved_at",
]
MDM_COLS = [
    "req_id",
    "domain",
    "entity",
    "country",
    "requestor",
    "is_ivd",
    "approval_sequence",
    "submitted_at",
    *APPROVER_COLS,
    "keyed_at",
    "bounced_for_missing_fields",
    "bounce_count",
    "missing_fields",
    "cycle_business_days",
]
COUNTRY_W = {"SG": 0.22, "MY": 0.2, "ID": 0.22, "VN": 0.2, "TH": 0.16}
ENTITY_W = {"SPD": 0.45, "QTS": 0.25, "QTG": 0.30}


def add_business_hours(dt: datetime, hours: float) -> datetime:
    """Move forward `hours` of business time (Mon-Fri 09:00-18:00)."""
    while True:
        if dt.weekday() >= 5 or dt.hour >= DAY_END:
            dt = (dt + timedelta(days=1)).replace(hour=DAY_START, minute=0, second=0)
            continue
        if dt.hour < DAY_START:
            dt = dt.replace(hour=DAY_START, minute=0, second=0)
        end = dt.replace(hour=DAY_END, minute=0, second=0)
        left = (end - dt).total_seconds() / 3600
        if hours <= left:
            return dt + timedelta(hours=hours)
        hours -= left
        dt = end


def business_hours_between(a: datetime, b: datetime) -> float:
    total, d = 0.0, a
    while d.date() < b.date():
        if d.weekday() < 5:
            end = d.replace(hour=DAY_END, minute=0, second=0)
            total += max(0.0, (end - max(d, d.replace(hour=DAY_START, minute=0))).total_seconds())
        d = (d + timedelta(days=1)).replace(hour=DAY_START, minute=0, second=0)
    if b.weekday() < 5:
        start = max(d, d.replace(hour=DAY_START, minute=0, second=0))
        total += max(0.0, (b - start).total_seconds())
    return total / 3600


def _ts(dt: datetime) -> str:
    return dt.replace(second=0, microsecond=0).isoformat()


def build_mdm_history(params: dict, seed: int) -> list[dict]:
    hp = params["mdm_history"]
    rng = stream(seed, "ops.mdm_history")

    def wait(median: float, sigma: float) -> float:
        return float(median * np.exp(rng.normal(0.0, sigma))) * HOURS_PER_DAY

    reqs: list[dict] = []
    for t in range(hp["start_month"], 36):
        d0 = month_date(t)
        days = business_days(d0.year, d0.month)
        for _ in range(int(rng.poisson(hp["per_month_mean"]))):
            day = days[int(rng.integers(len(days)))]
            sub = datetime(
                day.year,
                day.month,
                day.day,
                int(rng.integers(9, 18)),
                int(rng.integers(60)),
                tzinfo=SGT,
            )
            domain = wpick(rng, hp["domain_mix"])
            entity = wpick(rng, ENTITY_W)
            country = wpick(rng, COUNTRY_W)
            people = requestors_for(entity, country)
            requestor = people[int(rng.integers(len(people)))]
            u_ivd = rng.random()
            is_ivd = domain == "item" and u_ivd < hp["item_ivd_prob"]
            seq = [s for s in hp["sequence"][domain] if s != "quality_regulatory" or is_ivd]
            n_bounce = 0
            if rng.random() < hp["bounce_prob"]:
                n_bounce = 1 + int(rng.random() < hp["second_bounce_prob"])
            stages = seq + ["keying"]
            bounce_at = sorted(int(i) for i in rng.integers(0, len(stages), size=n_bounce))
            opts = hp["missing_field_options"][domain]
            missing = sorted({opts[int(i)] for i in rng.integers(0, len(opts), size=n_bounce)})
            now = sub
            stamps: dict[str, datetime] = {}
            for i, st in enumerate(stages):
                med, sig = (
                    (hp["keying_wait_median_days"], hp["keying_wait_sigma"])
                    if st == "keying"
                    else (hp["step_wait_median_days"], hp["step_wait_sigma"])
                )
                for _ in range(bounce_at.count(i)):
                    now = add_business_hours(now, wait(med, sig))  # reviewed, bounced
                    now = add_business_hours(
                        now, wait(hp["bounce_delay_median_days"], hp["bounce_delay_sigma"])
                    )
                now = add_business_hours(now, wait(med, sig))
                stamps[st] = now
            reqs.append(
                dict(
                    domain=domain,
                    entity=entity,
                    country=country,
                    requestor=requestor,
                    is_ivd=is_ivd if domain == "item" else None,
                    approval_sequence=">".join(seq),
                    submitted=sub,
                    stamps=stamps,
                    n_bounce=n_bounce,
                    missing=missing,
                )
            )
    reqs.sort(key=lambda r: (r["submitted"], r["domain"], r["requestor"]))
    out = []
    for i, r in enumerate(reqs):
        keyed = r["stamps"]["keying"]
        row = {
            "req_id": f"MDMH-{i + 1:05d}",
            "domain": r["domain"],
            "entity": r["entity"],
            "country": r["country"],
            "requestor": r["requestor"],
            "is_ivd": "" if r["is_ivd"] is None else ("true" if r["is_ivd"] else "false"),
            "approval_sequence": r["approval_sequence"],
            "submitted_at": _ts(r["submitted"]),
        }
        for col in APPROVER_COLS:
            role = col.removesuffix("_approved_at")
            row[col] = _ts(r["stamps"][role]) if role in r["stamps"] else ""
        row["keyed_at"] = _ts(keyed)
        row["bounced_for_missing_fields"] = "true" if r["n_bounce"] else "false"
        row["bounce_count"] = r["n_bounce"]
        row["missing_fields"] = "|".join(r["missing"])
        row["cycle_business_days"] = (
            f"{business_hours_between(r['submitted'], keyed) / HOURS_PER_DAY:.2f}"
        )
        out.append(row)
    return out


def mdm_rows(reqs: list[dict]) -> list[list]:
    return [[r[c] for c in MDM_COLS] for r in reqs]

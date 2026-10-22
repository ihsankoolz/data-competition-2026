"""Modelled cycle time, old email process vs new parallel process (PRD M10, D-018 item 4).

Old = `mdm_requests_history.csv` as recorded (sequential approvals by email, bounce loops).
New = the SAME requests replayed through the new rules:

1. Validation at entry: the form refuses to submit while a required field is missing
   (config/required_fields.yaml, D-018 item 3). Missing fields the form checks no longer bounce;
   the requestor fills them before submitting, which costs `ENTRY_FIX_BD`. Missing fields the
   form does NOT check (e.g. credit terms, risk class) still bounce once each.
2. One parallel approval stage (D-007): the stage takes as long as the SLOWEST approver
   (max of the waits, not the sum).
3. Each approver wait is the recorded wait for that step, capped by the SLA: reminder at 1
   business day (not credited with any speed-up), escalation to the backup approver at 2, and the
   backup answers within `BACKUP_RESPONSE_BD`.
4. MDM publish stays a stage: the recorded keying wait, capped at `PUBLISH_CAP_BD` (a publish
   queue with one click to SAP instead of re-typing).

Every assumption is returned with its source. This is a model, not a measurement.
"""

from __future__ import annotations

import csv
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ds.generator.ops import HOURS_PER_DAY, business_hours_between

# ---------------------------------------------------------------- assumptions (labelled below)
REMINDER_BD = 1.0  # D-018 item 4 (our design)
ESCALATE_BD = 2.0  # D-018 item 4 (our design)
BACKUP_RESPONSE_BD = 0.5  # assumption: the backup answers within half a business day
WAIT_CAP_BD = ESCALATE_BD + BACKUP_RESPONSE_BD
PUBLISH_CAP_BD = 1.0  # assumption: Priya's publish queue is cleared within one business day
ENTRY_FIX_BD = 0.5  # assumption: requestor fills the flagged fields before submitting
RESUBMIT_BD = 3.2  # generated history: median requestor fix-and-resend delay (params.yaml)
BRIEF_AMY_BD = 18.0  # brief: "Amy's item request took 18 days"

# History missing-field names that the new form checks at entry (config/required_fields.yaml:
# customer/vendor name, tax_id, country, address, contact_email; vendor bank account (form only);
# IVD registration numbers per selling country; cost center effective_from).
CAUGHT_AT_ENTRY: dict[str, set[str]] = {
    "customer": {"tax_id", "billing_address", "contact_email"},
    "vendor": {"tax_id", "address", "bank_details"},
    "item": {"registration_number"},
    "cost_center": {"effective_from"},
}

STEP_COL = {
    "bu_head": "bu_head_approved_at",
    "finance": "finance_approved_at",
    "quality_regulatory": "quality_regulatory_approved_at",
    "business_support": "business_support_approved_at",
}

# Amy's item (DEMO-02, D-015): new IVD malaria kit sold in SG, MY, VN. D-007 item route: BU Head
# and Business Support always, plus Quality/Regulatory per selling country, all in parallel.
AMY_COUNTRIES = ("SG", "MY", "VN")


@dataclass
class Replayed:
    req_id: str
    domain: str
    old_bd: float
    new_bd: float
    bounced_before: bool
    bounces_after: int
    step_waits: dict[str, float] = field(default_factory=dict)
    keying_bd: float = 0.0


def _bd(a: datetime, b: datetime) -> float:
    return business_hours_between(a, b) / HOURS_PER_DAY


def _p90(xs: list[float]) -> float:
    return statistics.quantiles(xs, n=10, method="inclusive")[-1]


def replay_request(row: dict[str, str]) -> Replayed:
    """One recorded request, old vs modelled new (business days, submitted -> live in SAP)."""
    seq = [s for s in row["approval_sequence"].split(">") if s]
    t = datetime.fromisoformat(row["submitted_at"])
    waits: dict[str, float] = {}
    for step in seq:
        nxt = datetime.fromisoformat(row[STEP_COL[step]])
        waits[step] = _bd(t, nxt)
        t = nxt
    keyed = datetime.fromisoformat(row["keyed_at"])
    keying = _bd(t, keyed)
    old = float(row["cycle_business_days"])

    missing = [m for m in (row["missing_fields"] or "").split("|") if m]
    caught = CAUGHT_AT_ENTRY.get(row["domain"], set())
    if row["domain"] == "item" and row.get("is_ivd") != "true":
        caught = set()  # registration numbers are only required for IVD items
    bounced = row["bounced_for_missing_fields"] == "true"
    n_caught = sum(m in caught for m in missing)
    remaining = min(int(row["bounce_count"] or 0), len(missing) - n_caught) if bounced else 0

    stage = max(min(w, WAIT_CAP_BD) for w in waits.values()) if waits else 0.0
    publish = min(keying, PUBLISH_CAP_BD)
    new = (ENTRY_FIX_BD if n_caught else 0.0) + stage + remaining * (RESUBMIT_BD + stage)
    new += publish
    return Replayed(row["req_id"], row["domain"], old, new, bounced, remaining, waits, keying)


def load_history(data_dir: Path) -> list[dict[str, str]]:
    with open(Path(data_dir) / "mdm_requests_history.csv", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def replay_all(data_dir: Path) -> list[Replayed]:
    return [replay_request(r) for r in load_history(data_dir)]


def amy_case(reqs: list[Replayed]) -> tuple[float, str, dict[str, float]]:
    """Amy's IVD item, built from D-007: medians of the recorded waits per role (IVD items that
    did not bounce), capped by the SLA, max over the parallel approvers, plus publish."""
    clean = [r for r in reqs if r.domain == "item" and "quality_regulatory" in r.step_waits
             and not r.bounced_before]  # fmt: skip
    med = {
        role: statistics.median(r.step_waits[role] for r in clean)
        for role in ("bu_head", "quality_regulatory", "business_support")
    }
    keying = statistics.median(r.keying_bd for r in clean)
    approvers = {"BU Head (SPD)": med["bu_head"], "Business Support": med["business_support"]}
    approvers |= {f"Quality/Regulatory {c}": med["quality_regulatory"] for c in AMY_COUNTRIES}
    capped = {k: min(v, WAIT_CAP_BD) for k, v in approvers.items()}
    stage = max(capped.values())
    publish = min(keying, PUBLISH_CAP_BD)
    after = ENTRY_FIX_BD + stage + publish
    old_sum = sum(med.values()) + keying
    clean_med = statistics.median(r.old_bd for r in clean)
    bounced_med = statistics.median(
        r.old_bd
        for r in reqs
        if r.domain == "item" and "quality_regulatory" in r.step_waits and r.bounced_before
    )
    text = (
        f"Amy's new IVD item (malaria rapid test, selling in {', '.join(AMY_COUNTRIES)}). "
        f"Today: {BRIEF_AMY_BD:.0f} days (brief), one approver after another by email. In our "
        "history the median waits for an IVD item are BU Head "
        f"{med['bu_head']:.1f}, Quality/Regulatory {med['quality_regulatory']:.1f}, Business "
        f"Support {med['business_support']:.1f} and keying {keying:.1f} business days: "
        f"{old_sum:.1f} in a row; IVD items that bounced took a median {bounced_med:.1f} "
        f"business days in total, against {clean_med:.1f} for those that did not. "
        f"New: the form asks for the three registration numbers before submit "
        f"({ENTRY_FIX_BD:.1f} day), then BU Head, Business Support and Quality/Regulatory for "
        f"SG, MY and VN all get the request at once. The stage ends when the slowest of the "
        f"five answers: at most {WAIT_CAP_BD:.1f} days, because a reminder goes out at "
        f"{REMINDER_BD:.0f} day and the backup approver takes over at {ESCALATE_BD:.0f} "
        f"({stage:.1f} days). Publishing to SAP from the queue takes up to "
        f"{PUBLISH_CAP_BD:.1f} day. Total about {after:.1f} business days."
    )
    return after, text, approvers


def ops_details(data_dir: Path) -> dict[str, Any]:
    reqs = replay_all(data_dir)
    old = [r.old_bd for r in reqs]
    new = [r.new_bd for r in reqs]
    amy_after, amy_text, amy_approvers = amy_case(reqs)
    by_domain = {}
    for d in ("customer", "vendor", "item", "cost_center"):
        o = [r.old_bd for r in reqs if r.domain == d]
        n = [r.new_bd for r in reqs if r.domain == d]
        by_domain[d] = (len(o), statistics.median(o), statistics.median(n))
    return dict(
        n=len(reqs),
        old_median=statistics.median(old),
        old_p90=_p90(old),
        new_median=statistics.median(new),
        new_p90=_p90(new),
        ftr_before=100 * sum(not r.bounced_before for r in reqs) / len(reqs),
        ftr_after=100 * sum(r.bounces_after == 0 for r in reqs) / len(reqs),
        still_bounce=sum(r.bounces_after > 0 for r in reqs),
        slower=sum(r.new_bd > r.old_bd + 1e-9 for r in reqs),
        by_domain=by_domain,
        amy_after=amy_after,
        amy_text=amy_text,
        amy_approvers=amy_approvers,
        months=(
            load_history(data_dir)[0]["submitted_at"][:7],
            load_history(data_dir)[-1]["submitted_at"][:7],
        ),  # fmt: skip
    )


def assumptions() -> list[dict[str, str]]:
    return [
        dict(
            name="Today's process",
            value="Approvals one after another by email; Amy's item took 18 days",
            source="brief",
        ),  # fmt: skip
        dict(
            name="Old cycle times",
            value="Recorded submit-to-keyed times of every past "
            "request in mdm_requests_history.csv (24 months, synthetic)",
            source="generated_history",
        ),  # fmt: skip
        dict(
            name="Business days",
            value="Mon-Fri 09:00-18:00 SGT; public holidays ignored",
            source="generated_history",
        ),  # fmt: skip
        dict(
            name="Parallel approvals",
            value="All stage-1 approvers get the request at once; "
            "the stage ends when the slowest answers (max, not sum)",
            source="our_design",
        ),
        dict(
            name="Reminder",
            value=f"At {REMINDER_BD:.0f} business day; not credited with any "
            "speed-up (conservative)",
            source="our_design",
        ),  # fmt: skip
        dict(
            name="Escalation",
            value=f"To the backup approver at {ESCALATE_BD:.0f} business days",
            source="our_design",
        ),  # fmt: skip
        dict(
            name="Backup response time",
            value=f"The backup answers within "
            f"{BACKUP_RESPONSE_BD} business day, so no approver wait exceeds "
            f"{WAIT_CAP_BD} days",
            source="assumption",
        ),  # fmt: skip
        dict(
            name="Fields checked at entry",
            value="Missing tax ID, address, contact email, "
            "bank account, IVD registration numbers and cost-center start date can no longer "
            "be submitted, so they never bounce",
            source="our_design",
        ),  # fmt: skip
        dict(
            name="Time to fill flagged fields",
            value=f"{ENTRY_FIX_BD} business day for a "
            "request that would have bounced on a checked field",
            source="assumption",
        ),
        dict(
            name="Fields the form does not check",
            value="Credit or payment terms, risk "
            "class, supplier, sales unit, cost-center dimension and owner still bounce once "
            f"each: requestor fix {RESUBMIT_BD} days (history median) plus the approval stage "
            "again",
            source="generated_history",
        ),  # fmt: skip
        dict(
            name="MDM publish",
            value=f"Recorded keying wait, capped at {PUBLISH_CAP_BD} "
            "business day (publish queue, no re-typing)",
            source="assumption",
        ),
        dict(
            name="Amy's route",
            value="IVD item: BU Head, Business Support and "
            "Quality/Regulatory for SG, MY and VN in parallel (D-007, D-015)",
            source="our_design",
        ),  # fmt: skip
        dict(
            name="Amy's approver waits",
            value="Median recorded wait per role for IVD items that did not bounce",
            source="generated_history",
        ),  # fmt: skip
        dict(
            name="Amy's 18 days",
            value="Read as business days, as the brief gives no unit",
            source="assumption",
        ),  # fmt: skip
    ]


CAPTION = (
    "Modelled, not measured: we replay every past request from the (synthetic) history "
    "through the new rules. Parallel approvals, reminders, escalation and checks at entry are "
    "our design; the backup's response time and the publish time are assumptions."
)


def ops_impact(data_dir: Path, duplicates_prevented: int = 0) -> dict[str, Any]:
    """-> OpsImpact. `duplicates_prevented` = live requests linked to an existing record."""
    d = ops_details(data_dir)
    r1 = lambda x: round(float(x), 1)  # noqa: E731
    return dict(
        cycle_time=[
            dict(
                process="old_email_sequential",
                label="Today: one approver after another by email",
                median_bd=r1(d["old_median"]),
                p90_bd=r1(d["old_p90"]),
            ),  # fmt: skip
            dict(
                process="new_parallel",
                label="New: parallel approvals, checked at entry",
                median_bd=r1(d["new_median"]),
                p90_bd=r1(d["new_p90"]),
            ),  # fmt: skip
        ],
        amy_before_bd=BRIEF_AMY_BD,
        amy_after_bd=r1(d["amy_after"]),
        amy_explanation=d["amy_text"],
        first_time_right_before_pct=r1(d["ftr_before"]),
        first_time_right_after_pct=r1(d["ftr_after"]),
        duplicates_prevented=int(duplicates_prevented),
        assumptions=assumptions(),
        caption=CAPTION,
    )

"""Clean-up queue: the groups behind the regional "after merge" view, for Priya to review.

The groups are the links our duplicate check proposes (`ds.analytics.cleanup`, precomputed into
`data/fixtures/derived/cleanup_pairs.json`). A person confirms each group or marks it as not the
same; the AI never decides (rule 6). Decisions are stored and audited, and they never change the
regional numbers (those keep using the proposed links).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ds.analytics import cleanup
from services.api import clock
from services.api.audit import AuditAction, append_audit
from services.api.db import models as m
from services.api.db.session import session_scope
from services.api.deps import CurrentUser, require_role
from services.api.routers.analytics import data_dir
from services.api.schemas import (
    CleanupCluster,
    CleanupDecisionIn,
    CleanupDecisionOut,
    CleanupDecisionResult,
    CleanupLink,
    CleanupQueue,
    CleanupReason,
    CleanupRecord,
    CleanupStatus,
)
from services.api.views import user_names

router = APIRouter(tags=["cleanup"])

DECIDER_ROLE = "mdm_analyst"
MIN_REASON_CHARS = 10
READ_ONLY_NOTE = (
    "Only the MDM analyst (Priya) can confirm or reject these groups. You can look, but the "
    "buttons are switched off for you."
)

_STATUS: dict[str, CleanupStatus] = {"confirm": "confirmed", "not_same": "not_same"}

StatusFilter = Annotated[
    str, Query(pattern="^(all|not_reviewed|reviewed)$", description="all, not_reviewed, reviewed")
]


def _clusters() -> list[cleanup.Cluster]:
    try:
        data = cleanup.queue_data(data_dir())
    except FileNotFoundError:
        raise HTTPException(
            503, "The clean-up queue is not ready yet. Ask the team to refresh the results."
        ) from None
    return cleanup.clusters(data.pairs)


def _groups() -> dict[str, str]:
    return cleanup.queue_data(data_dir()).groups


def _certainty(c: cleanup.Cluster) -> str:
    if c.all_tax_id_match:
        return "Same tax ID on every record"
    pct = round(c.weakest_score * 100)
    if any(p.tax_id_match for p in c.pairs):
        return f"Some records share a tax ID; the weakest link scores {pct}%"
    return f"Names and details match; the weakest link scores {pct}%"


def _record(bp: m.BusinessPartner | None, code: str, groups: dict[str, str]) -> CleanupRecord:
    if bp is None:  # a fixture record missing from the database: show the code, never fail
        return CleanupRecord(CardCode=code, CardName=code, Country="", group_name=groups.get(code))
    created = bp.CreateDate.isoformat() if isinstance(bp.CreateDate, date) else None
    return CleanupRecord(
        CardCode=bp.CardCode,
        CardName=bp.CardName,
        CardForeignName=bp.CardForeignName,
        FederalTaxID=bp.FederalTaxID,
        City=bp.City,
        Country=bp.Country or "",
        U_Entity=bp.U_Entity,
        Phone1=bp.Phone1,
        EmailAddress=bp.EmailAddress,
        CreateDate=created,
        CreatedBy=bp.CreatedBy,
        group_name=groups.get(code),
    )


def _decision(row: m.CleanupDecisionRow | None, names: dict[str, str]) -> CleanupDecisionOut | None:
    if row is None:
        return None
    return CleanupDecisionOut(
        decision=row.decision,  # type: ignore[arg-type]
        reason=row.reason,
        decided_by=names.get(row.decided_by, row.decided_by),
        decided_at=row.decided_at,
    )


def _view(
    c: cleanup.Cluster,
    bps: dict[str, m.BusinessPartner],
    groups: dict[str, str],
    row: m.CleanupDecisionRow | None,
    names: dict[str, str],
) -> CleanupCluster:
    return CleanupCluster(
        cluster_id=c.cluster_id,
        certainty=_certainty(c),
        all_tax_id_match=c.all_tax_id_match,
        weakest_score=c.weakest_score,
        records=[_record(bps.get(code), code, groups) for code in c.codes],
        links=[
            CleanupLink(
                a=p.a,
                b=p.b,
                score=p.score,
                tax_id_match=p.tax_id_match,
                reasons=[CleanupReason(text=r.text, against=r.against) for r in p.reasons],
            )
            for p in c.pairs
        ],
        status=_STATUS[row.decision] if row is not None else "not_reviewed",
        decision=_decision(row, names),
    )


def _partners(session: Session, codes: list[str]) -> dict[str, m.BusinessPartner]:
    rows = session.scalars(select(m.BusinessPartner).where(m.BusinessPartner.CardCode.in_(codes)))
    return {bp.CardCode: bp for bp in rows}


def _decisions(session: Session) -> dict[str, m.CleanupDecisionRow]:
    return {r.cluster_id: r for r in session.scalars(select(m.CleanupDecisionRow))}


@router.get("/cleanup/clusters", response_model=CleanupQueue, operation_id="listCleanupClusters")
def list_clusters(actor: CurrentUser, status: StatusFilter = "all") -> CleanupQueue:
    """Every proposed group, most certain first (same tax ID first, then the highest score of
    the weakest link), with its records side by side, the reasons and the review status."""
    clusters = _clusters()
    groups = _groups()
    with session_scope() as session:
        decided = _decisions(session)
        names = user_names(session)
        bps = _partners(session, [code for c in clusters for code in c.codes])
        views = [_view(c, bps, groups, decided.get(c.cluster_id), names) for c in clusters]
    ids = {c.cluster_id for c in clusters}
    reviewed = sum(1 for cid in decided if cid in ids)
    if status == "not_reviewed":
        views = [v for v in views if v.status == "not_reviewed"]
    elif status == "reviewed":
        views = [v for v in views if v.status != "not_reviewed"]
    can = actor.has(DECIDER_ROLE)
    return CleanupQueue(
        clusters=views,
        reviewed=reviewed,
        total=len(clusters),
        can_decide=can,
        note=None if can else READ_ONLY_NOTE,
    )


@router.post(
    "/cleanup/clusters/{cluster_id}/decision",
    response_model=CleanupDecisionResult,
    operation_id="decideCleanupCluster",
)
def decide_cluster(
    cluster_id: str, body: CleanupDecisionIn, actor: CurrentUser
) -> CleanupDecisionResult:
    """Confirm the link, or mark the group as not the same customer (a reason is required).
    Only the MDM analyst decides. Stored, audited, and never fed into the regional numbers."""
    require_role(actor, DECIDER_ROLE, "confirm or reject a clean-up group")
    clusters = _clusters()
    cluster = next((c for c in clusters if c.cluster_id == cluster_id), None)
    if cluster is None:
        raise HTTPException(404, f"There is no proposed group {cluster_id} in the clean-up queue.")
    reason = (body.reason or "").strip() or None
    if body.decision == "not_same" and len(reason or "") < MIN_REASON_CHARS:
        raise HTTPException(
            422,
            "Please say why these are different customers, in at least "
            f"{MIN_REASON_CHARS} characters.",
        )
    groups = _groups()
    with session_scope(write=True) as session:
        if session.get(m.CleanupDecisionRow, cluster_id) is not None:
            raise HTTPException(409, "This group has already been reviewed.")
        row = m.CleanupDecisionRow(
            cluster_id=cluster_id,
            decision=body.decision,
            reason=reason,
            decided_by=actor.user_id,
            decided_at=clock.now(),
            codes=list(cluster.codes),
        )
        session.add(row)
        codes = ", ".join(cluster.codes)
        if body.decision == "confirm":
            summary = f"{actor.name} confirmed that {codes} are the same customer"
        else:
            summary = f"{actor.name} marked {codes} as not the same customer: {reason}"
        append_audit(
            session,
            actor=actor.user_id,
            action=AuditAction.cleanup_decision,
            entity_type="cleanup_group",
            entity_id=cluster_id,
            payload={
                "decision": body.decision,
                "reason": reason,
                "codes": list(cluster.codes),
                "summary": summary,
            },
        )
        session.flush()
        decided = _decisions(session)
        names = user_names(session)
        bps = _partners(session, list(cluster.codes))
        view = _view(cluster, bps, groups, row, names)
    ids = {c.cluster_id for c in clusters}
    return CleanupDecisionResult(
        cluster=view, reviewed=sum(1 for cid in decided if cid in ids), total=len(clusters)
    )

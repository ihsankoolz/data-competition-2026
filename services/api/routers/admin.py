"""Demo administration (D-016). Owner: backend-engineer."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from services.api import reset
from services.api.crypto import EncryptionKeyError
from services.api.db.session import session_scope
from services.api.deps import CurrentUser, require_role
from services.api.schemas import (
    ConfigChange,
    Domain,
    EntityCode,
    ResetResult,
    RoutingRule,
    RoutingRules,
    RoutingRuleSave,
    RuleCountry,
    RuleKey,
    RulePreview,
    RulePreviewRequest,
)
from services.api.workflow import overrides

router = APIRouter(tags=["admin"])


@router.post("/admin/reset-demo", response_model=ResetResult, operation_id="resetDemo")
def reset_demo() -> ResetResult:
    """Restore the seeded demo state in under 10 s without stopping the API: database,
    simulated clock, audit chain and the SAP mock. `make reset-demo` uses the same code path."""
    try:
        return reset.reset_demo()
    except (reset.SeedError, EncryptionKeyError) as exc:
        raise HTTPException(status_code=500, detail=f"The demo reset did not run: {exc}") from None


# ---------------------------------------------------------------- approval rules (session 12)
# Stage 1 ("Business review") can be changed per record type x entity x country. Only the MDM
# team edits; the MDM publish stage is fixed. A saved rule applies to new requests only.

CAN_EDIT = "change approval rules"


@router.get("/admin/routing-rules", response_model=RoutingRules, operation_id="listRoutingRules")
def list_routing_rules(actor: CurrentUser) -> RoutingRules:
    """Every record type x entity x country with its stage-1 approvers, and whether that is the
    standard route or a saved override."""
    with session_scope() as session:
        return overrides.list_rules(session)


@router.put("/admin/routing-rules", response_model=RoutingRule, operation_id="saveRoutingRule")
def save_routing_rule(body: RoutingRuleSave, actor: CurrentUser) -> RoutingRule:
    """Save the full ordered list of stage-1 approvers for one key. 422 with a plain sentence for
    no approvers, an unknown person or someone without the step's role; 403 unless MDM."""
    require_role(actor, "mdm_analyst", CAN_EDIT)
    with session_scope(write=True) as session:
        return overrides.save_rule(session, actor.user_id, body)


@router.delete("/admin/routing-rules", response_model=RoutingRule, operation_id="resetRoutingRule")
def reset_routing_rule(
    domain: Annotated[Domain, Query()],
    entity: Annotated[EntityCode, Query()],
    country: Annotated[RuleCountry, Query()],
    actor: CurrentUser,
) -> RoutingRule:
    """Put one key back to the standard route from the rule table."""
    require_role(actor, "mdm_analyst", CAN_EDIT)
    with session_scope(write=True) as session:
        return overrides.reset_rule(
            session, actor.user_id, RuleKey(domain=domain, entity=entity, country=country)
        )


@router.post(
    "/admin/routing-rules/preview", response_model=RulePreview, operation_id="previewRoutingRule"
)
def preview_routing_rule(body: RulePreviewRequest, actor: CurrentUser) -> RulePreview:
    """Who would approve a sample request, by the real routing code. Nothing is saved."""
    with session_scope() as session:
        return overrides.preview(session, body)


@router.get(
    "/admin/config-changes", response_model=list[ConfigChange], operation_id="listConfigChanges"
)
def list_config_changes(actor: CurrentUser) -> list[ConfigChange]:
    """The most recent rule changes: who, when (simulated clock), before and after."""
    with session_scope() as session:
        return overrides.recent_changes(session)

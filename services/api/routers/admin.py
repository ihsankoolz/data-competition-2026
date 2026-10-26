"""Demo administration (D-016). Owner: backend-engineer."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from services.api import reset
from services.api.crypto import EncryptionKeyError
from services.api.db.session import session_scope
from services.api.deps import CurrentUser, require_role
from services.api.schemas import (
    ConfigChange,
    CountryCode,
    Domain,
    EntityCode,
    RequiredFieldChange,
    RequiredFieldsSave,
    RequiredFieldsView,
    ResetResult,
    RoutingRule,
    RoutingRules,
    RoutingRuleSave,
    RuleCountry,
    RuleKey,
    RulePreview,
    RulePreviewRequest,
)
from services.api.workflow import overrides, required_fields

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


# ---------------------------------------------------------------- required fields (session 13)
# Priya switches a form field between required and optional per record type x country. A request
# keeps the rules it was created with; locked fields can never be made optional.

CAN_EDIT_FIELDS = "change which fields are required"


@router.get(
    "/admin/required-fields", response_model=RequiredFieldsView, operation_id="getRequiredFields"
)
def get_required_fields(
    domain: Annotated[Domain, Query()], country: Annotated[CountryCode, Query()], actor: CurrentUser
) -> RequiredFieldsView:
    """Every field on one form with whether it is required now, whether that is the standard,
    and whether it is locked (with the reason)."""
    with session_scope() as session:
        return required_fields.view(session, domain, country)


@router.put(
    "/admin/required-fields", response_model=RequiredFieldsView, operation_id="saveRequiredFields"
)
def save_required_fields(body: RequiredFieldsSave, actor: CurrentUser) -> RequiredFieldsView:
    """Switch fields for one record type x country. 403 unless MDM; 422 with a plain sentence for
    a locked field (nothing is saved). Each change is audit-logged. New requests only."""
    require_role(actor, "mdm_analyst", CAN_EDIT_FIELDS)
    with session_scope(write=True) as session:
        return required_fields.save(session, actor.user_id, body)


@router.get(
    "/admin/required-field-changes",
    response_model=list[RequiredFieldChange],
    operation_id="listRequiredFieldChanges",
)
def list_required_field_changes(actor: CurrentUser) -> list[RequiredFieldChange]:
    """The most recent required-field changes: who, when (simulated clock), what."""
    with session_scope() as session:
        return required_fields.recent_changes(session)

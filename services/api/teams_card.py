"""The Teams reminder for an approval task, as an Adaptive Card (session 13, preview only).

In production Power Automate would post this card to the approver in Teams and send the button
presses back to the API. Here it is only built and shown: nothing is sent, and the buttons in the
web preview do nothing. A human still decides on every approval (domain rule 6).

Bank details never appear (domain rule 5): the card uses the record's name (CardName / ItemName /
CenterName) and the request's codes, exactly like the notification text, and never the bank rows.
"""

from __future__ import annotations

import os

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ds.forms import country_names
from services.api import bankfields, clock
from services.api.db import models as m
from services.api.formfields import title_of
from services.api.schemas import (
    AdaptiveCard,
    CardActionOpenUrl,
    CardActionSubmit,
    CardFact,
    CardFactSet,
    CardTextBlock,
)
from services.api.views import role_label

# Notifications about an approval task the recipient decides on. "info_requested" and "rejected"
# also carry a task, but they go to the requestor, who has nothing to approve.
CARD_KINDS = frozenset({"task_assigned", "reminder", "escalated"})

HEADLINE = {
    "task_assigned": "New request to approve",
    "reminder": "Reminder: a request is waiting for you",
    "escalated": "Overdue approval",
}

# A card for a task that is no longer open shows what happened and only the Open button, the way
# a sent Teams card is updated in place once someone has decided.
CLOSED_STATUS = {
    "approved": "Already decided: approved.",
    "rejected": "Already decided: rejected.",
    "info_requested": "Already decided: more information was asked for. Waiting for the requestor.",
    "cancelled": "No longer needed: this approval was cancelled.",
    "waiting": "Not open yet: this step opens when the earlier approvals are done.",
}

DOMAIN_WORDS = {
    "customer": "Customer",
    "vendor": "Vendor",
    "item": "Item",
    "cost_center": "Cost Center",
}


def web_origin() -> str:
    return os.environ.get("WEB_ORIGIN", "http://localhost:3000").rstrip("/")


def has_card(kind: str, task: m.ApprovalTaskRow | None) -> bool:
    """Stage 1 only: the MDM publish step is done by publishing, not by an Approve button."""
    return kind in CARD_KINDS and task is not None and task.stage == 1


def build(session: Session, note: m.NotificationRow) -> AdaptiveCard:
    task = session.get(m.ApprovalTaskRow, note.task_id) if note.task_id else None
    if not has_card(note.kind, task):
        raise HTTPException(
            404,
            "This notification is not about an approval for you, so there is no Teams card for it.",
        )
    assert task is not None
    req = session.get(m.Request, note.req_id)
    if req is None:
        raise HTTPException(404, f"There is no request {note.req_id}.")
    plain = bankfields.unseal(req.payload)
    title = title_of(req.domain.value, plain)  # a name only: never a bank field
    recipient = session.get(m.User, note.user_id)
    requestor = session.get(m.User, req.requestor_user_id)
    country = country_names().get(req.country, req.country)

    facts = [
        CardFact(title="Request", value=req.req_id),
        CardFact(title="Record", value=f"{DOMAIN_WORDS[req.domain.value]}, {req.entity} {country}"),
        CardFact(
            title="Requested by", value=requestor.name if requestor else req.requestor_user_id
        ),
        CardFact(title="Your part", value=role_label(task)),
    ]
    is_open = task.status == "pending"
    if is_open and task.due_at is not None:
        due = clock.format_due(task.due_at, recipient.country if recipient else None)
        facts.append(CardFact(title="Decide by", value=due))

    body: list[CardTextBlock | CardFactSet] = [
        CardTextBlock(text="Lives Group MDM", size="Small", isSubtle=True),
        CardTextBlock(text=HEADLINE[note.kind], size="Medium", weight="Bolder", spacing="None"),
        CardTextBlock(text=title, size="Large", weight="Bolder"),
        CardFactSet(facts=facts),
    ]
    if not is_open:
        body.insert(
            3,  # under the record's name, above the facts
            CardTextBlock(text=CLOSED_STATUS.get(task.status, "Already decided."), weight="Bolder"),
        )
    if bankfields.has_bank_details(plain):
        body.append(
            CardTextBlock(
                text="Bank details are not included in this card. Open the request to check them.",
                isSubtle=True,
                size="Small",
            )
        )

    def submit(label: str, action: str) -> CardActionSubmit:
        return CardActionSubmit(
            title=label, data={"action": action, "task_id": task.task_id, "req_id": req.req_id}
        )

    open_link = CardActionOpenUrl(title="Open", url=f"{web_origin()}/requests/{req.req_id}")
    if not is_open:
        return AdaptiveCard(body=body, actions=[open_link])
    return AdaptiveCard(
        body=body,
        actions=[
            submit("Approve", "approve"),
            submit("Ask for info", "ask_info"),
            submit("Reject", "reject"),
            open_link,
        ],
    )

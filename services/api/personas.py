"""Seeded demo users (PRD §3). Backup approvers are added with users.csv later."""

from services.api.schemas import Persona

PERSONAS: list[Persona] = [
    Persona(
        user_id="amy",
        name="Amy",
        title="Product Manager",
        roles=["requestor"],
        entity="SPD",
        country="SG",
    ),
    Persona(
        user_id="marcus",
        name="Marcus",
        title="Regional Sales (new BU)",
        roles=["requestor"],
        entity="QTG",
        country="VN",
    ),
    Persona(
        user_id="weijie",
        name="Wei Jie",
        title="Finance Manager",
        roles=["finance"],
        entity="Group",
        country="SG",
    ),
    Persona(
        user_id="priya",
        name="Priya",
        title="MDM Analyst",
        roles=["mdm_analyst"],
        entity="Group",
        country="SG",
    ),
    Persona(
        user_id="daniel",
        name="Daniel",
        title="BU Head",
        roles=["bu_head"],
        entity="SPD",
        country="SG",
    ),
    Persona(
        user_id="nurul",
        name="Nurul",
        title="Quality / Regulatory",
        roles=["quality_regulatory"],
        entity="Group",
        country="MY",
    ),
    Persona(
        user_id="meiling",
        name="Mei Ling",
        title="Business Support",
        roles=["business_support"],
        entity="Group",
        country="SG",
    ),
    Persona(
        user_id="huimin",
        name="Hui Min",
        title="Finance (second approver)",
        roles=["finance"],
        entity="Group",
        country="SG",
    ),
]

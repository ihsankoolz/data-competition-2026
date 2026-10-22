"""Modelled cycle time, old email process vs new parallel process (PRD M10, D-018 item 4).

Old = mdm_requests_history.csv as recorded (sequential approvals, bounce loops). New = the same
requests replayed through the new rules (one parallel stage, reminder at 1 business day,
escalation at 2, no missing-field bounces). Every assumption is returned with its source.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def ops_impact(data_dir: Path, duplicates_prevented: int = 0) -> dict[str, Any]:
    """-> OpsImpact. `duplicates_prevented` = live requests linked to an existing record."""
    raise NotImplementedError

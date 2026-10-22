"""Layered duplicate check (D-005). Public API:

index = MasterIndex(load_master("data/fixtures/seasonal_trend"))   # once
result = check(BPQuery(CardName="Benh vien Cho Ray", Country="VN",
                       FederalTaxID="0301234567"), index)          # per form change
"""

from .io import load_master
from .matcher import MasterIndex, check, score_candidates
from .schemas import (
    BPQuery,
    BPRecord,
    Candidate,
    DedupConfig,
    DedupResult,
    JudgeOpinion,
    Reason,
    RelatedRecord,
)

__all__ = [
    "BPQuery",
    "BPRecord",
    "Candidate",
    "DedupConfig",
    "DedupResult",
    "JudgeOpinion",
    "MasterIndex",
    "Reason",
    "RelatedRecord",
    "check",
    "load_master",
    "score_candidates",
]

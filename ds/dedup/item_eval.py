"""Scores the item duplicate check on the hand-made test set (`item_eval_set.yaml`).

Small and written by us, not generator ground truth (the generator plants no item duplicates).
Used by `notebooks/eval_item_dedup.py` (docs/results.md) and `tests/test_item_dedup.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from ds.dedup.items import ItemIndex, ItemQuery, check_item, records_from_fixtures

EVAL_SET_PATH = Path(__file__).with_name("item_eval_set.yaml")
FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "seasonal_trend"


class EvalCase(BaseModel):
    id: str
    kind: str
    same: bool
    item: str
    query: ItemQuery


class CaseResult(BaseModel):
    id: str
    kind: str
    same: bool
    item: str
    name: str
    level: Literal["likely", "possible", "none"]  # how the check graded THIS pair
    score: float | None = None
    top: str | None = None  # the check's top candidate (any item)


class LevelScore(BaseModel):
    level: Literal["likely", "likely_or_possible"]
    tp: int
    fp: int
    fn: int
    tn: int
    precision: float
    recall: float


class ItemEvalReport(BaseModel):
    n_pairs: int
    n_same: int
    n_different: int
    scores: list[LevelScore]
    cases: list[CaseResult]


def load_cases(path: Path | str = EVAL_SET_PATH) -> list[EvalCase]:
    with open(path, encoding="utf-8") as fh:
        return [EvalCase.model_validate(c) for c in yaml.safe_load(fh)["cases"]]


def _score(cases: list[CaseResult], flagged: set[str], level: str) -> LevelScore:
    tp = sum(c.same and c.level in flagged for c in cases)
    fp = sum((not c.same) and c.level in flagged for c in cases)
    fn = sum(c.same and c.level not in flagged for c in cases)
    tn = sum((not c.same) and c.level not in flagged for c in cases)
    return LevelScore(
        level=level,  # type: ignore[arg-type]
        tp=tp,
        fp=fp,
        fn=fn,
        tn=tn,
        precision=round(tp / (tp + fp), 4) if tp + fp else 0.0,
        recall=round(tp / (tp + fn), 4) if tp + fn else 0.0,
    )


def evaluate(
    cases: list[EvalCase] | None = None, fixture_dir: Path | str = FIXTURES
) -> ItemEvalReport:
    cases = cases if cases is not None else load_cases()
    index = ItemIndex(records_from_fixtures(fixture_dir))
    out: list[CaseResult] = []
    for c in cases:
        res = check_item(c.query, index)
        mine = next((x for x in res.candidates if x.ItemCode == c.item), None)
        out.append(
            CaseResult(
                id=c.id,
                kind=c.kind,
                same=c.same,
                item=c.item,
                name=c.query.ItemName,
                level=mine.verdict if mine else "none",
                score=mine.score if mine else None,
                top=res.candidates[0].ItemCode if res.candidates else None,
            )
        )
    return ItemEvalReport(
        n_pairs=len(out),
        n_same=sum(c.same for c in out),
        n_different=sum(not c.same for c in out),
        scores=[
            _score(out, {"likely"}, "likely"),
            _score(out, {"likely", "possible"}, "likely_or_possible"),
        ],
        cases=out,
    )

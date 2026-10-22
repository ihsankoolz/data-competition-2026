"""M10 modelled cycle time (D-018 item 4): contract shape and sanity of the model."""

from __future__ import annotations

from pathlib import Path

import pytest

from ds.analytics.cycle_time import (
    WAIT_CAP_BD,
    ops_details,
    ops_impact,
    replay_all,
    replay_request,
)
from services.api.schemas import OpsImpact

FIX = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "seasonal_trend"


@pytest.fixture(scope="module")
def impact() -> dict:
    return ops_impact(FIX, duplicates_prevented=3)


def test_matches_the_api_contract(impact):
    m = OpsImpact.model_validate(impact)
    assert [c.process for c in m.cycle_time] == ["old_email_sequential", "new_parallel"]
    assert m.duplicates_prevented == 3
    assert m.amy_before_bd == 18.0
    assert "modelled, not measured" in m.caption.lower()
    assert {a.source for a in m.assumptions} == {
        "brief",
        "generated_history",
        "our_design",
        "assumption",
    }


def test_new_process_is_not_slower(impact):
    old, new = impact["cycle_time"]
    assert new["median_bd"] <= old["median_bd"]
    assert new["p90_bd"] <= old["p90_bd"]
    assert impact["amy_after_bd"] < impact["amy_before_bd"]
    assert impact["first_time_right_after_pct"] >= impact["first_time_right_before_pct"]
    reqs = replay_all(FIX)
    slower = [r for r in reqs if r.new_bd > r.old_bd + 1e-9]
    assert len(slower) <= 0.01 * len(reqs)  # reported in docs/results.md, not hidden


def test_old_numbers_are_the_recorded_history():
    d = ops_details(FIX)
    # data-spec 12.1, seed 42: median 14.7, P90 25.0 business days, 38.5% bounced
    assert d["old_median"] == pytest.approx(14.7, abs=0.05)
    assert d["old_p90"] == pytest.approx(25.0, abs=0.1)
    assert 100 - d["ftr_before"] == pytest.approx(38.5, abs=0.1)


def _row(**kw) -> dict:
    base = dict(
        req_id="T-1",
        domain="customer",
        is_ivd="",
        approval_sequence="bu_head>finance>business_support",
        submitted_at="2026-10-05T09:00:00+08:00",  # Monday
        bu_head_approved_at="2026-10-06T09:00:00+08:00",  # 1 bd
        finance_approved_at="2026-10-12T09:00:00+08:00",  # +4 bd
        quality_regulatory_approved_at="",
        business_support_approved_at="2026-10-13T09:00:00+08:00",  # +1 bd
        keyed_at="2026-10-15T09:00:00+08:00",  # +2 bd
        bounced_for_missing_fields="false",
        bounce_count="0",
        missing_fields="",
        cycle_business_days="8.00",
    )
    return base | kw


def test_parallel_stage_is_the_max_of_capped_waits_not_the_sum():
    r = replay_request(_row())
    assert r.step_waits == pytest.approx({"bu_head": 1, "finance": 4, "business_support": 1})
    # stage = max(min(w, cap)) = cap (finance waited 4 > cap); publish = min(2, 1) = 1
    assert r.new_bd == pytest.approx(WAIT_CAP_BD + 1.0)
    assert r.bounces_after == 0


def test_checked_fields_stop_bouncing_unchecked_ones_still_bounce():
    caught = replay_request(
        _row(bounced_for_missing_fields="true", bounce_count="1", missing_fields="tax_id")
    )
    assert caught.bounces_after == 0
    still = replay_request(
        _row(bounced_for_missing_fields="true", bounce_count="1", missing_fields="credit_terms")
    )
    assert still.bounces_after == 1
    assert still.new_bd > caught.new_bd

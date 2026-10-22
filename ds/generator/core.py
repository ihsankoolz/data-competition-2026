"""Generator entry point: `generate(scenario, seed, out)` writes data/generated/<scenario>/."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml

from . import catalog, demand, emails, ops
from .common import write_csv
from .master import (
    BP_COLS,
    GOLDEN_COLS,
    bp_rows,
    build_master,
    churn_rows,
    golden_map_rows,
    golden_rows,
    hard_negative_rows,
)
from .users import USER_COLS, user_rows

PARAMS_PATH = Path(__file__).with_name("params.yaml")


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_params(scenario: str, path: Path = PARAMS_PATH) -> dict:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if scenario not in raw["scenarios"]:
        raise ValueError(f"unknown scenario {scenario!r}; known: {sorted(raw['scenarios'])}")
    return _merge(raw["common"], raw["scenarios"][scenario] or {})


def generate(scenario: str, seed: int, out: Path | str) -> Path:
    params = load_params(scenario)
    root = Path(out) / scenario
    gt = root / "ground_truth"
    gt.mkdir(parents=True, exist_ok=True)

    resolved = {"scenario": scenario, "seed": seed, "params": params}
    (root / "params.yaml").write_text(
        yaml.safe_dump(resolved, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )

    m = build_master(params, seed)
    vendor_rows, twin_codes = catalog.vendor_rows(m, params, seed)

    write_csv(root / "customers_golden.csv", GOLDEN_COLS, golden_rows(m))
    write_csv(root / "bp_records.csv", BP_COLS, bp_rows(m, params))
    write_csv(root / "vendors.csv", catalog.VENDOR_COLS, vendor_rows)
    write_csv(root / "items.csv", catalog.ITEM_COLS, catalog.item_rows())
    write_csv(root / "item_registrations.csv", catalog.REG_COLS, catalog.registration_rows(seed))

    write_csv(
        gt / "bp_golden_map.csv",
        ["CardCode", "golden_id", "record_role", "dup_of", "family"],
        golden_map_rows(m),
    )
    write_csv(
        gt / "dup_pairs.csv",
        [
            "golden_id",
            "card_code_a",
            "card_code_b",
            "dup_type",
            "tax_id_state",
            "is_migration",
            "entity_a",
            "entity_b",
        ],
        m.dup_pairs,
    )
    write_csv(
        gt / "hard_negatives.csv",
        [
            "card_code_a",
            "card_code_b",
            "not_dup_reason",
            "golden_id_a",
            "golden_id_b",
            "group_id",
            "note",
        ],
        hard_negative_rows(m, twin_codes),
    )
    write_csv(
        gt / "migrations.csv",
        [
            "golden_id",
            "old_card_code",
            "new_card_code",
            "switch_month",
            "country",
            "entity",
            "product_family",
        ],
        m.migrations,
    )
    write_csv(
        gt / "churn.csv",
        ["golden_id", "country", "decline_start_month", "churn_month", "decline_months"],
        churn_rows(m),
    )
    from .curated import GROUPS

    groups = []
    for gid in sorted(GROUPS):
        members = [g for g in m.golden if g.spec.group_id == gid]
        groups.append(
            [
                gid,
                GROUPS[gid],
                " ".join(g.country for g in members),
                " ".join(g.golden_id for g in members),
            ]
        )
    write_csv(gt / "groups.csv", ["group_id", "group_name", "countries", "golden_ids"], groups)

    # ---- v2 (data-spec §6-9). New named RNG streams only, so §1-5 output never shifts.
    write_csv(root / "users.csv", USER_COLS, user_rows())
    dem = demand.build_orders(m, params, seed)
    enqs = demand.build_enquiries(m, dem, params, seed)
    mdm_reqs = ops.build_mdm_history(params, seed)
    email_rows, label_rows = emails.build_inbox(m, dem, enqs, params, seed)  # sets source ids
    write_csv(root / "orders.csv", demand.ORDER_COLS, demand.order_rows(dem))
    write_csv(root / "enquiries.csv", demand.ENQUIRY_COLS, demand.enquiry_rows(enqs))
    write_csv(
        root / "dirty_demand.csv",
        demand.DIRTY_COLS,
        demand.dirty_rows(m, dem, enqs, mdm_reqs, params, seed),
    )
    write_csv(root / "mdm_requests_history.csv", ops.MDM_COLS, ops.mdm_rows(mdm_reqs))
    write_jsonl(root / "emails.jsonl", email_rows)
    write_jsonl(gt / "email_labels.jsonl", label_rows)
    return root


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

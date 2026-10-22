"""Shared helpers for the database, seed, audit and publisher tests.

`make_fixture_dir` builds a fixtures folder in a temp dir: the master files come from the real v1
generator (`python -m ds.generator --scenario seasonal_trend --seed 42`), and the v2 files that do
not exist yet (users, orders, enquiries, dirty demand, MDM history, emails) are small handmade
files with the columns from data-spec §7/§8 and the users.csv contract in D-015.
"""

# ruff: noqa: E501
from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from services.api import clock

REPO_ROOT = Path(__file__).resolve().parents[1]
MASTER_FILES = ["bp_records.csv", "vendors.csv", "items.csv", "item_registrations.csv"]

USERS = [
    ("amy", "Amy", "Product Manager", "requestor", "SPD", "SG", ""),
    ("marcus", "Marcus", "Regional Sales (new BU)", "requestor", "QTG", "VN", ""),
    ("weijie", "Wei Jie", "Finance Manager", "finance", "Group", "SG", ""),
    ("priya", "Priya", "MDM Analyst", "mdm_analyst", "Group", "SG", ""),
    ("daniel", "Daniel", "BU Head", "bu_head|requestor", "SPD", "SG", ""),
    ("nurul", "Nurul", "Quality / Regulatory", "quality_regulatory", "Group", "MY", ""),
    ("meiling", "Mei Ling", "Business Support", "business_support", "Group", "SG", ""),
    ("huimin", "Hui Min", "Finance (second approver)", "finance", "Group", "SG", ""),
    ("jun", "Jun", "Finance (backup)", "finance", "Group", "SG", "weijie"),
]


@lru_cache(maxsize=1)
def _generated_master() -> Path:
    out = Path(tempfile.mkdtemp(prefix="lives-gen-"))
    subprocess.run(
        [
            sys.executable,
            "-m",
            "ds.generator",
            "--scenario",
            "seasonal_trend",
            "--seed",
            "42",
            "--out",
            str(out),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return out / "seasonal_trend"


def _write_csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def make_fixture_dir(dest: Path) -> Path:
    """Fixtures folder: generator v1 master files plus handmade v2 files."""
    dest.mkdir(parents=True, exist_ok=True)
    master = _generated_master()
    for name in MASTER_FILES:
        shutil.copy(master / name, dest / name)
    # Ground truth must be ignored by the seed loader: put it where a real fixture has it.
    shutil.copy(master / "customers_golden.csv", dest / "customers_golden.csv")
    shutil.copytree(master / "ground_truth", dest / "ground_truth", dirs_exist_ok=True)

    _write_csv(
        dest / "users.csv",
        ["user_id", "name", "title", "roles", "entity", "country", "backup_for"],
        [list(u) for u in USERS],
    )
    order_header = [
        "doc_num", "card_code", "entity", "country", "item_code", "qty",
        "unit_price_usd", "doc_date", "po_ref", "source_email_id",
    ]  # fmt: skip
    _write_csv(
        dest / "orders.csv",
        order_header,
        [
            ["SO100001", "C00001", "SPD", "VN", "A-DEN-NS1", 20, 118.0, "2026-01-12", "PO-1", ""],
            ["SO100002", "C00002", "SPD", "VN", "A-HBA-1C", 5, 165.0, "2026-02-03", "PO-2", "E-9"],
            ["SO100003", "C00003", "QTG", "ID", "A-DEN-IGM", 8, 96.0, "2026-02-20", "", ""],
            # second line of the same PO: doc_num repeats per line, as in the generator
            ["SO100003", "C00003", "QTG", "ID", "A-CRP-QT", 4, 72.0, "2026-02-20", "", ""],
        ],
    )
    _write_csv(
        dest / "enquiries.csv",
        [*order_header, "kind", "converted_doc_num"],
        [
            ["EQ200001", "C00001", "SPD", "VN", "A-DEN-NS1", 30, "", "2026-03-01", "", "", "enquiry", ""],
            ["EQ200002", "C00002", "SPD", "VN", "A-HBA-1C", 10, "", "2026-03-04", "", "", "purchase_request", "SO100002"],
        ],
    )  # fmt: skip
    _write_csv(
        dest / "dirty_demand.csv",
        [*order_header, "leak_source"],
        [
            ["SO100001", "C00001", "SPD", "VN", "A-DEN-NS1", 20, 118.0, "2026-01-12", "PO-1", "", ""],
            ["EQ200001", "C00001", "SPD", "VN", "A-DEN-NS1", 30, "", "2026-03-01", "", "", "enquiry"],
        ],
    )  # fmt: skip
    _write_csv(
        dest / "mdm_requests_history.csv",
        [
            "req_id", "domain", "entity", "country", "requestor", "submitted_at",
            "approval_1_at", "approval_2_at", "keyed_at",
            "bounced_for_missing_fields", "bounce_count",
        ],
        [
            ["H-0001", "customer", "SPD", "SG", "amy", "2025-01-06 09:00", "2025-01-10 10:00",
             "2025-01-15 11:00", "2025-01-27 12:00", "true", 1],
            ["H-0002", "item", "SPD", "SG", "amy", "2025-02-03 09:00", "2025-02-05 10:00",
             "", "", "false", 0],
        ],
    )  # fmt: skip
    emails = [
        {
            "email_id": "DEMO-01",
            "received_at": "2026-10-05T09:00:00+08:00",
            "from_name": "Marcus Tran",
            "from_address": "marcus@qtg.example",
            "to": "mdm@lives.example",
            "subject": "New customer Benh vien Cho Ray",
            "body": "Pls create new customer Benh vien Cho Ray, HCMC, MST 0301234567",
            "attachments": [],
            "thread_id": "T-1",
        },
        {
            "email_id": "DEMO-03",
            "received_at": "2026-10-05T10:00:00+08:00",
            "from_name": "RSCM",
            "from_address": "purchasing@rscm.example",
            "to": ["orders@lives.example"],
            "subject": "PO RSCM/2026/118",
            "body": "Mohon dikirim 50 box A-DEN-NS1",
            "attachments": ["PO_118.pdf"],
            "thread_id": "T-2",
        },
    ]
    (dest / "emails.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in emails) + "\n", encoding="utf-8"
    )
    return dest


def count_lines(path: Path) -> int:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return sum(1 for _ in csv.DictReader(fh))


@pytest.fixture
def enc_key(monkeypatch):
    """A fresh Fernet key, in the environment for this test only."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", key)
    return key


@pytest.fixture
def sim_clock():
    clock.reset()
    yield clock
    clock.reset()

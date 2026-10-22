"""The replay cache is committed and the repo goes public (D-016): no bank data may be in it."""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "fixtures" / "llm_cache"
VENDORS = ROOT / "data" / "fixtures" / "seasonal_trend" / "vendors.csv"
DEMO_BANK = ["072-123456-7", "0721234567", "DBSSSGSG", "123-456789-001", "HSBCHKHHHKH"]


def _secrets() -> list[str]:
    out = set(DEMO_BANK)
    with open(VENDORS, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            for k in ("AccountNo", "IBAN", "BICSwiftCode"):
                v = (r.get(k) or "").strip()
                if v:
                    out.add(v)
    return sorted(out)


def _cache_files() -> list[Path]:
    return sorted(CACHE.rglob("*.json"))


def test_cache_holds_no_bank_value():
    secrets = _secrets()
    assert len(secrets) > 20  # the vendor file really was read
    leaks = []
    for p in _cache_files():
        text = p.read_text(encoding="utf-8")
        leaks += [(p.name, s) for s in secrets if s in text]
    assert leaks == []


def test_cache_holds_no_api_key_shaped_string():
    for p in _cache_files():
        assert "sk-ant-" not in p.read_text(encoding="utf-8")


def test_cache_files_are_lf():
    for p in _cache_files():
        assert b"\r\n" not in p.read_bytes(), p


def test_gitattributes_keeps_fixtures_lf():
    attrs = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "data/fixtures/** text eol=lf" in attrs


def test_cache_has_every_fixture_email():
    assert len(list((CACHE / "interpreter").glob("*.json"))) >= 88

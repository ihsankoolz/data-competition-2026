"""Bank details inside a request's form fields (`BPBankAccounts`), domain rule 5.

* At rest: `AccountNo` and `IBAN` are Fernet ciphertext inside the JSON payload (`seal`).
* In responses: everything is masked unless the acting user has the Finance role (`view`).
* Never logged: callers pass values through `audit.scrub`, which masks bank keys.
"""

from __future__ import annotations

import copy
from typing import Any

from services.api.crypto import ENCRYPTED_BANK_FIELDS, decrypt, encrypt, mask

BANK_KEY = "BPBankAccounts"
_LAST4 = ("AccountNo", "IBAN")
_HIDDEN = ("BankCode", "AccountName", "BICSwiftCode")


def is_masked(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("****")


def _rows(fields: dict[str, Any]) -> list[dict[str, Any]]:
    rows = fields.get(BANK_KEY)
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def seal(fields: dict[str, Any]) -> dict[str, Any]:
    """Copy of `fields` with the secret bank values encrypted (for the database)."""
    out = copy.deepcopy(fields)
    for row in _rows(out):
        for k in ENCRYPTED_BANK_FIELDS:
            if isinstance(row.get(k), str):
                row[k] = encrypt(row[k])
    return out


def unseal(fields: dict[str, Any]) -> dict[str, Any]:
    """Copy of `fields` with the bank values decrypted. Server-side use only."""
    out = copy.deepcopy(fields)
    for row in _rows(out):
        for k in ENCRYPTED_BANK_FIELDS:
            if isinstance(row.get(k), str):
                row[k] = decrypt(row[k])
    return out


def view(plain_fields: dict[str, Any], *, is_finance: bool) -> dict[str, Any]:
    """What an API response may show: bank values are masked unless the actor is Finance."""
    out = copy.deepcopy(plain_fields)
    if is_finance:
        return out
    for row in _rows(out):
        for k in _LAST4:
            if isinstance(row.get(k), str):
                row[k] = mask(row[k], keep=4)
        for k in _HIDDEN:
            if isinstance(row.get(k), str) and row[k]:
                row[k] = mask(row[k], keep=0)
    return out


def merge_masked(old_plain: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """A client that was shown masked values may send them back unchanged. Keep the stored
    value wherever the incoming one is still masked (a masked value is never stored)."""
    if not isinstance(incoming.get(BANK_KEY), list):
        return incoming
    old_rows = old_plain.get(BANK_KEY) if isinstance(old_plain.get(BANK_KEY), list) else []
    merged = copy.deepcopy(incoming)
    for i, row in enumerate(merged[BANK_KEY]):
        if not isinstance(row, dict):
            continue
        old_row = old_rows[i] if i < len(old_rows) and isinstance(old_rows[i], dict) else {}
        for k, v in list(row.items()):
            if is_masked(v):
                if old_row.get(k) is None:
                    del row[k]
                else:
                    row[k] = old_row[k]
    return merged


def has_bank_details(fields: dict[str, Any]) -> bool:
    return any(any(v for k, v in r.items() if k != "Country") for r in _rows(fields))

"""Bank details are removed from email text before any LLM call and masked for non-Finance
readers (domain rule 5). One implementation, used by ds.interpreter and services/api.

Bank details must be entered in the secure form field; email text never sets them (rule 7).
The patterns err on the side of removing too much: losing a harmless number costs nothing,
leaking an account number does.
"""

from __future__ import annotations

import re

MASK = "[bank details removed]"

_PATTERNS = [
    # "Account No 072-123456-7", "account no. 123-456789-001", "A/C: 1234 5678 90", "acct #..."
    re.compile(
        r"\b(?:bank\s+)?(?:account|acct|a/c|rekening|tai\s+khoan|tài\s+khoản|บัญชี)"
        r"(?:\s*(?:no\.?|number|num|#|nr\.?|số))?\s*[:.#]?\s*[A-Z0-9][A-Z0-9 \-]{4,30}[0-9]",
        re.IGNORECASE,
    ),
    # IBAN: two letters, two digits, 11-30 alphanumerics (spaces allowed)
    re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?\b"),
    # "SWIFT DBSSSGSG", "BIC: HSBCHKHHHKH", "swift code HSBCHKHH"
    re.compile(
        r"\b(?:swift|bic)(?:\s*(?:/\s*bic|code))?\s*[:.]?\s*[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b",
        re.IGNORECASE,
    ),
]


def strip_bank_details(text: str) -> tuple[str, bool]:
    """Return (`text` with every bank detail replaced by MASK, whether anything was found)."""
    found = False
    for pattern in _PATTERNS:
        text, n = pattern.subn(MASK, text)
        found = found or n > 0
    return text, found

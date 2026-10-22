"""Field-level encryption and masking for bank details (D-015, domain rule 5).

The Fernet key is read from the environment variable `FIELD_ENCRYPTION_KEY` at the moment it is
needed. There is no default and no fallback: without a key, anything that touches an encrypted
column fails with `MissingEncryptionKeyError` and a message that says what to do.

Which bank fields are encrypted at rest (`ENCRYPTED_BANK_FIELDS`): the two that can be used to
move money, `AccountNo` and `IBAN`. The other bank columns are not secrets on their own:
`BankCode` and `BICSwiftCode` identify a bank (public), `AccountName` is the vendor's legal name
(already stored in plain text on the business partner) and `BankCountry` is a country code.
All of them are still masked in audit rows and logs (`BANK_FIELDS`).
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

KEY_ENV = "FIELD_ENCRYPTION_KEY"

_HOW_TO_GENERATE = (
    'python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"'
)

# Encrypted at rest.
ENCRYPTED_BANK_FIELDS = frozenset({"AccountNo", "IBAN"})
# Masked in audit payloads and any other output (superset of the encrypted ones).
BANK_FIELDS = frozenset(
    {"BankCode", "AccountNo", "AccountName", "BICSwiftCode", "IBAN"}
    | {"account_no", "iban", "bank_code", "account_name", "bic_swift_code"}
)

MASK_CHAR = "*"


class EncryptionKeyError(RuntimeError):
    """Base class for key problems."""


class MissingEncryptionKeyError(EncryptionKeyError):
    def __init__(self) -> None:
        super().__init__(
            f"{KEY_ENV} is not set. Bank details are encrypted at rest and cannot be read or "
            f"written without it. Generate a key with: {_HOW_TO_GENERATE} and put it in .env "
            f"as {KEY_ENV}=<key>."
        )


class DecryptionError(EncryptionKeyError):
    def __init__(self) -> None:
        super().__init__(
            f"A stored value could not be decrypted: {KEY_ENV} is different from the key used "
            "to write it. Restore the original key or run `make reset-demo` to reseed."
        )


@lru_cache(maxsize=8)
def _fernet_for(key: str) -> Fernet:
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        raise EncryptionKeyError(
            f"{KEY_ENV} is not a valid Fernet key (it must be 44 url-safe base64 characters). "
            f"Generate one with: {_HOW_TO_GENERATE}"
        ) from None


def get_fernet() -> Fernet:
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        raise MissingEncryptionKeyError
    return _fernet_for(key)


def require_key() -> None:
    """Fail early (before doing destructive work) if the key is missing or malformed."""
    get_fernet()


def encrypt(value: str | None) -> str | None:
    if value is None or value == "":
        return value
    return get_fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(token: str | None) -> str | None:
    if token is None or token == "":
        return token
    try:
        return get_fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        raise DecryptionError from None


def mask(value: str | None, keep: int = 4) -> str | None:
    """`'7270029477'` -> `'****9477'`. Values no longer than `keep` are fully masked."""
    if value is None or value == "":
        return value
    if keep <= 0 or len(value) <= keep:
        return MASK_CHAR * 4
    return MASK_CHAR * 4 + value[-keep:]


class EncryptedString(TypeDecorator[str]):
    """Stores ciphertext in the column; the ORM sees plain text. Raw SQL sees only ciphertext."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        return encrypt(value)

    def process_result_value(self, value: Any, dialect: Any) -> str | None:
        return decrypt(value)

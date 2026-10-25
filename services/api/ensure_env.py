"""Make sure `.env` has a FIELD_ENCRYPTION_KEY, so a fresh clone runs after `make setup`.

- No `.env`: copy `.env.example` and put a new Fernet key in FIELD_ENCRYPTION_KEY.
- `.env` with the key blank or missing: fill in only that line, leave the rest as it is.
- `.env` with a key already: change nothing (a new key would make stored bank details unreadable).

The key itself is never printed, only what was done.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from cryptography.fernet import Fernet

from services.api.crypto import KEY_ENV

# `KEY=` with nothing after it but spaces and an optional inline comment.
_BLANK = re.compile(rf"^{KEY_ENV}=\s*(#.*)?$")
_SET = re.compile(rf"^{KEY_ENV}=\s*[^\s#]")


def ensure_env(env: Path, example: Path) -> str:
    """Create or fill `env` as described above. Returns the one-line message to print."""
    line = f"{KEY_ENV}={Fernet.generate_key().decode()}"
    if not env.exists():
        lines = example.read_text(encoding="utf-8").splitlines()
        lines = [line if _BLANK.match(x) else x for x in lines]
        if line not in lines:
            lines.append(line)
        env.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))  # LF: make reads it
        return f"Created .env with a new {KEY_ENV}"

    text = env.read_text(encoding="utf-8")
    lines = text.splitlines()
    if any(_SET.match(x) for x in lines):
        return "Left .env alone"
    if any(_BLANK.match(x) for x in lines):
        lines = [line if _BLANK.match(x) else x for x in lines]
    else:
        lines.append(line)
    newline = "\r\n" if "\r\n" in text else "\n"
    env.write_bytes((newline.join(lines) + newline).encode("utf-8"))
    return f"Filled {KEY_ENV}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"Make sure .env has a {KEY_ENV}.")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--example", default=".env.example")
    args = parser.parse_args(argv)
    print(ensure_env(Path(args.env), Path(args.example)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

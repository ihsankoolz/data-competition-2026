"""Every detail key the interpreter can return has a plain label in the web app."""

import re
from pathlib import Path
from typing import get_args

from ds.interpreter.prompt import FieldKey

EMAILS_TS = Path(__file__).resolve().parents[1] / "apps" / "web" / "lib" / "emails.ts"


def _ts_labels() -> dict[str, str]:
    src = EMAILS_TS.read_text(encoding="utf-8")
    block = re.search(r"export const FIELD_LABELS[^{]*\{(.*?)\n\};", src, re.S)
    assert block, "FIELD_LABELS not found in apps/web/lib/emails.ts"
    return dict(re.findall(r"^\s*(\w+): \"([^\"]+)\",$", block.group(1), re.M))


def test_field_labels_match_interpreter_keys() -> None:
    labels = _ts_labels()
    keys = set(get_args(FieldKey))
    assert set(labels) == keys, (
        f"missing labels: {sorted(keys - set(labels))}; "
        f"labels for unknown keys: {sorted(set(labels) - keys)}"
    )


def test_field_labels_are_plain_words() -> None:
    for key, label in _ts_labels().items():
        assert "_" not in label and label != key, f"{key} has no plain label: {label!r}"

"""The interpreter is FROZEN for the held-out email test (D-018 item 1).

These hashes were recorded before the held-out emails (`data/fixtures/holdout_emails.jsonl`)
were generated, and before the interpreter ever read them. If this test fails, someone changed
the prompt, the model-facing schema, the keyword baseline or the required-fields config after
the held-out run. That is allowed only together with a fresh, never-seen held-out set: the
current held-out numbers in docs/results.md would no longer be "unseen" for the new version.
Do not just update the hashes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ds.interpreter.prompt import PROMPT_VERSION, SYSTEM_PROMPT, EmailReading

ROOT = Path(__file__).resolve().parents[1]

FROZEN_PROMPT_VERSION = "interpreter_v2"
FROZEN_SYSTEM_PROMPT_SHA256 = "f60cd870ede9d5e8d0ebf62fa70044382f716567ac2684d1ac0b582a6757f75b"
FROZEN_SCHEMA_SHA256 = "fe2aad625466d3a9f80abbdb0aacb6fc3b0042678033fed93e63d49b1bde15e6"
FROZEN_FILES = {
    "ds/interpreter/keywords.py": (
        "936ff64ab0c82943de6935cfeeb5f882dfbbae2f020b79e7ba8cddfb012ad3ef"
    ),
    "config/required_fields.yaml": (
        "b17eece5121b25bf9a2990fd5c264a73405dc550ec231f281976de72f3d0bea0"
    ),
}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def test_prompt_version_is_frozen():
    assert PROMPT_VERSION == FROZEN_PROMPT_VERSION


def test_system_prompt_text_is_frozen():
    assert _sha(SYSTEM_PROMPT.encode()) == FROZEN_SYSTEM_PROMPT_SHA256


def test_model_output_schema_is_frozen():
    schema = json.dumps(EmailReading.model_json_schema(), sort_keys=True).encode()
    assert _sha(schema) == FROZEN_SCHEMA_SHA256


def test_keyword_baseline_and_required_fields_are_frozen():
    for rel, want in FROZEN_FILES.items():
        raw = (ROOT / rel).read_bytes().replace(b"\r\n", b"\n")  # checkout-independent
        assert _sha(raw) == want, f"{rel} changed after the held-out run"

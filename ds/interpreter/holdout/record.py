"""Record the FROZEN interpreter's answers on the held-out emails into the replay cache.

Runs `ds.interpreter.api.interpret_email` exactly as the app does (bank stripping, fast model,
prompt `interpreter_v2`, quote check), in record mode. Labels are never read here.

Run: `LLM_MODE=record uv run --env-file .env python -m ds.interpreter.holdout.record`
"""

from __future__ import annotations

import json
import sys

from ds.interpreter import llm
from ds.interpreter.api import interpret_email
from ds.interpreter.holdout.generate import OUT_EMAILS
from ds.interpreter.prompt import PROMPT_VERSION, TASK

# Claude Haiku 5.5 list prices (USD per million tokens), rough per-call tokens
PRICE_IN, PRICE_OUT, IN_TOK, OUT_TOK = 0.10, 0.50, 3000, 2048


def load_holdout() -> list[dict]:
    with open(OUT_EMAILS, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def main() -> int:
    emails = load_holdout()
    model = llm.resolve_model(TASK)
    est = len(emails) * (IN_TOK * PRICE_IN + OUT_TOK * PRICE_OUT) / 1e6
    print(f"{len(emails)} emails, {model} ({PROMPT_VERSION}), mode {llm.llm_mode()}, "
          f"worst case ~US${est:.3f}")  # fmt: skip
    bad = 0
    for e in emails:
        it = interpret_email(e["email_id"], e["subject"], e["body"], e["from_address"])
        bad += it.method != "llm"
        print(f"  {e['email_id']}: {it.method} {it.ai_status}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

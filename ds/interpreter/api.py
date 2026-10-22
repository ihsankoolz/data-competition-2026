"""Entry point the API calls. The data-scientist track implements it (M2, D-006)."""

from __future__ import annotations

from ds.interpreter.schemas import Interpretation


def interpret_email(
    email_id: str,
    subject: str,
    body: str,
    from_address: str,
    *,
    mode: str | None = None,
) -> Interpretation:
    """Classify one email and extract fields with source quotes.

    Never raises for AI problems: when the replay cache has no answer it returns the keyword
    baseline with `method="keyword_fallback"` and `ai_status="offline"`. Bank details are
    stripped before any LLM call. The returned object is safe to show to any role.
    """
    raise NotImplementedError("M2 interpreter: implemented by the data-scientist track")

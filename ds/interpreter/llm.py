"""The ONLY place that calls the Anthropic API (CLAUDE.md rule 8, D-006, D-010).

- Structured output: `client.messages.parse(..., output_format=PydanticModel)` (GA, D-014).
  The model gets no tools (rule 7); its answer is validated by Pydantic.
- Cache: one JSON file per call under data/fixtures/llm_cache/<task>/<key>.json, where
  key = sha256(model + "\\n" + prompt_version + "\\n" + input) (see `cache_key`).
- LLM_MODE (env): `replay` (default; cache only, never touches the network or imports the SDK),
  `record` (call the API and write the cache), `live` (call the API, write nothing).
- Each entry also stores sha256(system prompt). A replay hit recorded under a different system
  prompt is treated as offline ("bump prompt_version and re-record"); the key itself stays
  sha256(model + prompt_version + input) as rule 8 says.
- API calls time out after LLM_TIMEOUT_S seconds (default 20) with one retry.
- A replay miss, a missing key or an API error returns an LLMResult with status "offline" /
  "error" instead of raising, so callers can show an "AI offline" badge and carry on.
- Sampling: CLAUDE.md asks for temperature 0. The current API (anthropic-version 2026-10-21,
  SDK 2.x) rejects `temperature` on every model, so it is not sent. Determinism for the demo
  comes from the replay cache instead: the same input always returns the recorded answer.
- The API key is read from ANTHROPIC_API_KEY by the SDK at call time; it is never written to
  the cache or logged. Callers must strip bank details before calling (rule 5).
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

Mode = Literal["replay", "record", "live"]
Status = Literal["ok", "offline", "error"]

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_DIR = REPO_ROOT / "data" / "fixtures" / "llm_cache"

# model tiers (D-006): env-configurable, names match .env.example
_TIER_ENV = {
    "fast": ("LLM_MODEL_FAST", "claude-haiku-5-5"),
    "judge": ("LLM_MODEL_JUDGE", "claude-sonnet-5-5"),
}
_TASK_TIER = {"dedup_judge": "judge"}


class LLMResult(BaseModel, Generic[T]):
    status: Status
    output: T | None = None
    task: str
    model: str
    prompt_version: str
    cache_key: str
    from_cache: bool = False
    mode: Mode = "replay"
    message: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok" and self.output is not None


def llm_mode() -> Mode:
    mode = os.environ.get("LLM_MODE", "replay").strip().lower()
    return mode if mode in ("replay", "record", "live") else "replay"  # type: ignore[return-value]


def resolve_model(task: str, model: str | None = None) -> str:
    if model:
        return model
    env, default = _TIER_ENV[_TASK_TIER.get(task, "fast")]
    return os.environ.get(env) or default


def cache_dir() -> Path:
    return Path(os.environ.get("LLM_CACHE_DIR") or DEFAULT_CACHE_DIR)


def cache_key(model: str, prompt_version: str, user_input: str) -> str:
    """sha256(model + prompt_version + input), newline-separated so fields cannot run together."""
    return hashlib.sha256(f"{model}\n{prompt_version}\n{user_input}".encode()).hexdigest()


def _cache_path(task: str, key: str) -> Path:
    return cache_dir() / task / f"{key}.json"


def read_cache(task: str, key: str) -> dict | None:
    p = _cache_path(task, key)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_cache(task: str, key: str, entry: dict) -> Path:
    p = _cache_path(task, key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(entry, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",  # LF on Windows too: the cache is committed (.gitattributes eol=lf)
    )
    return p


def system_hash(system: str) -> str:
    """Stored in each cache entry (not in the key) so a changed prompt is caught on replay."""
    return hashlib.sha256(system.encode()).hexdigest()


def make_entry(
    task: str, model: str, prompt_version: str, system: str, user_input: str, output: BaseModel
) -> dict:
    """A complete cache entry. Used by record mode and by tests that seed the cache."""
    return {
        "task": task,
        "model": model,
        "prompt_version": prompt_version,
        "cache_key": cache_key(model, prompt_version, user_input),
        "system_sha256": system_hash(system),
        "input": user_input,
        "output": output.model_dump(mode="json"),
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def api_timeout_s() -> float:
    try:
        return float(os.environ.get("LLM_TIMEOUT_S", "20"))
    except ValueError:
        return 20.0


def _call_api(
    model: str, system: str, user_input: str, output_model: type[T], max_tokens: int
) -> T:
    import anthropic  # imported only in record/live mode

    # reads ANTHROPIC_API_KEY from env; bounded so a slow API cannot hang a request
    client = anthropic.Anthropic(timeout=api_timeout_s(), max_retries=1)
    response = client.messages.parse(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_input}],
        output_format=output_model,
    )
    if response.stop_reason == "refusal" or response.parsed_output is None:
        raise RuntimeError(f"no structured output (stop_reason={response.stop_reason})")
    return response.parsed_output


def call_structured(
    task: str,
    prompt_version: str,
    system: str,
    user_input: str,
    output_model: type[T],
    model: str | None = None,
    *,
    max_tokens: int = 2048,
    mode: Mode | None = None,
) -> LLMResult[T]:
    """One structured LLM call through the replay cache. Never raises for offline/API errors.

    `user_input` must already be the exact, deterministic text sent to the model (callers
    serialise payloads with sorted keys) because it is part of the cache key.
    """
    mode = mode or llm_mode()
    model = resolve_model(task, model)
    key = cache_key(model, prompt_version, user_input)
    base = dict(task=task, model=model, prompt_version=prompt_version, cache_key=key, mode=mode)

    if mode in ("replay", "record"):
        hit = read_cache(task, key)
        stale = hit is not None and hit.get("system_sha256") != system_hash(system)
        if stale and mode == "replay":
            return LLMResult[output_model](
                status="offline",
                message="AI offline: the prompt changed since this answer was recorded; "
                "bump prompt_version and re-record",
                **base,
            )
        if hit is not None and not stale:
            try:
                out = output_model.model_validate(hit["output"])
                return LLMResult[output_model](status="ok", output=out, from_cache=True, **base)
            except (KeyError, ValidationError) as exc:
                if mode == "replay":
                    return LLMResult[output_model](
                        status="error",
                        message=f"cached answer does not fit the schema: {exc}",
                        **base,
                    )
        if mode == "replay":
            return LLMResult[output_model](
                status="offline", message="AI offline: no recorded answer for this input", **base
            )

    if not os.environ.get("ANTHROPIC_API_KEY"):
        return LLMResult[output_model](
            status="offline", message="AI offline: no API key set", **base
        )
    try:
        out = _call_api(model, system, user_input, output_model, max_tokens)
    except Exception as exc:  # network, rate limit, refusal: the caller shows the badge
        return LLMResult[output_model](
            status="error", message=f"AI unavailable: {type(exc).__name__}", **base
        )
    if mode == "record":
        write_cache(task, key, make_entry(task, model, prompt_version, system, user_input, out))
    return LLMResult[output_model](status="ok", output=out, **base)

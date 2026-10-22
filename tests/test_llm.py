"""ds/interpreter/llm.py: cache key, replay behaviour, no network in replay."""

from __future__ import annotations

import hashlib
import sys

import pytest
from pydantic import BaseModel

from ds.interpreter import llm


class Out(BaseModel):
    label: str
    score: float


@pytest.fixture(autouse=True)
def _tmp_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("LLM_MODE", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture
def no_network(monkeypatch):
    """Fail if anything tries to import the SDK or call the API."""
    monkeypatch.setitem(sys.modules, "anthropic", None)  # `import anthropic` now raises

    def boom(*a, **k):
        raise AssertionError("network call attempted")

    monkeypatch.setattr(llm, "_call_api", boom)


def test_cache_key_is_sha256_of_model_version_input_and_stable():
    k = llm.cache_key("claude-sonnet-5-5", "v1", "hello")
    assert k == hashlib.sha256(b"claude-sonnet-5-5\nv1\nhello").hexdigest()
    assert k == llm.cache_key("claude-sonnet-5-5", "v1", "hello")
    assert (
        len(
            {
                k,
                llm.cache_key("claude-haiku-5-5", "v1", "hello"),
                llm.cache_key("claude-sonnet-5-5", "v2", "hello"),
                llm.cache_key("claude-sonnet-5-5", "v1", "hello!"),
            }
        )
        == 4
    )


def test_default_mode_is_replay():
    assert llm.llm_mode() == "replay"


def test_replay_hit_returns_parsed_model(no_network):
    key = llm.cache_key("m1", "v1", "input text")
    entry = llm.make_entry("t", "m1", "v1", "system", "input text", Out(label="enquiry", score=0.9))
    llm.write_cache("t", key, entry)
    res = llm.call_structured("t", "v1", "system", "input text", Out, model="m1")
    assert res.ok and res.from_cache
    assert isinstance(res.output, Out) and res.output.label == "enquiry"
    assert res.cache_key == key


def test_replay_miss_returns_offline_not_exception(no_network):
    res = llm.call_structured("t", "v1", "system", "never recorded", Out, model="m1")
    assert res.status == "offline" and res.output is None and not res.ok
    assert "offline" in (res.message or "").lower()


def test_replay_bad_cache_entry_is_error_not_crash(no_network):
    key = llm.cache_key("m1", "v1", "x")
    entry = llm.make_entry("t", "m1", "v1", "system", "x", Out(label="enquiry", score=0.1))
    del entry["output"]["score"]  # recorded under an older schema
    llm.write_cache("t", key, entry)
    res = llm.call_structured("t", "v1", "system", "x", Out, model="m1")
    assert res.status == "error"


def test_record_without_api_key_is_offline_and_writes_nothing(monkeypatch, no_network, tmp_path):
    monkeypatch.setenv("LLM_MODE", "record")
    res = llm.call_structured("t", "v1", "system", "y", Out, model="m1")
    assert res.status == "offline"
    assert not list((tmp_path / "cache").rglob("*.json"))


def test_model_resolution_uses_env_tiers(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_JUDGE", "judge-model")
    monkeypatch.setenv("LLM_MODEL_FAST", "fast-model")
    assert llm.resolve_model("dedup_judge") == "judge-model"
    assert llm.resolve_model("classify") == "fast-model"
    assert llm.resolve_model("classify", "explicit") == "explicit"


def test_cache_entry_never_contains_api_key(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_MODE", "record")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-secret")
    monkeypatch.setattr(llm, "_call_api", lambda *a, **k: Out(label="po", score=1.0))
    res = llm.call_structured("t", "v1", "system", "z", Out, model="m1")
    assert res.ok
    files = list((tmp_path / "cache").rglob("*.json"))
    assert len(files) == 1
    assert "sk-ant-test-secret" not in files[0].read_text(encoding="utf-8")


def test_replay_with_changed_system_prompt_is_offline_with_reason(no_network):
    key = llm.cache_key("m1", "v1", "q")
    llm.write_cache(
        "t", key, llm.make_entry("t", "m1", "v1", "old prompt", "q", Out(label="a", score=1))
    )
    res = llm.call_structured("t", "v1", "new prompt", "q", Out, model="m1")
    assert res.status == "offline" and res.output is None
    assert "bump prompt_version" in (res.message or "")
    # the key itself does not depend on the system prompt (rule 8)
    assert res.cache_key == key


def test_cache_entry_stores_system_prompt_hash():
    entry = llm.make_entry("t", "m1", "v1", "sys", "q", Out(label="a", score=1))
    assert entry["system_sha256"] == hashlib.sha256(b"sys").hexdigest()
    assert entry["cache_key"] == llm.cache_key("m1", "v1", "q")


@pytest.mark.parametrize("mode,writes", [("record", 1), ("live", 0)])
def test_record_writes_cache_live_does_not(monkeypatch, tmp_path, mode, writes):
    monkeypatch.setenv("LLM_MODE", mode)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    calls = []

    def fake(*a, **k):
        calls.append(a)
        return Out(label="po", score=1.0)

    monkeypatch.setattr(llm, "_call_api", fake)
    res = llm.call_structured("t", "v1", "system", "w", Out, model="m1")
    assert res.ok and not res.from_cache and len(calls) == 1
    assert len(list((tmp_path / "cache").rglob("*.json"))) == writes
    if mode == "record":  # the recorded answer now replays offline
        monkeypatch.setenv("LLM_MODE", "replay")
        again = llm.call_structured("t", "v1", "system", "w", Out, model="m1")
        assert again.ok and again.from_cache and len(calls) == 1


def test_api_client_has_timeout(monkeypatch):
    seen = {}

    class FakeResp:
        stop_reason = "end_turn"
        parsed_output = Out(label="x", score=0.5)

    class FakeClient:
        def __init__(self, **kw):
            seen.update(kw)
            self.messages = self

        def parse(self, **kw):
            seen["parse"] = kw
            return FakeResp()

    fake_mod = type(sys)("anthropic")
    fake_mod.Anthropic = FakeClient
    monkeypatch.setitem(sys.modules, "anthropic", fake_mod)
    monkeypatch.setenv("LLM_TIMEOUT_S", "20")
    out = llm._call_api("m1", "sys", "in", Out, 256)
    assert out.label == "x"
    assert seen["timeout"] == 20.0
    assert "temperature" not in seen["parse"]  # rejected by the current API; see module docstring

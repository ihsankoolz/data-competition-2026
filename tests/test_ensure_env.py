"""`make setup` writes .env with a FIELD_ENCRYPTION_KEY and never prints the key."""

import re

import pytest
from cryptography.fernet import Fernet

from services.api.crypto import KEY_ENV
from services.api.ensure_env import ensure_env, main

EXAMPLE = (
    "# Copy to .env. Never commit .env.\n"
    "LLM_MODE=replay              # replay (default, offline demo) | record | live\n"
    f"{KEY_ENV}=        # Fernet key: python -c ...\n"
    "API_PORT=8000\n"
)


@pytest.fixture
def paths(tmp_path):
    example = tmp_path / ".env.example"
    example.write_text(EXAMPLE, encoding="utf-8")
    return tmp_path / ".env", example


def key_in(env) -> str:
    m = re.search(rf"^{KEY_ENV}=(\S+)$", env.read_text(encoding="utf-8"), re.M)
    assert m, env.read_text(encoding="utf-8")
    Fernet(m.group(1))  # a valid Fernet key
    return m.group(1)


def test_missing_env_is_created_from_example_with_a_key(paths, capsys):
    env, example = paths
    assert main(["--env", str(env), "--example", str(example)]) == 0
    out = capsys.readouterr().out
    key = key_in(env)
    assert out.strip() == f"Created .env with a new {KEY_ENV}"
    assert key not in out
    text = env.read_text(encoding="utf-8")
    assert "LLM_MODE=replay" in text and "API_PORT=8000" in text
    assert b"\r\n" not in env.read_bytes()  # make reads LF


def test_blank_key_is_filled_and_other_lines_kept(paths, capsys):
    env, example = paths
    env.write_text(EXAMPLE.replace("API_PORT=8000", "API_PORT=9000"), encoding="utf-8")
    main(["--env", str(env), "--example", str(example)])
    out = capsys.readouterr().out
    key = key_in(env)
    assert out.strip() == f"Filled {KEY_ENV}"
    assert key not in out
    assert "API_PORT=9000" in env.read_text(encoding="utf-8")


def test_missing_key_line_is_appended(paths):
    env, example = paths
    env.write_text("LLM_MODE=replay\n", encoding="utf-8")
    assert ensure_env(env, example) == f"Filled {KEY_ENV}"
    key_in(env)


def test_existing_key_is_left_alone(paths, capsys):
    env, example = paths
    key = Fernet.generate_key().decode()
    before = f"LLM_MODE=replay\n{KEY_ENV}={key}\n"
    env.write_text(before, encoding="utf-8")
    main(["--env", str(env), "--example", str(example)])
    out = capsys.readouterr().out
    assert out.strip() == "Left .env alone"
    assert key not in out
    assert env.read_text(encoding="utf-8") == before

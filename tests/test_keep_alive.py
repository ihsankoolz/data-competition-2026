"""Regression for the intermittent 500 on GET /api/clock during Reset demo (D-025).

The Next proxy (Node's keep-alive agent) and httpx drop idle sockets after 5 s, and uvicorn's
default keep-alive is also 5 s. With equal timeouts the proxy can reuse a socket uvicorn is just
closing, and the browser gets a 500 "socket hang up". Every uvicorn launch therefore keeps idle
connections open longer than the clients do, so the client always closes first.
"""

from __future__ import annotations

import http.client
import re
import socket
import subprocess
import sys
import time

import pytest

from services.api.db.session import REPO_ROOT

CLIENT_IDLE_POOL_S = 5  # Node's http agent and httpx both drop idle sockets after 5 s
LAUNCHERS = {
    "Makefile": REPO_ROOT / "Makefile",
    "e2e API": REPO_ROOT / "apps" / "web" / "e2e" / "start-api.mjs",
    "e2e SAP mock": REPO_ROOT / "apps" / "web" / "playwright.config.ts",
}


def _keep_alive_values(text: str) -> list[int]:
    values = re.findall(r'--timeout-keep-alive["\s,]+"?(\$\(UVICORN_KEEP_ALIVE\)|\d+)', text)
    default = re.search(r"^UVICORN_KEEP_ALIVE \?= (\d+)$", text, re.M)
    return [int(default.group(1)) if v.startswith("$") and default else int(v) for v in values]


@pytest.mark.parametrize("name", LAUNCHERS)
def test_every_uvicorn_launch_outlives_the_clients_idle_pool(name: str) -> None:
    text = LAUNCHERS[name].read_text(encoding="utf-8")
    launches = len(re.findall(r'\buvicorn[\s",]+services\.\w+\.main:app', text))
    values = _keep_alive_values(text)
    assert launches >= 1
    assert len(values) == launches, f"{name}: a uvicorn launch has no --timeout-keep-alive"
    assert all(v > 2 * CLIENT_IDLE_POOL_S for v in values), values


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_a_connection_idle_past_the_client_pool_is_still_served() -> None:
    """Live: the same socket, idle a little longer than the clients' 5 s pool, still answers."""
    keep_alive = _keep_alive_values(LAUNCHERS["Makefile"].read_text(encoding="utf-8"))[0]
    port = _free_port()
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "services.sap_mock.main:app", "--port", str(port)]
        + ["--timeout-keep-alive", str(keep_alive), "--log-level", "warning"],
        cwd=REPO_ROOT,
    )
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("GET", "/b1s/v2/health")
                first = conn.getresponse()
                first.read()
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.2)
        assert first.status == 200
        time.sleep(CLIENT_IDLE_POOL_S + 0.5)
        conn.request("GET", "/b1s/v2/health")  # same socket: no reconnect
        second = conn.getresponse()
        second.read()
        assert second.status == 200
        conn.close()
    finally:
        server.terminate()
        server.wait(timeout=10)

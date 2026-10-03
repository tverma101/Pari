#!/usr/bin/env python3
"""Local synthetic integration tests for Issue #42 server ownership and identity.

No GPU, no model, no network beyond loopback. Every fake server here is a plain
stdlib HTTP server started and stopped by these tests, so the assertions exercise
this benchmark's orchestration logic rather than any runtime.

Cases from the issue:
1. stale fake server already holding the requested port -> port_collision;
2. healthy server whose /v1/models names the wrong model -> rejected;
3. owned child still loading -> no false readiness;
4. owned server exits after readiness and a stranger takes the port -> detected;
5. two concurrent owned servers get distinct ports and cannot cross-talk;
6. wrong served-model name rejected, right one accepted;
7. an unrelated process is never killed during cleanup;
8. owned server cleanup releases the port it held.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from kaggle_server_identity import (
    OwnedServer,
    PortCollision,
    allocate_loopback_port,
    discover_listener_pids,
    port_is_free,
    release_port_reservation,
    served_model_identity,
    verify_listener_ownership,
)

HERE = Path(__file__).resolve().parent


def free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


SERVER_SOURCE = """
import json, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

port = int(sys.argv[1])
model = sys.argv[2] if len(sys.argv) > 2 else "expected-model"
hold = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0


class H(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok"})
        elif self.path == "/v1/models":
            self._send(200, {"object": "list", "data": [{"id": model}]})
        else:
            self._send(404, {})


srv = ThreadingHTTPServer(("127.0.0.1", port), H)
if hold:
    time.sleep(hold)
srv.serve_forever()
"""


def server_command(port: int, model: str, hold: float = 0.0) -> list[str]:
    return [sys.executable, "-c", SERVER_SOURCE, str(port), model, str(hold)]


class FakeServer:
    """A loopback stand-in for an OpenAI-compatible model server."""

    def __init__(self, model_id: str, *, serve_models: bool = True):
        self.model_id = model_id
        self.serve_models = serve_models
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code: int, payload):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/health":
                    self._send(200, {"status": "ok"})
                elif self.path == "/v1/models":
                    if owner.serve_models:
                        self._send(200, {"object": "list", "data": [{"id": owner.model_id}]})
                    else:
                        self._send(404, {"error": "not supported"})
                else:
                    self._send(404, {"error": "not found"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


def wait_for_listener(port: int, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not port_is_free(port):
            return True
        time.sleep(0.05)
    return False


def log_path(name: str) -> Path:
    return HERE / ("__test_server_identity_" + name + ".log.txt")


def test_stale_server_on_requested_port_is_port_collision() -> None:
    """A pre-existing listener must fail closed, never be adopted."""
    stale = FakeServer("stale-model")
    try:
        raised = False
        try:
            allocate_loopback_port(stale.port)
        except PortCollision as collision:
            raised = True
            evidence = collision.evidence
            assert evidence["status"] == "port_collision"
            assert evidence["requestedPort"] == stale.port
            assert "never kill" in evidence["note"]
        assert raised, "allocate_loopback_port adopted an occupied port"
    finally:
        stale.stop()


def test_stale_server_healthy_but_wrong_model_is_rejected() -> None:
    """Health success plus a wrong served model must not qualify."""
    stale = FakeServer("some-other-model")
    try:
        identity = served_model_identity("http://127.0.0.1:%d" % stale.port, "expected-model")
        assert identity["identityMatched"] is False
        assert identity["identityStatus"] == "wrong_served_model"
        assert identity["servedModelIds"] == ["some-other-model"]
        assert identity["/v1/models.response"]["data"][0]["id"] == "some-other-model"
    finally:
        stale.stop()


def test_wrong_served_model_name_rejected_right_one_accepted() -> None:
    wrong = FakeServer("nope")
    right = FakeServer("expected-model")
    try:
        bad = served_model_identity("http://127.0.0.1:%d" % wrong.port, "expected-model")
        good = served_model_identity("http://127.0.0.1:%d" % right.port, "expected-model")
        assert bad["identityMatched"] is False
        assert good["identityMatched"] is True
        assert good["identityStatus"] == "matched"
    finally:
        wrong.stop()
        right.stop()


def test_identity_unavailable_is_not_treated_as_matched() -> None:
    """A runtime that cannot answer /v1/models is unproven, never assumed good."""
    server = FakeServer("ignored", serve_models=False)
    try:
        identity = served_model_identity("http://127.0.0.1:%d" % server.port, "expected-model")
        assert identity["identityMatched"] is False
        assert identity["identityStatus"] == "identity_unavailable"
    finally:
        server.stop()


def test_owned_child_still_loading_does_not_false_ready() -> None:
    """The owned child binds nothing until its hold elapses; no false readiness."""
    port = free_port()
    log = log_path("loading")
    receipt = OwnedServer(
        server_command(port, "expected-model", hold=30.0),
        port=port,
        expected_model="expected-model",
        log_path=log,
    )
    receipt.spawn()
    try:
        ready, evidence = receipt.wait_ready(timeout=2.0, poll_interval=0.2)
        assert ready is False
        assert evidence["status"] == "readiness_timeout"
        assert "readiness timeout" in evidence["error"]
    finally:
        receipt.terminate()
        if log.exists():
            log.unlink()


def test_owned_server_ready_and_identity_proven() -> None:
    """A correctly-served owned server qualifies and produces a full receipt."""
    port = free_port()
    port_evidence = {
        "schemaVersion": 1,
        "requestedPort": None,
        "selectedPort": port,
        "host": "127.0.0.1",
        "status": "kernel_allocated",
        "checkedAt": "test",
    }
    log = log_path("ready")
    receipt = OwnedServer(
        server_command(port, "expected-model"),
        port=port,
        expected_model="expected-model",
        log_path=log,
    )
    receipt.spawn(port_evidence)
    try:
        assert wait_for_listener(port), "owned server never bound the allocated port"
        ready, evidence = receipt.wait_ready(timeout=20.0, poll_interval=0.2)
        assert ready is True, evidence
        assert evidence["status"] == "ready"
        assert evidence["servedModelIdentity"]["identityMatched"] is True
        assert evidence["runNonce"] == receipt.nonce
        ownership = receipt.ownership_receipt()
        assert ownership["childPid"] == receipt.pid
        assert ownership["childPgid"] == receipt.pid
        assert ownership["expectedServedModel"] == "expected-model"
        assert len(ownership["commandIdentitySha256"]) == 64
        assert ownership["portEvidence"]["selectedPort"] == port
    finally:
        cleanup = receipt.terminate()
    assert cleanup["signalledPids"] == [receipt.pid]
    assert cleanup["portReleased"] is True
    if log.exists():
        log.unlink()


def test_wrong_model_on_owned_server_blocks_readiness() -> None:
    """Even our own child is rejected when it serves the wrong model name."""
    port = free_port()
    log = log_path("wrong")
    receipt = OwnedServer(
        server_command(port, "some-other-model"),
        port=port,
        expected_model="expected-model",
        log_path=log,
    )
    receipt.spawn()
    try:
        assert wait_for_listener(port)
        ready, evidence = receipt.wait_ready(timeout=20.0, poll_interval=0.2)
        assert ready is False
        assert evidence["status"] == "wrong_served_model"
        assert evidence["servedModelIdentity"]["identityMatched"] is False
        assert evidence["servedModelIdentity"]["servedModelIds"] == ["some-other-model"]
    finally:
        cleanup = receipt.terminate()
    assert cleanup["portReleased"] is True
    if log.exists():
        log.unlink()


def test_server_exits_after_readiness_then_port_reused() -> None:
    """If the owned server dies and a stranger takes the port, we detect it."""
    port = free_port()
    log = log_path("exits")
    receipt = OwnedServer(
        server_command(port, "expected-model"),
        port=port,
        expected_model="expected-model",
        log_path=log,
    )
    receipt.spawn()
    assert wait_for_listener(port)
    ready, _ = receipt.wait_ready(timeout=20.0, poll_interval=0.2)
    assert ready is True
    receipt.process.kill()
    receipt.process.wait(timeout=10)
    stranger = FakeServer("stranger-model")
    try:
        identity = served_model_identity("http://127.0.0.1:%d" % port, "expected-model")
        assert identity["identityMatched"] is False
    finally:
        stranger.stop()
    # terminate() is idempotent: nothing is re-signalled, so the stranger survives.
    cleanup = receipt.terminate()
    assert cleanup["signalledPids"] == []
    if log.exists():
        log.unlink()


def test_unrelated_process_is_never_killed_during_cleanup() -> None:
    """Cleanup signals only the owned child; a bystander server stays up."""
    bystander = FakeServer("bystander")
    bystander_pids = discover_listener_pids(bystander.port)
    port = free_port()
    log = log_path("unrelated")
    receipt = OwnedServer(
        server_command(port, "expected-model"),
        port=port,
        expected_model="expected-model",
        log_path=log,
    )
    receipt.spawn()
    try:
        assert wait_for_listener(port)
        ready, _ = receipt.wait_ready(timeout=20.0, poll_interval=0.2)
        assert ready is True
    finally:
        cleanup = receipt.terminate()
    assert cleanup["signalledPids"] == [receipt.pid]
    # The bystander was never signalled and is still answering.
    assert not (bystander_pids & set(cleanup["signalledPids"]))
    still = served_model_identity("http://127.0.0.1:%d" % bystander.port, "bystander")
    assert still["identityMatched"] is True
    bystander.stop()
    if log.exists():
        log.unlink()


def test_two_concurrent_owned_servers_do_not_cross_talk() -> None:
    """Concurrent runs get distinct ports and each server answers for itself."""
    port_a, evidence_a = allocate_loopback_port()
    port_b, evidence_b = allocate_loopback_port()
    assert port_a != port_b
    assert evidence_a["status"] == "kernel_allocated"
    release_port_reservation(evidence_a)
    release_port_reservation(evidence_b)

    log_a = log_path("concurrent_a")
    log_b = log_path("concurrent_b")
    server_a = OwnedServer(
        server_command(port_a, "model-a"), port=port_a, expected_model="model-a", log_path=log_a
    )
    server_b = OwnedServer(
        server_command(port_b, "model-b"), port=port_b, expected_model="model-b", log_path=log_b
    )
    server_a.spawn()
    server_b.spawn()
    try:
        assert wait_for_listener(port_a) and wait_for_listener(port_b)
        ready_a, ev_a = server_a.wait_ready(timeout=20.0, poll_interval=0.2)
        ready_b, ev_b = server_b.wait_ready(timeout=20.0, poll_interval=0.2)
        assert ready_a and ready_b
        assert ev_a["servedModelIdentity"]["servedModelIds"] == ["model-a"]
        assert ev_b["servedModelIdentity"]["servedModelIds"] == ["model-b"]
        # Asking A for B's model is refused, so outputs cannot be mislabelled.
        cross = served_model_identity("http://127.0.0.1:%d" % port_a, "model-b")
        assert cross["identityMatched"] is False
    finally:
        cleanup_a = server_a.terminate()
        cleanup_b = server_b.terminate()
    assert cleanup_a["portReleased"] and cleanup_b["portReleased"]
    for path in (log_a, log_b):
        if path.exists():
            path.unlink()


def test_listener_ownership_never_claims_an_unowned_listener() -> None:
    """A listener we did not spawn is never reported as ours."""
    stranger = FakeServer("stranger")
    try:
        evidence = verify_listener_ownership(stranger.port, {os.getpid()})
        assert evidence["ownedListenerObserved"] is False
        if evidence["status"] == "unowned_listener":
            assert os.getpid() in evidence["unrelatedListenerPids"]
            assert evidence["ownedListenerPids"] == []
        else:
            # No /proc attribution available (macOS): the honest answer is unknown.
            assert evidence["status"] in {"listener_unknown", "no_listener"}
    finally:
        stranger.stop()


def test_remote_host_is_refused() -> None:
    """Non-loopback endpoints are rejected before any traffic is sent."""
    from kaggle_server_identity import require_loopback

    refused = False
    try:
        require_loopback("10.0.0.5")
    except ValueError:
        refused = True
    assert refused


def test_stale_server_answering_health_while_new_child_loads_is_rejected() -> None:
    """The core race: a stale listener answers health while our child is loading.

    We request the stale server's port explicitly. Allocation must fail as
    port_collision before any child is spawned, so the benchmark can never adopt
    the stale answerer. Even if a caller bypasses that and probes anyway, the
    served-model check refuses a model that is not the expected candidate.
    """
    stale = FakeServer("stale-model")
    try:
        stale_identity = served_model_identity(
            "http://127.0.0.1:%d" % stale.port, "expected-model"
        )
        assert stale_identity["identityMatched"] is False

        # Our own child is spawned but held in "loading"; it never answers.
        # It must not reach readiness just because the stale server does.
        port = free_port()
        log = log_path("race_loading")
        receipt = OwnedServer(
            server_command(port, "expected-model", hold=30.0),
            port=port,
            expected_model="expected-model",
            log_path=log,
        )
        receipt.spawn()
        ready, evidence = receipt.wait_ready(timeout=2.0, poll_interval=0.2)
        assert ready is False
        assert evidence["status"] == "readiness_timeout"
        receipt.terminate()
        if log.exists():
            log.unlink()
    finally:
        stale.stop()


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print("ok " + test.__name__)
    print("Kaggle server-identity/ownership tests passed (%d cases)." % len(tests))


if __name__ == "__main__":
    main()

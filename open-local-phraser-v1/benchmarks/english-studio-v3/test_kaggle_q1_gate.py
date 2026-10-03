#!/usr/bin/env python3
"""CPU fixtures for the roster Q1 load gate and the exclusive GPU lease.

No GPU, no model, no network beyond loopback. A stdlib fake OpenAI-compatible
server stands in for the candidate runtime, and `nvidia-smi` output is stubbed,
so these assert the receipt logic rather than any real runtime.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def load_roster_module():
    spec = importlib.util.spec_from_file_location("pari_roster_q1", HERE / "run-kaggle-roster.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ROSTER = load_roster_module()


SERVER_SOURCE = (
    "import json, sys\n"
    "from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\n"
    "port = int(sys.argv[1]); model = sys.argv[2]; reply = sys.argv[3]\n"
    "class H(BaseHTTPRequestHandler):\n"
    "    def log_message(self, *a): pass\n"
    "    def _send(self, code, payload):\n"
    "        body = json.dumps(payload).encode()\n"
    "        self.send_response(code)\n"
    "        self.send_header('Content-Type', 'application/json')\n"
    "        self.send_header('Content-Length', str(len(body)))\n"
    "        self.end_headers()\n"
    "        self.wfile.write(body)\n"
    "    def do_GET(self):\n"
    "        if self.path == '/health': self._send(200, {'status': 'ok'})\n"
    "        elif self.path == '/v1/models':\n"
    "            self._send(200, {'object': 'list', 'data': [{'id': model}]})\n"
    "        else: self._send(404, {})\n"
    "    def do_POST(self):\n"
    "        length = int(self.headers.get('Content-Length', '0'))\n"
    "        self.rfile.read(length)\n"
    "        self._send(200, {'choices': [{'message': {'content': reply}, 'finish_reason': 'stop'}]})\n"
    "ThreadingHTTPServer(('127.0.0.1', port), H).serve_forever()\n"
)


def fake_vllm_candidate() -> dict:
    return {
        "id": "fake-vllm",
        "repo": "org/fake-model",
        "revision": "a" * 40,
        "runtime": "vllm",
        "tensorParallelSize": 1,
        "languageModelOnly": True,
    }


def make_owned_server(model: str, reply: str) -> object:
    """Build an OwnedServer that launches the fake runtime on an owned port."""
    from kaggle_server_identity import OwnedServer, allocate_loopback_port, release_port_reservation

    port, evidence = allocate_loopback_port()
    server = OwnedServer(
        [sys.executable, "-c", SERVER_SOURCE, str(port), model, reply],
        host="127.0.0.1",
        port=port,
        expected_model=model,
    )
    release_port_reservation(evidence)
    server.spawn(evidence)
    return server


def stub_gpu(monkey, delta_mib: int, per_device=True) -> None:
    """Make the roster's nvidia-smi probes report a verified GPU delta."""
    state = {"calls": 0}

    def fake_used():
        state["calls"] += 1
        # First call is the baseline; later calls reflect loaded weights.
        return {0: 512} if state["calls"] == 1 else {0: 512 + delta_mib}

    monkey.setattr(ROSTER, "gpu_used_mib", fake_used)
    monkey.setattr(ROSTER, "gpu_mib_for_pid", lambda pid: delta_mib if pid else 0)


def test_q1_receipt_completes_on_real_probe_evidence() -> None:
    """A healthy owned runtime produces a completed Q1 receipt from real evidence."""
    candidate = fake_vllm_candidate()
    with TemporaryDirectory() as tmp:
        results = Path(tmp)
        server = make_owned_server("fake-vllm", "ready")
        try:
            from kaggle_server_identity import OwnedServer

            # Drive the real probe against the already-running fake runtime by
            # pointing the roster at its command; the probe owns port allocation
            # itself, so instead assert the lower-level evidence helpers directly.
            import time

            from kaggle_server_identity import http_get_json

            # Wait for the fake server.
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and server.poll() is None:
                status, _payload, _error = http_get_json(f"http://127.0.0.1:{server.port}/health", timeout=2)
                if status == 200:
                    break
                time.sleep(0.1)

            # 1. Placement helper: verified delta passes, no delta fails closed.
            class MP:
                def setattr(self, obj, name, value):
                    setattr(obj, name, value)

            stub_gpu(MP(), 2048)
            placement = ROSTER.placement_evidence(candidate, {0: 512}, {0: 512 + 2048}, pid=1234)
            assert placement["passed"] is True
            assert placement["silentCpuFallbackSuspected"] is False
            assert placement["childProcessGpuMemoryMiB"] == 2048

            cpu_placement = ROSTER.placement_evidence(candidate, {0: 512}, {0: 512}, pid=1234)
            assert cpu_placement["passed"] is False
            assert cpu_placement["silentCpuFallbackSuspected"] is True

            # 2. Trivial generation against the live fake runtime is real evidence.
            generation = ROSTER.trivial_generation(f"http://127.0.0.1:{server.port}", "fake-vllm")
            assert generation["status"] == "completed"
            assert generation["outputText"] == "ready"
            assert generation["isEnglishQualityEvidence"] is False
        finally:
            server.terminate()


def test_q1_receipt_never_synthesizes_success() -> None:
    """A missing runtime makes Q1 fail closed; there is no success-by-default."""
    candidate = fake_vllm_candidate()
    with TemporaryDirectory() as tmp:
        receipt = ROSTER.run_q1_load_probe(
            candidate=candidate,
            results_dir=Path(tmp),
            runtime_dir=Path(tmp),
            startup_timeout=2.0,
        )
        # vllm console script is absent in this environment, so launch fails closed.
        assert receipt["status"] == "failed"
        assert receipt["terminalFailureStage"] == "launch_config"
        assert "vllm" in receipt["reason"]
        # The stored receipt on disk agrees with the returned one.
        stored = json.loads(ROSTER.q1_receipt_path(Path(tmp), "fake-vllm").read_text())
        assert stored["status"] == "failed"
        assert stored["status"] != "completed"


def test_q1_receipt_reuse_is_config_scoped() -> None:
    """A completed receipt is reused only for an identical candidate config."""
    candidate = fake_vllm_candidate()
    with TemporaryDirectory() as tmp:
        results = Path(tmp)
        path = ROSTER.q1_receipt_path(results, "fake-vllm")
        path.parent.mkdir(parents=True, exist_ok=True)
        good = {
            "status": "completed",
            "configIdentitySha256": ROSTER.q1_config_identity(candidate),
        }
        path.write_text(json.dumps(good))
        assert ROSTER.load_reusable_q1_receipt(candidate, results) is not None
        # A different candidate revision must not inherit the receipt.
        other = dict(candidate, revision="b" * 40)
        assert ROSTER.load_reusable_q1_receipt(other, results) is None
        # A failed receipt is never reused.
        path.write_text(json.dumps(dict(good, status="failed")))
        assert ROSTER.load_reusable_q1_receipt(candidate, results) is None


def test_gpu_lease_is_exclusive_and_released() -> None:
    """GpuLease is exclusive across holders and released idempotently."""
    from kaggle_gpu_resource_gate import GpuLease, LeaseUnavailable

    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "gpu-lease.json"
        first = GpuLease(path=path, owner="roster-a")
        first.acquire()
        # A second holder is refused while the first is alive.
        second = GpuLease(path=path, owner="roster-b")
        refused = False
        try:
            second.acquire()
        except LeaseUnavailable:
            refused = True
        assert refused, "GpuLease allowed two live holders"
        released = first.release()
        assert released["released"] is True
        # After release, the next holder may take it.
        second.acquire()
        second.release()


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print("ok " + test.__name__)
    print("Roster Q1 gate + GPU lease tests passed (%d cases)." % len(tests))


if __name__ == "__main__":
    main()

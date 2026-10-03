#!/usr/bin/env python3
"""Loopback server ownership, port and served-model identity proof for Kaggle runs.

Issue #42: a successful `/health` response is not evidence that the answering
process is the server this benchmark just launched, nor that it serves the
intended candidate. This module makes server-backed benchmark traffic fail
closed:

- ports are allocated or verified free before spawn, and a pre-existing listener
  raises `port_collision` instead of being talked to;
- the launched process, its process group, command, start time, log paths and a
  run nonce are recorded in an ownership receipt;
- where the OS exposes it, the listening PID is compared against the owned
  process tree, so an unrelated listener cannot masquerade as readiness;
- OpenAI-compatible servers additionally have to answer `/v1/models` with the
  expected served-model name, and the raw response is preserved in the receipt.

Cleanup only ever signals the `Popen` handle this module created. Nothing here
searches by port or by name and kills what it finds, so an unrelated process is
never terminated to recover a port.

Standard library only, so it imports on Kaggle before any ML dependency exists.
"""
from __future__ import annotations

import hashlib
import json
import os
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
IDENTITY_PATHS = ("/v1/models",)
LISTEN_STATE = "0A"


class PortCollision(RuntimeError):
    """A pre-existing listener occupies the requested loopback port."""

    def __init__(self, message: str, evidence: dict[str, Any]):
        super().__init__(message)
        self.evidence = evidence


class ServerIdentityError(RuntimeError):
    """The answering server failed ownership or served-model identity proof."""

    def __init__(self, message: str, evidence: dict[str, Any], category: str):
        super().__init__(message)
        self.evidence = evidence
        self.category = category


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def require_loopback(host: str) -> str:
    if host not in LOOPBACK_HOSTS:
        raise ValueError(f"host must be loopback, refusing remote endpoint {host!r}")
    return host


# ---------------------------------------------------------------------------
# Port ownership


def _bind_free_port(host: str) -> tuple[int, socket.socket]:
    sock = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, 0))
    return int(sock.getsockname()[1]), sock


def port_is_free(port: int, host: str = "127.0.0.1") -> bool:
    """True when nothing is currently listening on the loopback port."""
    try:
        probe = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return False
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind((host, port))
    except OSError:
        return False
    finally:
        probe.close()
    return True


def allocate_loopback_port(preferred: int | None = None, host: str = "127.0.0.1") -> tuple[int, dict[str, Any]]:
    """Reserve a loopback port for a child this caller is about to spawn.

    `preferred` is honoured only when it is actually free; an occupied port is a
    hard `port_collision` rather than a silent reuse of whatever is listening.
    Without a preference the kernel hands out a free port, which the caller keeps
    bound until the real server is spawned so two concurrent runs cannot be
    handed the same number.
    """
    host = require_loopback(host)
    if preferred is not None:
        if not port_is_free(preferred, host):
            raise PortCollision(
                f"loopback port {preferred} is already in use",
                {
                    "schemaVersion": SCHEMA_VERSION,
                    "requestedPort": preferred,
                    "host": host,
                    "status": "port_collision",
                    "listenerPids": sorted(discover_listener_pids(preferred, host)),
                    "checkedAt": utc_now(),
                    "note": "a pre-existing listener owns this port; never talk to it and never kill it",
                },
            )
        return preferred, {
            "schemaVersion": SCHEMA_VERSION,
            "requestedPort": preferred,
            "selectedPort": preferred,
            "host": host,
            "status": "verified_free",
            "checkedAt": utc_now(),
        }

    selected, sock = _bind_free_port(host)
    return selected, {
        "schemaVersion": SCHEMA_VERSION,
        "requestedPort": None,
        "selectedPort": selected,
        "host": host,
        "status": "kernel_allocated",
        "checkedAt": utc_now(),
        # Caller must close the reservation via `release_port_reservation`.
        "_reservation": sock,
    }


def release_port_reservation(evidence: dict[str, Any]) -> None:
    sock = evidence.pop("_reservation", None)
    if sock is not None:
        try:
            sock.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Listener / process ownership (best effort, Linux /proc)


def _proc_available() -> bool:
    return Path("/proc/self/stat").exists()


def _listening_inodes(port: int) -> set[str]:
    inodes: set[str] = set()
    for name in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            lines = Path(name).read_text(encoding="utf-8").splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 10 or fields[3] != LISTEN_STATE:
                continue
            try:
                local_port = int(fields[1].rsplit(":", 1)[1], 16)
            except (IndexError, ValueError):
                continue
            if local_port == port:
                inodes.add(fields[9])
    return inodes


def discover_listener_pids(port: int, host: str = "127.0.0.1") -> set[int]:
    """PIDs holding a listening socket on `port`, from /proc. Empty if unknown."""
    del host  # loopback only; every /proc listener table row is inspected
    inodes = _listening_inodes(port)
    if not inodes:
        return set()
    wanted = {f"socket:[{inode}]" for inode in inodes}
    pids: set[int] = set()
    proc_root = Path("/proc")
    try:
        entries = [entry for entry in proc_root.iterdir() if entry.name.isdigit()]
    except OSError:
        return set()
    for entry in entries:
        try:
            handles = list((entry / "fd").iterdir())
        except OSError:
            continue
        for handle in handles:
            try:
                if os.readlink(handle) in wanted:
                    pids.add(int(entry.name))
                    break
            except OSError:
                continue
    return pids


def process_children(pid: int) -> set[int]:
    children: set[int] = set()
    proc_root = Path("/proc")
    try:
        entries = [entry for entry in proc_root.iterdir() if entry.name.isdigit()]
    except OSError:
        return children
    for entry in entries:
        try:
            stat = (entry / "stat").read_text(encoding="utf-8", errors="replace")
            parent_pid = int(stat.rsplit(")", 1)[1].split()[1])
        except (OSError, IndexError, ValueError):
            continue
        if parent_pid == pid:
            children.add(int(entry.name))
    return children


def owned_process_tree(pid: int) -> set[int]:
    """The launched PID plus its descendants, for listener ownership comparison."""
    tree = {pid}
    frontier = [pid]
    while frontier:
        parent = frontier.pop()
        for child in process_children(parent):
            if child not in tree:
                tree.add(child)
                frontier.append(child)
    return tree


def verify_listener_ownership(
    port: int, owned_pids: set[int], host: str = "127.0.0.1"
) -> dict[str, Any]:
    """Compare the listening PIDs on `port` with the process tree we launched.

    `status` is one of `owned`, `unowned_listener`, `listener_unknown` or
    `no_listener`. Only `owned` proves the answerer is the process this run
    spawned; `unowned_listener` is a hard failure.
    """
    listeners = set(discover_listener_pids(port, host))
    evidence: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "port": port,
        "host": host,
        "ownedPids": sorted(owned_pids),
        "listenerPids": sorted(listeners),
        "attributionSupported": _proc_available(),
        "checkedAt": utc_now(),
    }
    if not listeners:
        # /proc exposes no attribution path here; the caller decides whether
        # ownership proof is mandatory for this runtime.
        evidence["status"] = "listener_unknown" if _proc_available() else "no_listener"
        evidence["ownedListenerObserved"] = False
        return evidence
    owned_listeners = sorted(listeners & set(owned_pids))
    evidence["ownedListenerPids"] = owned_listeners
    evidence["unrelatedListenerPids"] = sorted(listeners - set(owned_pids))
    evidence["ownedListenerObserved"] = bool(owned_listeners)
    evidence["status"] = "owned" if owned_listeners else "unowned_listener"
    return evidence


# ---------------------------------------------------------------------------
# HTTP identity probes (loopback only)


def http_get_json(
    url: str, timeout: float = 5.0, headers: dict[str, str] | None = None
) -> tuple[int | None, Any, str | None]:
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code), None, f"HTTP {exc.code}"
    except Exception as exc:  # URLError, socket errors, timeouts
        return None, None, f"{type(exc).__name__}: {exc}"
    try:
        return status, json.loads(body), None
    except json.JSONDecodeError as exc:
        return status, None, f"invalid JSON: {exc}"


def served_model_identity(
    endpoint: str,
    expected_model: str | None,
    timeout: float = 5.0,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Read `/v1/models` and check the expected served-model name is present."""
    base = endpoint.rstrip("/")
    evidence: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "endpoint": base,
        "identityPathsTried": list(IDENTITY_PATHS),
        "expectedModel": expected_model,
        "checkedAt": utc_now(),
    }
    for path in IDENTITY_PATHS:
        status, payload, error = http_get_json(base + path, timeout=timeout, headers=headers)
        evidence[f"{path}.status"] = status
        if payload is None:
            evidence[f"{path}.error"] = error
            continue
        evidence[f"{path}.response"] = payload
        model_ids = [
            str(entry["id"])
            for entry in (payload.get("data") or [])
            if isinstance(entry, dict) and entry.get("id")
        ]
        evidence["servedModelIds"] = model_ids
        if expected_model is None:
            evidence["identityMatched"] = None
            evidence["identityStatus"] = "not_requested"
        else:
            matched = expected_model in model_ids
            evidence["identityMatched"] = matched
            evidence["identityStatus"] = "matched" if matched else "wrong_served_model"
        evidence["status"] = "ok"
        return evidence
    evidence["servedModelIds"] = []
    evidence["identityMatched"] = False
    evidence["identityStatus"] = "identity_unavailable"
    evidence["status"] = "failed"
    return evidence


# ---------------------------------------------------------------------------
# Owned server lifecycle


def command_identity(command: list[str]) -> str:
    """Stable identity for a launch command, recorded in the receipt."""
    payload = json.dumps(list(command), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class OwnedServer:
    """A server process this benchmark owns, with a receipt for every claim."""

    def __init__(
        self,
        command: list[str],
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        expected_model: str | None = None,
        log_path: Path | None = None,
        env: dict[str, str] | None = None,
        nonce: str | None = None,
    ) -> None:
        self.host = require_loopback(host)
        self.command = list(command)
        self.port = port
        self.expected_model = expected_model
        self.log_path = Path(log_path) if log_path else None
        self.env = env
        self.nonce = nonce or uuid.uuid4().hex
        self.process: subprocess.Popen | None = None
        self.log_handle = None
        self.started_at = utc_now()
        self.started_monotonic = time.monotonic()
        self.port_evidence: dict[str, Any] = {}

    def spawn(self, port_evidence: dict[str, Any] | None = None) -> subprocess.Popen:
        if self.process is not None:
            raise RuntimeError("this OwnedServer was already spawned")
        if self.port <= 0:
            raise ValueError("OwnedServer requires a pre-allocated port")
        self.port_evidence = {
            key: value
            for key, value in dict(port_evidence or {}).items()
            if not key.startswith("_")
        }
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self.log_handle = self.log_path.open("w", encoding="utf-8")
        kwargs: dict[str, Any] = {"text": True, "start_new_session": True}
        if self.log_handle is not None:
            kwargs["stdout"] = self.log_handle
            kwargs["stderr"] = subprocess.STDOUT
        else:
            kwargs["stdout"] = subprocess.PIPE
            kwargs["stderr"] = subprocess.STDOUT
        if self.env is not None:
            kwargs["env"] = self.env
        self.process = subprocess.Popen(self.command, **kwargs)
        return self.process

    @property
    def pid(self) -> int | None:
        return self.process.pid if self.process is not None else None

    def ownership_receipt(self) -> dict[str, Any]:
        pid = self.pid
        pgid = None
        if pid is not None:
            try:
                pgid = os.getpgid(pid)
            except OSError:
                pgid = None
        return {
            "schemaVersion": SCHEMA_VERSION,
            "runNonce": self.nonce,
            "host": self.host,
            "port": self.port,
            "endpoint": f"http://{self.host}:{self.port}",
            "childPid": pid,
            "childPgid": pgid,
            "ownProcessGroup": True,
            "command": list(self.command),
            "commandIdentitySha256": command_identity(self.command),
            "expectedServedModel": self.expected_model,
            "startedAt": self.started_at,
            "startMonotonicSeconds": self.started_monotonic,
            "logPath": str(self.log_path) if self.log_path else None,
            "portEvidence": self.port_evidence,
            "recordedAt": utc_now(),
        }

    def poll(self) -> int | None:
        return self.process.poll() if self.process is not None else None

    def wait_ready(
        self,
        timeout: float,
        *,
        require_identity: bool = True,
        require_ownership: bool = False,
        poll_interval: float = 0.5,
    ) -> tuple[bool, dict[str, Any]]:
        """Poll until health *and* identity (and optionally ownership) both hold.

        Health alone never qualifies a server. A healthy server that fails
        ownership or served-model identity is rejected as `unowned_listener` /
        `wrong_served_model` / `server_exited`: runtime failures, never
        English-quality signal.
        """
        deadline = time.monotonic() + timeout
        evidence: dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "endpoint": f"http://{self.host}:{self.port}",
            "expectedModel": self.expected_model,
            "requireIdentity": require_identity,
            "requireOwnership": require_ownership,
            "runNonce": self.nonce,
            "attempts": 0,
        }
        last_error = ""
        while time.monotonic() < deadline:
            evidence["attempts"] += 1
            rc = self.poll()
            if rc is not None:
                evidence["status"] = "server_exited"
                evidence["returnCode"] = rc
                evidence["error"] = "owned server exited before readiness"
                return False, evidence

            health_status, _payload, health_error = http_get_json(
                f"http://{self.host}:{self.port}/health", timeout=5.0
            )
            evidence["healthStatus"] = health_status
            if health_status is None or not 200 <= health_status < 300:
                last_error = health_error or f"HTTP {health_status}"
                time.sleep(poll_interval)
                continue

            identity = served_model_identity(
                f"http://{self.host}:{self.port}", self.expected_model
            )
            evidence["servedModelIdentity"] = identity
            if require_identity and identity.get("identityMatched") is not True:
                evidence["status"] = identity.get("identityStatus") or "identity_unavailable"
                evidence["error"] = (
                    f"served-model identity not proven: expected={self.expected_model!r} "
                    f"served={identity.get('servedModelIds')}"
                )
                return False, evidence

            owned_pids = owned_process_tree(self.pid) if self.pid is not None else set()
            ownership = verify_listener_ownership(self.port, owned_pids, self.host)
            evidence["listenerOwnership"] = ownership
            if ownership["status"] == "unowned_listener":
                evidence["status"] = "unowned_listener"
                evidence["error"] = (
                    f"loopback port {self.port} is held by an unrelated process "
                    f"{ownership['listenerPids']}"
                )
                return False, evidence
            if require_ownership and ownership["status"] != "owned":
                evidence["status"] = ownership["status"]
                evidence["error"] = "could not prove the listener belongs to the owned process"
                return False, evidence

            evidence["status"] = "ready"
            evidence["readyAt"] = utc_now()
            return True, evidence

        evidence["status"] = "readiness_timeout"
        evidence["error"] = f"readiness timeout: {last_error}"
        return False, evidence

    def terminate(self, grace_seconds: float = 30.0) -> dict[str, Any]:
        """Stop only the process this object spawned, then close its log handle."""
        evidence: dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "signalledPids": [],
            "policy": "only the Popen handle created by this object is signalled",
            "stoppedAt": utc_now(),
        }
        proc = self.process
        if proc is not None:
            if proc.poll() is None:
                pid = proc.pid
                try:
                    child_pgid = os.getpgid(pid)
                except OSError:
                    child_pgid = None
                try:
                    if child_pgid is not None and child_pgid != os.getpgid(0):
                        # Signal the child's own group only, never our own group.
                        os.killpg(child_pgid, signal.SIGTERM)
                    else:
                        proc.terminate()
                    evidence["signalledPids"].append(pid)
                    evidence["signal"] = "SIGTERM"
                except OSError as exc:
                    evidence["signalError"] = f"{type(exc).__name__}: {exc}"
                try:
                    proc.wait(timeout=grace_seconds)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    evidence["signalledPids"].append(pid)
                    evidence["signal"] = "SIGKILL"
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        evidence["killTimeout"] = True
            evidence["returnCode"] = proc.poll()
            evidence["pid"] = proc.pid
        if self.log_handle is not None:
            try:
                self.log_handle.close()
            except OSError:
                pass
            self.log_handle = None
        evidence["portReleased"] = port_is_free(self.port, self.host)
        evidence["stopped"] = evidence.get("returnCode") is not None
        return evidence

    def __enter__(self) -> "OwnedServer":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.terminate()

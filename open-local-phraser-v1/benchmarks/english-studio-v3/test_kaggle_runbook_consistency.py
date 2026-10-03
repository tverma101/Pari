#!/usr/bin/env python3
"""Issue #59: runbook, CLI stage model, and mandatory self-checks must agree.

`KAGGLE_AGENT_EXECUTION.md` tells execution agents to follow it literally and not
improvise, which makes stale runbook prose an executable correctness bug. This
module is the mechanical check for that claim: it reads
`kaggle-runbook-contract.json` (the machine-readable authority), compares it to
the runbook prose, to the CLI stage model, to the pinned runtime registry, and
to the mandatory self-check, and fails closed on any disagreement.

All checks are CPU-only: no GPU, no model, no network, no Kaggle.

Run directly (matching the other benchmark tests) or under pytest:
    python3 test_kaggle_runbook_consistency.py
"""
from __future__ import annotations

import ast
import importlib.util
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE / "kaggle-runbook-contract.json"

# A registered contract is invoked through an explicit interpreter so the gate
# says unambiguously which file ran. Both lanes need one: the #44 allowed-choice
# contract has a Python half and a Node half, and only the second needs `node`.
INTERPRETERS = ("python3 ", "node ")

# What a self-check gate looks like when it runs a test: an interpreter followed
# by a module path, and the module named like a test. Inline `python3 -c` and
# heredoc snippets do not match, and non-test tools a gate runs deliberately
# (the validator, the shadow audit) are out of scope: this check is about tests,
# not about every file a gate happens to execute.
INVOCATION_RE = re.compile(
    r"(?m)^[ \t]*(?:python3|node)[ \t]+(?P<target>[\w./-]*test[\w./-]*\.(?:py|mjs))(?:[ \t]|$)"
)

# Third-party HTTP clients a contract module must not *call*. Importing one to
# detect availability is allowed, and in fact one registered suite imports
# `requests` precisely so it can substitute a stub that raises on any use. A
# stdlib loopback fixture (http.server standing in for a candidate runtime) is
# fine too; it never leaves the machine.
NETWORK_MODULES = ("requests", "httpx", "aiohttp", "urllib.request", "urllib3", "huggingface_hub")
NETWORK_CALLS = ("get", "post", "put", "patch", "delete", "head", "request", "send")


class ContractError(AssertionError):
    """One runbook/contract inconsistency, collected so a run reports them all."""


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_tuple_constant(path: Path, name: str) -> tuple[int, ...]:
    """Read a frozen tuple constant without executing the module.

    Static reading matters here: the runners import sibling helpers and are not
    safe to execute from a temporary fixture directory, and the point of the
    ladder check is to compare declared constants, not to run a launcher.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        targets = getattr(node, "targets", []) or []
        if not any(isinstance(target, ast.Name) and target.id == name for target in targets):
            continue
        value = node.value
        if not isinstance(value, (ast.Tuple, ast.List)):
            break
        values = []
        for item in value.elts:
            if not isinstance(item, ast.Constant) or not isinstance(item.value, int):
                raise ContractError(f"{path.name}: {name} must be a literal tuple of integers")
            values.append(int(item.value))
        return tuple(values)
    raise ContractError(f"cannot find {name} in {path.name}")


def canonical_commands(runbook_text: str) -> list[str]:
    """Extract the fenced bash blocks the runbook tells an agent to execute."""
    return [block for block in re.findall(r"```bash\n(.*?)```", runbook_text, flags=re.S) if block.strip()]


def bash_tokens(block: str) -> list[str]:
    """Flat token list for a bash block, with line continuations joined."""
    joined = block.replace("\\\n", " ")
    return re.findall(r"[^\s'\"\\]+", joined)


def check_contract_shape(contract: dict, here: Path) -> None:
    assert contract.get("contractVersion") == 1, "runbook contract version must be 1"
    for key in ("sources", "phaseSequence", "stageApplicability", "mandatoryContracts"):
        assert contract.get(key), f"runbook contract is missing {key}"
    for name, value in contract["sources"].items():
        assert (here / value).is_file(), f"contract source {name}={value} does not exist"
    gates = contract.get("selfCheckGates") or {}
    scripts = [name for name in gates.values() if isinstance(name, str) and name.endswith(".sh")]
    assert len(scripts) == len(set(scripts)), f"a self-check script is declared by two gates: {gates}"
    for name in scripts:
        assert (here / name).is_file(), f"self-check gate {name} does not exist"
    declared_gates = {entry.get("gate") for entry in contract["mandatoryContracts"]}
    assert declared_gates <= set(gates), (
        f"mandatory contracts name gates the contract does not define: {sorted(declared_gates - set(gates))}"
    )
    # A contract may pin the implementation it enforces (for example the strict
    # result schema and its validator). Those paths must exist, so a renamed
    # schema or validator cannot silently detach from its gate.
    for entry in contract["mandatoryContracts"]:
        for key in ("validator", "schema"):
            value = entry.get(key)
            if value:
                assert (here / value).is_file(), (
                    f"contract {entry['id']} declares {key}={value}, which does not exist"
                )
        # A contract may name the producers it validates. Those files must exist,
        # and the contract module must actually reference each one, so a producer
        # cannot be renamed out from under its evidence gate.
        for producer in entry.get("producers") or []:
            assert (here / producer).is_file(), (
                f"contract {entry['id']} declares producer {producer}, which does not exist"
            )
            if entry["modules"]:
                module_text = "\n".join(
                    (here / name).read_text(encoding="utf-8") for name in entry["modules"]
                )
                assert producer in module_text, (
                    f"contract {entry['id']} never references its producer {producer}"
                )


def check_phase_sequence(contract: dict) -> None:
    ids = [step["id"] for step in contract["phaseSequence"]]
    assert ids, "phaseSequence is empty"
    assert len(ids) == len(set(ids)), f"duplicate phase ids: {ids}"
    assert ids[0] == "S0", "the sequence must start at S0"
    assert ids[-1] == "Z", "the sequence must end with the cleanup phase"
    assert ids.index("S1") < ids.index("Q0"), "S1 must run before the accelerator is enabled"
    for gate in ("Q0", "Q1", "Q2", "Q3", "Q4"):
        assert gate in ids, f"contract sequence is missing the {gate} gate"


def check_finalist_before_product(contract: dict) -> None:
    by_id = {step["id"]: step for step in contract["phaseSequence"]}
    freeze = by_id.get("F")
    assert freeze is not None, "the sequence must freeze a finalist set before product work"
    freeze_at = contract["phaseSequence"].index(freeze)
    for step in contract["phaseSequence"]:
        if step.get("appliesTo") == "finalists":
            at = contract["phaseSequence"].index(step)
            assert at > freeze_at, f"{step['id']} is finalist-only but runs before the finalist set is frozen"
            assert freeze["id"] in step.get("requires", []), (
                f"{step['id']} must declare the frozen finalist set as a requirement"
            )


def check_product_stages_are_finalist_only(contract: dict, here: Path) -> None:
    applicability = contract["stageApplicability"]
    all_candidates = list(applicability["allCandidates"])
    finalists_only = list(applicability["finalistsOnly"])
    assert set(all_candidates).isdisjoint(finalists_only), (
        f"a stage cannot be both all-candidate and finalist-only: {set(all_candidates) & set(finalists_only)}"
    )
    assert finalists_only, "the contract must declare at least one finalist-only stage"

    # The matrix builder is where finalist-only semantics are enforced at report
    # time, so the contract must name exactly the same product stages.
    matrix_source = (here / contract["sources"]["matrixBuilder"]).read_text(encoding="utf-8")
    declared = re.search(r"^PRODUCT_STAGES = \(([^)]*)\)", matrix_source, flags=re.M)
    assert declared, "cannot read PRODUCT_STAGES from the matrix builder"
    names = sorted(part.strip().strip("\"'") for part in declared.group(1).split(",") if part.strip())
    assert names == sorted(finalists_only), (
        f"contract finalist-only stages {finalists_only} disagree with the matrix builder {names}"
    )


def check_no_phase_all_in_canonical_commands(contract: dict, runbook_text: str) -> None:
    forbidden = contract["canonicalCliPhases"]["forbiddenInCanonicalCommands"]
    assert forbidden, "the contract must declare forbidden canonical command patterns"
    used: list[str] = []
    for block in canonical_commands(runbook_text):
        tokens = bash_tokens(block)
        for index, token in enumerate(tokens[:-1]):
            if token == "--phase":
                value = tokens[index + 1]
                used.append(value)
                if any(re.fullmatch(pattern, f"--phase {value}") for pattern in forbidden):
                    raise ContractError(
                        f"canonical runbook issues a forbidden phase `{value}`, which "
                        "schedules product stages for every candidate instead of only the frozen finalists"
                    )
    screening = contract["canonicalCliPhases"]["screeningPhase"]
    assert used, "the canonical runbook never passes --phase at all"
    assert screening in used, f"the canonical runbook must issue the screening phase {screening!r}"


def check_cli_phase_choices_match_contract(contract: dict, here: Path) -> None:
    """A CLI phase rename must fail until the runbook and contract follow."""
    cli = contract["canonicalCliPhases"]
    roster_source = (here / contract["sources"]["rosterRunner"]).read_text(encoding="utf-8")
    assert '"--phase", choices=sorted(PHASE_STAGES)' in roster_source, (
        "the roster runner no longer derives --phase choices from PHASE_STAGES"
    )
    block = re.search(r"PHASE_STAGES = \{(.*?)\n\}", roster_source, flags=re.S)
    assert block, "cannot read PHASE_STAGES from the roster runner"
    declared = sorted(re.findall(r'^\s*"([^"]+)":', block.group(1), flags=re.M))
    assert declared, "PHASE_STAGES declares no phases"
    assert declared == sorted(cli["declaredChoices"]), (
        f"roster --phase choices {declared} disagree with the contract {sorted(cli['declaredChoices'])}"
    )

    screening = cli["screeningPhase"]
    stages = re.search(rf'"{screening}": \(([^)]*)\)', roster_source)
    assert stages, f"cannot read the {screening!r} phase stage list"
    scheduled = [part.strip().strip("\"'") for part in stages.group(1).split(",") if part.strip()]
    product = set(contract["stageApplicability"]["finalistsOnly"])
    assert not product.intersection(scheduled), (
        f"screening phase {screening!r} schedules finalist-only stages {sorted(product.intersection(scheduled))}"
    )


def check_gate_chain_matches_register(contract: dict, here: Path) -> None:
    chain = contract["gateChain"]
    register = load_json(here / chain["registerFile"])
    assert int(register.get("manifestVersion") or 0) >= chain["minManifestVersion"], (
        f"stage register manifestVersion {register.get('manifestVersion')} is older than required"
    )
    actual = [entry["gate"] for entry in register["qualificationLadder"]]
    assert actual == list(chain["requiredOrder"]), (
        f"stage register gate order {actual} disagrees with the contract {chain['requiredOrder']}"
    )

    stage_gates = {stage: entry["gate"] for stage, entry in register["stages"].items()}
    for step in contract["phaseSequence"]:
        stage, gate = step.get("stage"), step.get("gate")
        if stage in stage_gates and gate:
            assert stage_gates[stage] == gate, (
                f"runbook maps {stage} to {gate} but the register maps it to {stage_gates[stage]}"
            )


def check_generation_ladder_is_documented(contract: dict, here: Path) -> None:
    """The frozen ladder must match the runnable constant, not a hand-typed list."""
    runner_path = here / contract["sources"]["vllmCandidateRunner"]
    ladder = list(read_tuple_constant(runner_path, "CANONICAL_GENERATION_LADDER"))
    product = list(read_tuple_constant(runner_path, "PRODUCT_BATCH_POLICY"))
    assert ladder and ladder == sorted(ladder, reverse=True), f"ladder must descend: {ladder}"
    assert ladder[-1] == 1, "the ladder must terminate at batch 1"
    assert product == [1], f"product stages must use one frozen batch, got {product}"
    assert len(ladder) > len(product), "the product policy must not be the English ladder"

    documented = " -> ".join(str(value) for value in ladder)
    # Line-anchored, because "32 -> 16 -> 8 -> 4 -> 1" is a substring of the stale
    # "64 -> 32 -> 16 -> 8 -> 4 -> 1"; a bare `in` test would accept that drift.
    anchored = re.compile(rf"(?m)^\s*`?{re.escape(documented)}`?\s*$")
    for label, name in (
        ("hardening contract", contract["sources"]["hardeningContract"]),
        ("runbook", contract["sources"]["runbook"]),
    ):
        text = (here / name).read_text(encoding="utf-8")
        assert anchored.search(text), (
            f"{label} does not state the runnable ladder `{documented}` on its own line"
        )
        stale = re.search(r"(?m)^\s*`?64 -> 32[^`\n]*`?\s*$", text)
        assert not stale, f"{label} still documents the stale 64-first ladder: {stale.group(0)!r}"


def check_pinned_runtime_ids_exist(contract: dict, here: Path) -> None:
    """A runtime artifact id or digest named by the runbook must exist in the registry."""
    registry = load_json(here / contract["sources"]["pinnedRuntimes"])
    by_id = {artifact["id"]: artifact for artifact in registry["artifacts"]}
    runbook = (here / contract["sources"]["runbook"]).read_text(encoding="utf-8")

    # An artifact id named in the runbook must exist, and each registered artifact
    # the runbook relies on must be named, so a runtime cannot be added or renamed
    # without the runbook following.
    named = re.findall(r"registry artifact id: `([^`]+)`", runbook, flags=re.I)
    unknown = sorted(name for name in named if name not in by_id)
    assert not unknown, f"runbook references unregistered runtime artifact ids: {unknown}"

    required_ids = set(contract["runtimePolicy"].get("requiredArtifactIds") or [])
    assert required_ids, "the contract must declare which pinned runtime artifacts the runbook relies on"
    assert required_ids <= set(by_id), (
        f"contract requires unregistered runtime artifacts: {sorted(required_ids - set(by_id))}"
    )
    missing_ids = sorted(required_ids - set(named))
    assert not missing_ids, f"runbook does not name required runtime artifact ids: {missing_ids}"

    digests = set(re.findall(r"\b[0-9a-f]{64}\b", runbook))
    registered = {artifact["sha256"] for artifact in registry["artifacts"]}
    stale = sorted(digest for digest in digests if digest not in registered)
    assert not stale, f"runbook pins digests absent from the runtime registry: {stale}"

    policy = registry.get("policy") or {}
    runtime_policy = contract["runtimePolicy"]
    assert policy.get("sourceBuildDefault") == runtime_policy["sourceBuildDefault"], (
        "the runbook contract and the pinned-runtime registry disagree about source builds"
    )
    assert policy.get("dependencyClosureDefault") == runtime_policy["dependencyClosureDefault"], (
        "the runbook contract and the pinned-runtime registry disagree about the dependency closure policy"
    )


def check_runbook_required_facts(contract: dict, here: Path) -> None:
    runbook = (here / contract["sources"]["runbook"]).read_text(encoding="utf-8")
    lowered = runbook.lower()
    for fact in contract["runbookRequiredFacts"]:
        if "mustMention" in fact:
            missing = [token for token in fact["mustMention"] if token not in runbook]
            assert not missing, f"runbook is missing required {fact['id']} tokens: {missing}"
        else:
            alternatives = fact["anyOf"]
            assert any(token.lower() in lowered for token in alternatives), (
                f"runbook states none of the required {fact['id']} markers: {alternatives}"
            )
        for pattern in fact.get("mustNotMention", []):
            found = re.search(pattern, runbook)
            assert not found, f"runbook contains forbidden {fact['id']} text: {found.group(0)!r}"
        # A command-level rule (for example "no `--phase all` command") is enforced
        # against the fenced command blocks elsewhere, so prose may still name the
        # excluded command. What prose must not do is present it as canonical.
        if fact.get("commandRule") == "forbidInCanonicalCommands":
            for phrase in re.findall(r"`(--phase\s+all)`", runbook):
                window = runbook[max(0, runbook.find(phrase) - 400): runbook.find(phrase) + 400].lower()
                assert any(
                    marker in window
                    for marker in ("not part of", "forbidden", "never", "debugging", "not in the canonical")
                ), f"runbook names `{phrase}` without excluding it from the canonical sequence"


def check_dependency_lock_blocker_is_truthful(contract: dict, here: Path) -> None:
    """The runbook must describe the real lock state of each pinned runtime."""
    registry = load_json(here / contract["sources"]["pinnedRuntimes"])
    runbook = (here / contract["sources"]["runbook"]).read_text(encoding="utf-8")
    pending = [
        env["artifactId"]
        for env in registry.get("environments", [])
        if (env.get("dependencyLock") or {}).get("state") != "locked"
    ]
    if not pending:
        return
    marker = contract["runtimePolicy"]["onDependencyLockPending"]
    assert marker in runbook, (
        f"runbook does not warn that {pending} is blocked on a pending dependency lock ({marker})"
    )
    assert "dependency closure" in runbook.lower(), (
        "runbook must explain the dependency closure policy, not only the classification token"
    )


def check_data_preparation_lock_is_truthful(contract: dict, here: Path) -> None:
    """The runbook's prep-lock claims must match the builder's actual gate."""
    policy = contract["dataPreparationPolicy"]
    builder = (here / policy["builder"]).read_text(encoding="utf-8")
    runbook = (here / contract["sources"]["runbook"]).read_text(encoding="utf-8")

    # The qualified versions and platform gate are hardcoded in the builder, so
    # read them rather than trusting the contract's prose.
    assert 'version not in {"3.10", "3.11"}' in builder, (
        "the data-prep builder no longer gates to CPython 3.10/3.11; update the contract"
    )
    assert 'system != "Linux"' in builder, (
        "the data-prep builder no longer fails closed off Linux; update the contract"
    )
    for profile in policy["qualifiedProfiles"]:
        version = profile.split()[1]
        assert version in runbook, f"runbook does not name the qualified profile version {version}"
    for version in ("3.12", "3.13"):
        assert version in runbook, f"runbook must state that CPython {version} fails closed"

    for flag in ("--require-hashes", "--only-binary=:all:"):
        assert flag in builder, f"the data-prep builder no longer installs with {flag}"
        assert flag in runbook, f"runbook does not state the {flag} install policy"

    named = re.findall(r"`(locks/kaggle-data-prep-[\w.-]+\.txt)`", runbook)
    assert named, "runbook does not name any data-prep lock file"
    for name in named:
        assert (here / name).is_file(), f"runbook names a data-prep lock that does not exist: {name}"

    # Lock-verified is not image-ABI-proven; that caveat must stay visible.
    assert policy.get("caveat"), "the contract must record the unresolved image-ABI caveat"
    assert "image-ABI-proven" in runbook, (
        "runbook must distinguish a lock-verified profile from an image-ABI-proven one"
    )


def contract_status(contract: dict, here: Path) -> list[dict]:
    gates = contract["selfCheckGates"]
    rows = []
    for entry in contract["mandatoryContracts"]:
        modules = list(entry.get("modules") or [])
        gate = entry.get("gate")
        rows.append(
            {
                "id": entry["id"],
                "issue": entry.get("issue"),
                "gate": gate,
                "selfCheck": gates.get(gate),
                "modules": modules,
                "missingModules": [name for name in modules if not (here / name).is_file()],
                "command": entry.get("command"),
                "status": "required" if modules else entry.get("status", "pending"),
            }
        )
    return rows


def check_mandatory_registry_is_complete(contract: dict, here: Path) -> None:
    """A landed contract may never sit on disk without being in the self-check."""
    rows = contract_status(contract, here)
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids)), f"duplicate contract ids: {ids}"

    for row in rows:
        assert not row["missingModules"], (
            f"mandatory contract {row['id']} (issue {row['issue']}) declares missing modules: {row['missingModules']}"
        )
        if row["modules"]:
            assert row["command"], f"required contract {row['id']} has no command"
            assert row["status"] == "required", f"contract {row['id']} has modules but status {row['status']!r}"
        else:
            assert row["command"] is None, (
                f"pending contract {row['id']} must not declare a command before its modules exist"
            )
            assert row["status"] == "pending", f"contract {row['id']} has no modules but status {row['status']!r}"

    # One module and one issue may legitimately back several contracts: a single
    # fixture file can carry both the provenance and the finalist-lifecycle
    # assertions, and #53 spans two independent fixtures. What must stay unique is
    # the contract identity and its (gate, command) wiring, so a contract can
    # never be re-pointed at a different gate or command.
    pairs = [(row["id"], row["gate"], row["command"]) for row in rows]
    assert len(pairs) == len(set(pairs)), f"duplicate contract identity or wiring: {pairs}"
    for row in rows:
        if row["modules"]:
            assert row["command"].startswith(INTERPRETERS), (
                f"contract {row['id']} must run through an explicit interpreter "
                f"({' or '.join(t.strip() for t in INTERPRETERS)}), got {row['command']!r}"
            )
            module = row["command"].split(" ", 1)[1].strip()
            assert module in row["modules"], (
                f"contract {row['id']} runs {module!r}, which it does not declare in modules {row['modules']}"
            )


def check_self_check_invokes_every_contract(contract: dict, here: Path) -> None:
    gates = contract["selfCheckGates"]
    scripts = {
        gate: (here / name).read_text(encoding="utf-8")
        for gate, name in gates.items()
        if isinstance(name, str) and name.endswith(".sh")
    }
    assert scripts, "the contract declares no self-check script gates"
    required = set()
    for row in contract_status(contract, here):
        if not row["modules"]:
            continue
        script = scripts.get(row["gate"], "")
        assert row["command"] in script, (
            f"mandatory contract {row['id']} declares command {row['command']!r} which "
            f"{row['selfCheck']!r} does not run"
        )
        required.add(row["command"])
        # Each module backing a required contract must also be named in the self-check,
        # so renaming a fixture without rewiring the gate fails here.
        for name in row["modules"]:
            assert name in script, (
                f"mandatory contract {row['id']} (issue {row['issue']}) is not invoked by "
                f"{row['selfCheck']}: {name} never appears"
            )
    assert required, "the registry declares no required contract commands"


def imported_modules(path: Path) -> set[str]:
    """Every module a file imports, read from its AST.

    Reading imports rather than searching substrings matters here: a CPU fixture
    may legitimately carry `torch.cuda` inside a *string* to prove that an OOM
    log line classifies as `cuda_oom`, which a substring rule rejects for the
    wrong reason. The rule is about what a module loads at run time.
    """
    if path.suffix != ".py":
        text = path.read_text(encoding="utf-8")
        return set(
            re.findall(r"""(?m)^\s*(?:import|from)\s+['"]?([\w.]+)['"]?""", text)
        )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            base = node.module or ""
            if not base:
                continue
            names.add(base)
            names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def network_call_sites(path: Path) -> list[str]:
    """Lines where an imported HTTP client is actually called.

    The rule is about calls, not imports: a suite may import a client purely to
    decide whether it needs a blocking stub, and a stub that raises on any use
    is stricter evidence of CPU-only behaviour than an import ban.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if alias.name in NETWORK_MODULES or root in NETWORK_MODULES:
                    bound.add(alias.asname or root)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            module = node.module or ""
            if module in NETWORK_MODULES or module.split(".")[0] in NETWORK_MODULES:
                bound.update(alias.asname or alias.name for alias in node.names)
    if not bound:
        return []
    sites: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in bound
            and node.func.attr in NETWORK_CALLS
        ):
            sites.append(f"line {node.lineno}: {node.func.value.id}.{node.func.attr}(...)")
    return sites


def check_registered_modules_stay_cpu_only(contract: dict, here: Path) -> None:
    for row in contract_status(contract, here):
        for name in row["modules"]:
            path = here / name
            for imported in sorted(imported_modules(path)):
                assert imported.split(".")[0] != "vllm", (
                    f"mandatory contract module {name} is not CPU-only: imports {imported!r}"
                )
                assert imported != "torch.cuda", (
                    f"mandatory contract module {name} is not CPU-only: imports {imported!r}"
                )
            if path.suffix == ".py":
                for line in network_call_sites(path):
                    raise ContractError(
                        f"mandatory contract module {name} reaches the network: {line}"
                    )


def check_self_check_covers_every_registered_test(contract: dict, here: Path) -> None:
    """A green test outside the registry is drift #59 cannot see.

    Every module a gate script executes must be a registered contract command in
    that same gate, or an exemption that says why it is not an issue contract.
    Exemptions are held to the same standard: one naming a module no gate runs
    any more is itself rot.
    """
    gates = contract["selfCheckGates"]
    coverage = contract.get("selfCheckCoverage") or {}
    exemptions = {entry["invocation"]: entry for entry in (coverage.get("exemptions") or [])}
    for target, entry in exemptions.items():
        assert entry.get("reason"), f"selfCheckCoverage exempts {target!r} without giving a reason"

    # Registered modules, not just primary commands, and registry-wide rather
    # than per gate. Several contracts are deliberately backed by more than one
    # suite (#30, #53, #39, #57), and a suite registered in one lane is also
    # legitimately re-run in the other; this check answers "is this test in the
    # registry at all", while which lane owns it is check_self_check_invokes_
    # every_contract's job.
    registered: set[str] = set()
    for row in contract_status(contract, here):
        if row["modules"]:
            registered.update(row["modules"])

    invoked: set[str] = set()
    for gate, name in gates.items():
        if not (isinstance(name, str) and name.endswith(".sh")):
            continue
        text = (here / name).read_text(encoding="utf-8")
        for match in INVOCATION_RE.finditer(text):
            target = match.group("target")
            invoked.add(target)
            assert target in registered or target in exemptions, (
                f"{name} runs {target!r}, which is not a registered mandatoryContracts command "
                "and carries no selfCheckCoverage exemption"
            )
    for target in sorted(exemptions):
        assert target in invoked, (
            f"selfCheckCoverage exempts {target!r}, but no gate script runs it any more; "
            "the exemption has rotted and should be removed or its gate restored"
        )


def copy_sources(contract: dict, here: Path, root: Path) -> None:
    for name in contract["sources"].values():
        copy_file(here, root, name)


def copy_file(here: Path, root: Path, name: str) -> None:
    """Mirror one file, keeping any subdirectory it lives in.

    A contract may register a suite that lives in its own lane directory (the
    #68 native-blimp lane), and a fixture root without that directory is not a
    faithful stand-in for the tree.
    """
    src = here / name
    if src.is_file():
        dest = root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())


def copy_contract_inputs(contract: dict, here: Path, root: Path) -> None:
    """Copy every source the consistency checks read, not just declared ones."""
    names = set(contract["sources"].values())
    names.update(
        name
        for name in (contract.get("selfCheckGates") or {}).values()
        if isinstance(name, str) and name.endswith(".sh")
    )
    names.add(contract["gateChain"]["registerFile"])
    if contract.get("dataPreparationPolicy"):
        names.add(contract["dataPreparationPolicy"]["builder"])
    names.add(CONTRACT_PATH.name)
    for row in contract["mandatoryContracts"]:
        names.update(row.get("modules") or [])
    for name in names:
        copy_file(here, root, name)


def check_consistency_contract(here: Path | None = None) -> list[str]:
    """Run every consistency check, returning the collected errors."""
    root = here or HERE
    contract = load_json(CONTRACT_PATH if root == HERE else root / CONTRACT_PATH.name)
    runbook_text = (root / contract["sources"]["runbook"]).read_text(encoding="utf-8")
    errors: list[str] = []
    checks = [
        lambda: check_contract_shape(contract, root),
        lambda: check_phase_sequence(contract),
        lambda: check_finalist_before_product(contract),
        lambda: check_product_stages_are_finalist_only(contract, root),
        lambda: check_no_phase_all_in_canonical_commands(contract, runbook_text),
        lambda: check_cli_phase_choices_match_contract(contract, root),
        lambda: check_gate_chain_matches_register(contract, root),
        lambda: check_generation_ladder_is_documented(contract, root),
        lambda: check_pinned_runtime_ids_exist(contract, root),
        lambda: check_runbook_required_facts(contract, root),
        lambda: check_dependency_lock_blocker_is_truthful(contract, root),
        lambda: check_data_preparation_lock_is_truthful(contract, root),
        lambda: check_mandatory_registry_is_complete(contract, root),
        lambda: check_self_check_invokes_every_contract(contract, root),
        lambda: check_registered_modules_stay_cpu_only(contract, root),
        lambda: check_self_check_covers_every_registered_test(contract, root),
    ]
    for check in checks:
        try:
            check()
        except AssertionError as exc:
            errors.append(str(exc))
    return errors


def test_current_repository_passes() -> None:
    errors = check_consistency_contract()
    assert not errors, "runbook/contract drift:\n- " + "\n- ".join(errors)
    print("  ok  current runbook, CLI, registry, and self-check agree")


def test_product_for_all_candidates_in_runbook_fails() -> None:
    """Runbook says product-all while the contract says finalist-only -> fail."""
    contract = load_json(CONTRACT_PATH)
    runbook = (HERE / contract["sources"]["runbook"]).read_text(encoding="utf-8")
    mutated = runbook.replace("--phase english", "--phase all")
    assert mutated != runbook, "fixture failed to introduce a broad `--phase all` command"
    try:
        check_no_phase_all_in_canonical_commands(contract, mutated)
    except ContractError:
        print("  ok  a canonical `--phase all` command is rejected")
        return
    raise AssertionError("a canonical `--phase all` command was accepted")


def test_code_ladder_drift_fails() -> None:
    """Code OOM ladder differs from the documented ladder -> fail."""
    contract = load_json(CONTRACT_PATH)
    hardening = (HERE / contract["sources"]["hardeningContract"]).read_text(encoding="utf-8")
    ladder = read_tuple_constant(HERE / contract["sources"]["vllmCandidateRunner"], "CANONICAL_GENERATION_LADDER")
    documented = " -> ".join(str(value) for value in ladder)
    assert documented in hardening
    drifted = hardening.replace(documented, "64 -> 32 -> 16 -> 8 -> 4 -> 1")
    assert drifted != hardening, "fixture failed to introduce ladder drift"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        copy_sources(contract, HERE, root)
        (root / contract["sources"]["hardeningContract"]).write_text(drifted, encoding="utf-8")
        try:
            check_generation_ladder_is_documented(contract, root)
        except AssertionError:
            print("  ok  a ladder that disagrees with the runnable constant is rejected")
            return
    raise AssertionError("ladder drift was accepted")


def test_omitted_mandatory_module_fails() -> None:
    """One mandatory test removed from the registry -> fail."""
    contract = load_json(CONTRACT_PATH)
    target = next(row for row in contract["mandatoryContracts"] if row["id"] == "oom-ladder")
    omitted = target["modules"][0]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        copy_contract_inputs(contract, HERE, root)
        (root / omitted).unlink()
        try:
            check_mandatory_registry_is_complete(contract, root)
        except AssertionError:
            print("  ok  a mandatory contract with a missing module fails the registry")
            return
    raise AssertionError("a missing mandatory module was accepted")


def test_contract_command_missing_from_its_gate_fails() -> None:
    """A registry command the named self-check does not run -> fail.

    Regression guard for the drift where the registry declared a contract whose
    command only existed in a different gate script.
    """
    contract = load_json(CONTRACT_PATH)
    target = next(row for row in contract["mandatoryContracts"] if row["id"] == "runtime-dependency-lock")
    gate_script = contract["selfCheckGates"][target["gate"]]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        copy_contract_inputs(contract, HERE, root)
        stripped = (root / gate_script).read_text(encoding="utf-8").replace(
            f"{target['command']}\n", ""
        )
        (root / gate_script).write_text(stripped, encoding="utf-8")
        try:
            check_self_check_invokes_every_contract(contract, root)
        except AssertionError:
            print("  ok  a registry command missing from its gate script is rejected")
            return
    raise AssertionError("a contract command missing from its gate script was accepted")


def test_strict_result_schema_contract_is_required() -> None:
    """#60 must be enforced, not a reserved placeholder.

    Guards the pending -> required transition: once the implementation landed, a
    regression back to an empty module list would silently drop the gate.
    """
    contract = load_json(CONTRACT_PATH)
    entry = next(row for row in contract["mandatoryContracts"] if row["id"] == "strict-result-schema")
    assert entry["modules"] == ["test_kaggle_result_schema.py"], (
        f"#60 must name its landed test module, got {entry['modules']!r}"
    )
    assert entry["command"] == "python3 test_kaggle_result_schema.py"
    assert entry.get("validator") == "validate-english-core-run.py"
    assert entry.get("schema") == "english-core-result-schema.json"
    assert (HERE / entry["command"].removeprefix("python3 ")).is_file()

    # The declared implementation must be the one the test actually exercises,
    # so a renamed validator cannot pass a stale test.
    text = (HERE / "test_kaggle_result_schema.py").read_text(encoding="utf-8")
    assert entry["validator"] in text, f"#60 test does not reference {entry['validator']}"
    assert entry["schema"] in text or "SCHEMA_PATH" in text, (
        f"#60 test does not reference {entry['schema']}"
    )

    check_contract_shape(contract, HERE)
    print("  ok  #60 strict result schema is a required, implementation-pinned contract")


def test_thinking_capability_contract_is_required() -> None:
    """#58 must be enforced against all three runtime producers."""
    contract = load_json(CONTRACT_PATH)
    entry = next(row for row in contract["mandatoryContracts"] if row["id"] == "effective-prompt-mode")
    assert entry["modules"] == ["test_kaggle_thinking_capability.py"], entry["modules"]
    assert entry["command"] == "python3 test_kaggle_thinking_capability.py"
    producers = list(entry.get("producers") or [])
    assert len(producers) == 3, f"#58 must cover all three producers, got {producers}"
    assert (HERE / entry["command"].removeprefix("python3 ")).is_file()

    # The module must exercise each producer, not merely mention it in prose.
    text = (HERE / "test_kaggle_thinking_capability.py").read_text(encoding="utf-8")
    for producer in producers:
        assert producer in text, f"#58 test never references {producer}"
    assert text.count("load_runner(") >= 4, "#58 test must load the real runner modules"
    assert "probe_context_budget" in text, "#58 test must drive a real producer probe"
    # The contract must name the validator whose expectations the payloads must
    # satisfy, and the test must actually drive it.
    assert entry.get("validator") == "validate-english-core-run.py", (
        "#58 must pin the validator whose schema the emitted payloads must satisfy"
    )
    assert "validate_schema" in text, "#58 test must run the real validator schema check"
    assert "strict_json_loads" in text, "#58 test must exercise the validator's strict JSON loader"
    # The unprovable-on-CPU remainder must be recorded, not glossed over.
    residual = entry.get("kaggleOnlyResidual") or ""
    assert residual, "#58 must record what still requires a real Kaggle run"
    assert "kaggle" in residual.lower(), "the residual must name the Kaggle-only proof"
    check_contract_shape(contract, HERE)
    print("  ok  #58 effective prompt mode is required and pinned to three producers")


def test_stale_runtime_artifact_id_fails() -> None:
    """A runtime artifact id in the runbook that is not registered -> fail."""
    contract = load_json(CONTRACT_PATH)
    runbook = (HERE / contract["sources"]["runbook"]).read_text(encoding="utf-8")
    live_id = contract["runtimePolicy"]["requiredArtifactIds"][0]
    mutated = runbook.replace(
        f"Registry artifact id: `{live_id}`",
        "Registry artifact id: `vllm-0.29.0-cu129-linux-x86_64`",
    )
    assert mutated != runbook, "fixture failed to introduce a stale artifact id"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        copy_sources(contract, HERE, root)
        (root / contract["sources"]["runbook"]).write_text(mutated, encoding="utf-8")
        try:
            check_pinned_runtime_ids_exist(contract, root)
        except AssertionError:
            print("  ok  a stale runtime artifact id is rejected")
            return
    raise AssertionError("a stale runtime artifact id was accepted")


def test_data_prep_lock_drift_fails() -> None:
    """A prep-lock claim that stops matching the builder must fail."""
    contract = load_json(CONTRACT_PATH)
    policy = contract["dataPreparationPolicy"]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        copy_contract_inputs(contract, HERE, root)
        builder_name = policy["builder"]
        builder = (root / builder_name).read_text(encoding="utf-8").replace(
            'version not in {"3.10", "3.11"}', 'version not in {"3.10", "3.11", "3.12"}'
        )
        (root / builder_name).write_text(builder, encoding="utf-8")
        try:
            check_data_preparation_lock_is_truthful(contract, root)
        except AssertionError:
            print("  ok  a data-prep lock gate that drifts from the builder is rejected")
            return
    raise AssertionError("data-prep lock drift was accepted")


def test_cli_stage_rename_fails() -> None:
    """A CLI phase rename without a contract update -> fail."""
    contract = load_json(CONTRACT_PATH)
    screening = contract["canonicalCliPhases"]["screeningPhase"]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        copy_sources(contract, HERE, root)
        roster_name = contract["sources"]["rosterRunner"]
        roster = (root / roster_name).read_text(encoding="utf-8")
        (root / roster_name).write_text(
            roster.replace(f'"{screening}":', '"screening":', 1), encoding="utf-8"
        )
        try:
            check_cli_phase_choices_match_contract(contract, root)
        except AssertionError:
            print("  ok  a CLI phase rename without a contract update is rejected")
            return
    raise AssertionError("a renamed CLI phase was accepted")


def test_product_phase_cannot_reach_without_finalist_receipt() -> None:
    """The canonical sequence may not reach a product phase before the freeze."""
    contract = load_json(CONTRACT_PATH)
    sequence = [dict(step) for step in contract["phaseSequence"]]
    freeze_at = next(index for index, step in enumerate(sequence) if step["id"] == "F")
    sequence.append(sequence.pop(freeze_at))
    mutated = dict(contract, phaseSequence=sequence)
    try:
        check_finalist_before_product(mutated)
    except AssertionError:
        print("  ok  product work cannot precede the frozen finalist set")
        return
    raise AssertionError("product work before the finalist freeze was accepted")


def test_exact_current_contract_passes_without_gpu() -> None:
    """The valid contract passes with no GPU, model, or network dependency."""
    errors = check_consistency_contract()
    assert not errors, "the in-tree contract must pass:\n- " + "\n- ".join(errors)
    for entry in load_json(CONTRACT_PATH)["mandatoryContracts"]:
        for name in entry.get("modules") or []:
            assert (HERE / name).is_file(), name
    print("  ok  exact current contract passes on CPU alone")


def test_unregistered_test_in_a_self_check_fails() -> None:
    """A green test nobody registered is drift this gate must be able to see."""
    contract = load_json(CONTRACT_PATH)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        copy_contract_inputs(contract, HERE, root)
        gate_script = contract["selfCheckGates"]["english-core"]
        path = root / gate_script
        path.write_text(
            path.read_text(encoding="utf-8") + "\npython3 test_something_unregistered.py\n",
            encoding="utf-8",
        )
        try:
            check_self_check_covers_every_registered_test(contract, root)
        except AssertionError:
            print("  ok  a self-check test outside the registry is rejected")
            return
    raise AssertionError("an unregistered self-check test was accepted")


def test_rotted_exemption_fails() -> None:
    """An exemption for a test no gate runs any more must not sit forever."""
    contract = load_json(CONTRACT_PATH)
    mutated = json.loads(json.dumps(contract))
    mutated["selfCheckCoverage"]["exemptions"].append(
        {"invocation": "test_already_deleted.py", "reason": "stale"}
    )
    try:
        check_self_check_covers_every_registered_test(mutated, HERE)
    except AssertionError:
        print("  ok  an exemption for a test no gate runs is rejected")
        return
    raise AssertionError("a rotted exemption was accepted")


def test_network_calling_contract_module_fails() -> None:
    """CPU-only means the client is never called, not merely never imported."""
    contract = load_json(CONTRACT_PATH)
    entry = next(row for row in contract["mandatoryContracts"] if row["id"] == "oom-ladder")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        copy_contract_inputs(contract, HERE, root)
        path = root / entry["modules"][0]
        path.write_text(
            "import requests\n\n"
            "def fetch():\n"
            "    return requests.get('https://example.invalid')\n",
            encoding="utf-8",
        )
        try:
            check_registered_modules_stay_cpu_only(contract, root)
        except (AssertionError, ContractError):
            print("  ok  a registered contract module that calls the network is rejected")
            return
    raise AssertionError("a network-calling contract module was accepted")


def test_import_only_network_client_is_allowed() -> None:
    """A suite may import a client purely to install a blocking stub."""
    contract = load_json(CONTRACT_PATH)
    entry = next(row for row in contract["mandatoryContracts"] if row["id"] == "oom-ladder")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        copy_contract_inputs(contract, HERE, root)
        path = root / entry["modules"][0]
        path.write_text(
            "try:\n"
            "    import requests  # noqa: F401\n"
            "except ImportError:\n"
            "    requests = None\n",
            encoding="utf-8",
        )
        check_registered_modules_stay_cpu_only(contract, root)
    print("  ok  importing a client to stub it out is not a network call")


TESTS = [
    test_current_repository_passes,
    test_product_for_all_candidates_in_runbook_fails,
    test_code_ladder_drift_fails,
    test_omitted_mandatory_module_fails,
    test_contract_command_missing_from_its_gate_fails,
    test_strict_result_schema_contract_is_required,
    test_thinking_capability_contract_is_required,
    test_stale_runtime_artifact_id_fails,
    test_data_prep_lock_drift_fails,
    test_cli_stage_rename_fails,
    test_product_phase_cannot_reach_without_finalist_receipt,
    test_exact_current_contract_passes_without_gpu,
    test_unregistered_test_in_a_self_check_fails,
    test_rotted_exemption_fails,
    test_network_calling_contract_module_fails,
    test_import_only_network_client_is_allowed,
]


def main() -> int:
    failures = 0
    for test in TESTS:
        try:
            test()
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL {test.__name__}: {exc}")
    if failures:
        print(f"{failures} runbook consistency check(s) failed.", file=sys.stderr)
        return 1
    print("Kaggle runbook/contract consistency tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

// Snapshot binding for English Core statistical tooling (GitHub issue #65).
//
// Every analysis consumes config/weights, the private seed, the model-visible
// shadow task file, the shadow manifest and the generative metric contract from
// the checkout that happens to run today. Those bytes decide composite weights,
// dimension lists, phenomenon grouping and per-dimension denominators, so they
// must be the exact bytes the source score artifact was computed against.
// Nothing here invents historical bytes: when the score artifact does not name
// an input hash, the analysis fails closed instead of assuming current bytes.

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

// benchmarkInputs key -> file the analysis actually reads for it.
export const SNAPSHOT_FILES = Object.freeze({
  configSha256: "english-core-config.json",
  shadowSeedSha256: "english-core-shadow.seed.json",
  shadowTaskSha256: "english-core-shadow.jsonl",
  shadowManifestSha256: "english-core-shadow.manifest.json",
  generativeMetricContractSha256: "english-core-generative-metric-contract.json",
});

// Keys the scorer v8+ emits. Anything else (for example the prompt/order
// robustness lanes) is a different artifact and must not be analyzed here.
export const REQUIRED_SNAPSHOT_KEYS = Object.freeze(Object.keys(SNAPSHOT_FILES));

export const SCORE_ARTIFACT_TYPE = "pari.english-core.shadow-score";
export const RESULT_SCHEMA_VERSION = 1;
export const PROMOTION_VALIDATION_MODE = "promotion";
export const SCORE_METRIC_RANGE = Object.freeze([0, 1]);

// Issue #64 identity, declared by english_core_choice_views.py. These strings
// are copied from that module's frozen contract constants
// (VIEW_CONTRACT_VERSION, DENOMINATOR_POLICY_VERSION, PRIMARY_SCREENING_VIEW)
// so the JS analysis can name the exact view it read without editing or
// re-implementing the Python scorers. If #64's contract is ever revised, both
// sides must move together and this binding fails closed until they do.
export const SCORE_VIEW_CONTRACT_VERSION = "strict-recoverable-choice-views-v1";
export const SCORE_VIEW_DENOMINATOR_POLICY = "fixed-screening-denominator-v1";
export const SCORE_VIEW_ALLOWED_LABEL_CONTRACT = "allowed-choices-frozen-v1";
export const SCORE_VIEW_CONTRACT_FILE = "english_core_choice_views.py";
export const PRIMARY_SCREENING_SCORE_VIEW = "recoverable_anchored";
export const STRICT_SCORE_VIEW = "strict";

// The metric keys english_core_choice_views.py actually publishes per view.
export const SCORE_VIEW_METRIC_KEYS = Object.freeze({
  [STRICT_SCORE_VIEW]: "strictAccuracyFixedDenominator",
  [PRIMARY_SCREENING_SCORE_VIEW]: "recoverableAccuracyFixedDenominator",
});
export const SCORE_VIEW_NAMES = Object.freeze(Object.keys(SCORE_VIEW_METRIC_KEYS));

export function isSha256Hex(value) {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

export function sha256Bytes(bytes) {
  return crypto.createHash("sha256").update(bytes).digest("hex");
}

export function sha256File(filePath) {
  return sha256Bytes(fs.readFileSync(filePath));
}

function fail(message) {
  throw new Error(message);
}

function readExactFile(dir, name) {
  const filePath = path.join(dir, name);
  let bytes;
  try {
    bytes = fs.readFileSync(filePath);
  } catch (error) {
    fail(
      `Benchmark snapshot file is unavailable: ${name} under ${dir} (${error?.code ?? error?.message}). `
      + "Point --benchmark-dir at the snapshot named by the source score artifact.",
    );
  }
  return { filePath, bytes, sha256: sha256Bytes(bytes) };
}

// Resolves the exact benchmark bytes named by the score artifact and refuses to
// continue on a mismatch. A missing legacy identity is a hard failure, not a
// licence to substitute today's bytes.
export function bindBenchmarkSnapshot({ score, benchmarkDir, label = "Source score" }) {
  const declared = score?.benchmarkInputs;
  if (!declared || typeof declared !== "object") {
    fail(`${label} carries no benchmarkInputs hashes; legacy/unqualified for promotion comparison`);
  }

  const legacyKeys = Object.keys(declared).filter((key) => !(key in SNAPSHOT_FILES));
  const resolved = {};
  for (const key of REQUIRED_SNAPSHOT_KEYS) {
    const expected = declared[key];
    if (!isSha256Hex(expected)) {
      fail(
        `${label} is missing benchmarkInputs.${key}; legacy/unqualified for promotion comparison `
        + `(present keys: ${Object.keys(declared).join(", ") || "none"})`,
      );
    }
    const file = readExactFile(benchmarkDir, SNAPSHOT_FILES[key]);
    if (file.sha256 !== expected) {
      fail(
        `${label} benchmarkInputs.${key} does not match ${path.join(benchmarkDir, SNAPSHOT_FILES[key])}: `
        + `expected ${expected}, found ${file.sha256}. The current checkout is not the benchmark snapshot `
        + "this score was computed against; refusing to re-analyze it under different weights or seed.",
      );
    }
    resolved[key] = { file: SNAPSHOT_FILES[key], path: file.filePath, sha256: file.sha256 };
  }

  const parseJson = (key) => {
    try {
      return JSON.parse(fs.readFileSync(resolved[key].path, "utf8"));
    } catch (error) {
      fail(`Benchmark snapshot file ${resolved[key].file} is not valid JSON: ${error?.message}`);
    }
  };

  const config = parseJson("configSha256");
  const seed = parseJson("shadowSeedSha256");
  const manifest = parseJson("shadowManifestSha256");
  const metricContract = parseJson("generativeMetricContractSha256");

  const taskRows = fs
    .readFileSync(resolved.shadowTaskSha256.path, "utf8")
    .split("\n")
    .filter((line) => line.trim().length > 0)
    .map((line, index) => {
      try {
        return JSON.parse(line);
      } catch (error) {
        fail(`Benchmark snapshot task file line ${index + 1} is not valid JSON: ${error?.message}`);
      }
    });

  validateSnapshotShape({ config, seed, manifest, metricContract, taskRows });

  if (score.taskFileSha256 !== resolved.shadowTaskSha256.sha256) {
    fail(
      `${label} taskFileSha256 (${score.taskFileSha256 ?? "absent"}) does not match the bound shadow task file `
      + `(${resolved.shadowTaskSha256.sha256})`,
    );
  }
  if (!Number.isInteger(score.shadowCases) || score.shadowCases !== seed.cases.length) {
    fail(
      `${label} shadowCases (${score.shadowCases ?? "absent"}) disagrees with the bound seed `
      + `(${seed.cases.length} cases)`,
    );
  }

  return {
    dir: benchmarkDir,
    files: resolved,
    declaredExtraKeys: legacyKeys,
    config,
    seed,
    manifest,
    metricContract,
    taskRows,
  };
}

function validateSnapshotShape({ config, seed, manifest, metricContract, taskRows }) {
  const weights = config?.composite?.weights;
  if (!weights || typeof weights !== "object" || !Object.keys(weights).length) {
    fail("Bound english-core-config.json carries no composite.weights; composite inputs cannot be verified");
  }
  const weightTotal = Object.values(weights).reduce((acc, value) => acc + Number(value ?? 0), 0);
  if (Math.abs(weightTotal - 100) > 1e-9) {
    fail(`Bound composite weights sum to ${weightTotal}, not 100`);
  }
  if (!Array.isArray(seed?.cases) || !seed.cases.length) fail("Bound english-core-shadow.seed.json carries no cases");
  if (!Array.isArray(taskRows) || taskRows.length !== seed.cases.length) {
    fail(
      `Bound shadow task file has ${taskRows?.length ?? 0} rows but the seed has ${seed.cases.length} cases; `
      + "the task file is stale or from a different snapshot",
    );
  }
  if (Number(manifest?.cases) !== seed.cases.length) {
    fail(`Bound shadow manifest declares ${manifest?.cases} cases but the seed has ${seed.cases.length}`);
  }
  if (!metricContract || typeof metricContract !== "object") {
    fail("Bound generative metric contract is not an object");
  }

  const seedIds = seed.cases.map((row) => row?.id);
  if (seedIds.some((id) => typeof id !== "string" || !id)) fail("Bound shadow seed contains a case without an ID");
  if (new Set(seedIds).size !== seedIds.length) fail("Bound shadow seed contains duplicate case IDs");
  for (const dimension of Object.keys(weights)) {
    if (!Object.prototype.hasOwnProperty.call(config.dimensions ?? {}, dimension)) {
      fail(`Bound config weights name dimension ${dimension} that config.dimensions does not define`);
    }
  }
  for (const dimension of Object.keys(config.dimensions ?? {})) {
    if (!Object.prototype.hasOwnProperty.call(weights, dimension)) {
      fail(`Bound config dimension ${dimension} has no composite weight`);
    }
  }
  const unknownDimensions = seedIds
    .map((id) => seed.cases.find((row) => row.id === id))
    .filter((row) => !Object.prototype.hasOwnProperty.call(weights, row.dimension));
  if (unknownDimensions.length) {
    fail(`Bound shadow seed has ${unknownDimensions.length} cases in dimensions absent from the bound weights`);
  }
  taskRows.forEach((row, index) => {
    if (row?.id !== seedIds[index]) {
      fail(`Bound shadow task row ${index + 1} (${row?.id}) does not match seed case ${seedIds[index]}`);
    }
  });
}

// Confirms the score artifact itself was produced by a promotion-validated run
// against the current result schema, and reports which strict/recoverable score
// view the analysis will read (issue #64 artifacts when they exist).
export function requireScoreViewContract(score, label = "Source score", { benchmarkDir = null } = {}) {
  const schema = score?.inputResultSchema;
  if (!schema || typeof schema !== "object") {
    fail(`${label} lacks English Core result-schema validation provenance`);
  }
  if (schema.resultSchemaVersion !== RESULT_SCHEMA_VERSION || !isSha256Hex(schema.schemaSha256)) {
    fail(`${label} lacks current English Core result-schema validation provenance`);
  }
  if (schema.validationMode !== PROMOTION_VALIDATION_MODE) {
    fail(
      `${label} was validated in ${JSON.stringify(schema.validationMode ?? "unknown")} mode; `
      + "promotion comparison requires promotion-mode result validation",
    );
  }
  return {
    resultSchema: {
      validatorContractVersion: schema.validatorContractVersion ?? null,
      validationMode: schema.validationMode,
      resultSchemaVersion: schema.resultSchemaVersion,
      schemaSha256: schema.schemaSha256,
      compatibilityMode: schema.compatibilityMode ?? null,
    },
    scoreView: describeScoreView(score, label, benchmarkDir),
  };
}

function firstString(...candidates) {
  for (const candidate of candidates) {
    if (typeof candidate === "string" && candidate.trim().length) return candidate.trim();
  }
  return null;
}

function metricKeyOf(view, name) {
  const fromMap = view?.metricKeys?.[name];
  if (typeof fromMap === "string" && fromMap.trim().length) return fromMap.trim();
  const branch = view?.[name];
  if (!branch || typeof branch !== "object") return null;
  return firstString(
    branch.metricKey,
    branch.accuracyMetricKey,
    branch.metric,
    name === STRICT_SCORE_VIEW ? view.strictMetricKey : view.recoverableMetricKey,
  );
}

// Normalizes whichever shape the #64 scorer publishes into one explicit
// description. A declared-but-partial view contract is a hard failure: a
// half-declared strict/recoverable pair cannot be silently completed from the
// other side's numbers.
function describeScoreView(score, label, benchmarkDir) {
  const view = score?.scoreView ?? score?.scoreViews ?? null;
  if (!view) {
    return {
      available: false,
      selected: null,
      reason: "The source score artifact declares no strict/recoverable score view (issue #64 lanes are not present yet).",
    };
  }
  if (typeof view !== "object" || Array.isArray(view)) {
    fail(`${label} declares a score view that is not an object`);
  }

  const contractVersion = firstString(view.parseViewContractVersion, view.contractVersion);
  if (contractVersion !== SCORE_VIEW_CONTRACT_VERSION) {
    fail(
      `${label} score view declares contract version ${JSON.stringify(contractVersion)}; this analysis is bound to `
      + `${SCORE_VIEW_CONTRACT_VERSION} as declared by ${SCORE_VIEW_CONTRACT_FILE}`,
    );
  }
  const denominatorPolicy = firstString(view.denominatorPolicyVersion, view.denominatorPolicy);
  if (denominatorPolicy !== SCORE_VIEW_DENOMINATOR_POLICY) {
    fail(
      `${label} score view declares denominator policy ${JSON.stringify(denominatorPolicy)}; expected `
      + `${SCORE_VIEW_DENOMINATOR_POLICY}`,
    );
  }
  const allowedLabelContract = firstString(view.allowedLabelContractVersion);
  if (allowedLabelContract !== SCORE_VIEW_ALLOWED_LABEL_CONTRACT) {
    fail(
      `${label} score view declares allowed-label contract ${JSON.stringify(allowedLabelContract)}; expected `
      + `${SCORE_VIEW_ALLOWED_LABEL_CONTRACT}`,
    );
  }

  const declared = Object.fromEntries(
    SCORE_VIEW_NAMES.map((name) => [name, metricKeyOf(view, name)]),
  );
  const missingMetricKeys = SCORE_VIEW_NAMES.filter((name) => !declared[name]);
  if (missingMetricKeys.length) {
    fail(
      `${label} declares an issue #64 score view but names no metric key for `
      + `${missingMetricKeys.join(" and ")}; a partial view contract is not comparable`,
    );
  }
  for (const name of SCORE_VIEW_NAMES) {
    if (declared[name] !== SCORE_VIEW_METRIC_KEYS[name]) {
      fail(
        `${label} score view ${name} names metric ${JSON.stringify(declared[name])}; ${SCORE_VIEW_CONTRACT_FILE} `
        + `publishes ${SCORE_VIEW_METRIC_KEYS[name]}`,
      );
    }
  }

  const selected = firstString(view.selected, view.primaryScreeningView, view.primary);
  if (selected && !SCORE_VIEW_NAMES.includes(selected)) {
    fail(
      `${label} names primary score view ${JSON.stringify(selected)}; ${SCORE_VIEW_CONTRACT_FILE} declares `
      + SCORE_VIEW_NAMES.map((name) => JSON.stringify(name)).join(" and "),
    );
  }

  const contractFile = firstString(view.contractFile, view.contractPath) ?? SCORE_VIEW_CONTRACT_FILE;
  const declaredContractSha256 = view.contractSha256 ?? view.contractFileSha256 ?? null;
  if (!isSha256Hex(declaredContractSha256)) {
    fail(
      `${label} declares an issue #64 score view without contractSha256 for ${contractFile}; the view contract `
      + "bytes cannot be verified",
    );
  }
  let localContractSha256 = null;
  if (benchmarkDir) {
    const contractPath = path.join(benchmarkDir, contractFile);
    if (!fs.existsSync(contractPath)) {
      fail(
        `${label} names score-view contract ${contractFile}, which is absent from ${benchmarkDir}. Point `
        + "--benchmark-dir at the snapshot that produced this score.",
      );
    }
    localContractSha256 = sha256File(contractPath);
    if (localContractSha256 !== declaredContractSha256) {
      fail(
        `${label} score-view contract ${contractFile} is ${localContractSha256} but the score artifact recorded `
        + `${declaredContractSha256}`,
      );
    }
  }

  // The same block names the parser whose bytes define the strict/recoverable
  // split. When the score recorded a parser hash, the snapshot's parser bytes
  // must still be the ones that produced the view.
  const parserFile = firstString(view.parserFile, view.parserPath);
  const declaredParserSha256 = view.parserSha256 ?? view.parserFileSha256 ?? null;
  let localParserSha256 = null;
  if (parserFile && isSha256Hex(declaredParserSha256) && benchmarkDir) {
    const parserPath = path.join(benchmarkDir, parserFile);
    if (!fs.existsSync(parserPath)) {
      fail(
        `${label} names score-view parser ${parserFile}, which is absent from ${benchmarkDir}. Point `
        + "--benchmark-dir at the snapshot that produced this score.",
      );
    }
    localParserSha256 = sha256File(parserPath);
    if (localParserSha256 !== declaredParserSha256) {
      fail(
        `${label} score-view parser ${parserFile} is ${localParserSha256} but the score artifact recorded `
        + `${declaredParserSha256}`,
      );
    }
  }

  // A score view is only comparable when it was measured over the same task
  // bytes the surrounding score artifact claims. A disagreement means the view
  // block and the score summary describe different runs.
  if (isSha256Hex(view.taskFileSha256) && view.taskFileSha256 !== score.taskFileSha256) {
    fail(
      `${label} score view measured ${path.basename(String(view.taskFile ?? "the model-visible task file"))} `
      + `(${view.taskFileSha256}) while the score artifact records ${String(score.taskFileSha256)}`,
    );
  }
  if (
    isSha256Hex(view.taskManifestSha256)
    && isSha256Hex(score.benchmarkInputs?.shadowManifestSha256)
    && view.taskManifestSha256 !== score.benchmarkInputs.shadowManifestSha256
  ) {
    fail(
      `${label} score view measured shadow manifest ${view.taskManifestSha256} while the score artifact records `
      + `${score.benchmarkInputs.shadowManifestSha256}`,
    );
  }

  return {
    available: true,
    selected,
    contractVersion,
    denominatorPolicy,
    strict: { name: STRICT_SCORE_VIEW, metric: declared[STRICT_SCORE_VIEW] },
    recoverable: { name: PRIMARY_SCREENING_SCORE_VIEW, metric: declared[PRIMARY_SCREENING_SCORE_VIEW] },
    metricKeys: declared,
    contract: {
      file: contractFile,
      declaredSha256: declaredContractSha256,
      localSha256: localContractSha256,
      verifiedLocally: localContractSha256 === declaredContractSha256,
    },
    parser: parserFile
      ? {
        file: parserFile,
        declaredSha256: declaredParserSha256,
        localSha256: localParserSha256,
        verifiedLocally: localParserSha256 !== null && localParserSha256 === declaredParserSha256,
      }
      : null,
    sourceBindings: {
      taskFileSha256: score.taskFileSha256 ?? null,
      taskManifestSha256: score.benchmarkInputs?.shadowManifestSha256 ?? null,
      sourceResultSha256: view.sourceResultSha256 ?? null,
      sourceRunId: view.sourceRunId ?? null,
    },
  };
}

// Independent reconciliation of the score detail rows before any resampling.
// `score.complete` and `dimensionScores[].cases` are treated as claims to check,
// never as truth.
export function reconcileScoreStructure({ score, snapshot, config, label, requirePromotionReady }) {
  const detail = score.detail;
  if (!Array.isArray(detail)) fail(`${label} detail must be an array`);

  const seedById = new Map(snapshot.seed.cases.map((row) => [row.id, row]));
  const ids = detail.map((row) => row?.id);
  if (ids.some((id) => typeof id !== "string" || !id)) fail(`${label} detail contains a missing ID`);
  const duplicates = ids.filter((id, index) => ids.indexOf(id) !== index);
  if (duplicates.length) {
    fail(
      `${label} detail contains ${new Set(duplicates).size} duplicate ID(s) `
      + `(${[...new Set(duplicates)].slice(0, 5).join(", ")}); declared completeness cannot be trusted`,
    );
  }
  const unknown = ids.filter((id) => !seedById.has(id));
  if (unknown.length) {
    fail(`${label} detail contains ${unknown.length} IDs absent from the bound shadow seed`);
  }

  const weights = config.composite.weights;
  const seedCountByDimension = {};
  for (const row of snapshot.seed.cases) {
    seedCountByDimension[row.dimension] = (seedCountByDimension[row.dimension] ?? 0) + 1;
  }

  const declared = score.dimensionScores ?? {};
  const observedByDimension = {};
  for (const row of detail) {
    const dimension = row?.dimension;
    if (typeof dimension !== "string" || !Object.prototype.hasOwnProperty.call(weights, dimension)) {
      fail(`${label} detail row ${row?.id} has dimension ${JSON.stringify(dimension)} absent from the bound weights`);
    }
    const seedRow = seedById.get(row.id);
    if (seedRow.dimension !== dimension) {
      fail(`${label} detail row ${row.id} claims dimension ${dimension} but the bound seed says ${seedRow.dimension}`);
    }
    if ((row.phenomenon ?? null) !== (seedRow.phenomenon ?? null)) {
      fail(
        `${label} detail row ${row.id} claims phenomenon ${JSON.stringify(row.phenomenon ?? null)} but the bound seed `
        + `says ${JSON.stringify(seedRow.phenomenon ?? null)}; regrouping would change the hierarchical lane`,
      );
    }
    if (row.score !== null && row.score !== undefined) {
      if (typeof row.score !== "number" || !Number.isFinite(row.score)) {
        fail(`${label} detail row ${row.id} has a non-finite score`);
      }
      if (row.score < SCORE_METRIC_RANGE[0] || row.score > SCORE_METRIC_RANGE[1]) {
        fail(
          `${label} detail row ${row.id} score ${row.score} is outside the declared metric range `
          + `${SCORE_METRIC_RANGE[0]}..${SCORE_METRIC_RANGE[1]}`,
        );
      }
    }
    (observedByDimension[dimension] ??= []).push(row);
  }

  for (const dimension of Object.keys(weights)) {
    const declaredMeta = declared[dimension];
    if (!declaredMeta || typeof declaredMeta !== "object") {
      fail(`${label} dimensionScores is missing ${dimension} from the bound weight set`);
    }
    const observedRows = observedByDimension[dimension] ?? [];
    if (Number(declaredMeta.cases) !== observedRows.length) {
      fail(
        `${label} dimensionScores.${dimension}.cases declares ${declaredMeta.cases} but the detail carries `
        + `${observedRows.length} rows`,
      );
    }
    if (Number(declaredMeta.cases) !== seedCountByDimension[dimension]) {
      fail(
        `${label} dimensionScores.${dimension}.cases declares ${declaredMeta.cases} but the bound seed has `
        + `${seedCountByDimension[dimension]} cases in that dimension`,
      );
    }
    const scoredRows = observedRows.filter((row) => typeof row.score === "number");
    if (Number(declaredMeta.scored) !== scoredRows.length) {
      fail(
        `${label} dimensionScores.${dimension}.scored declares ${declaredMeta.scored} but ${scoredRows.length} `
        + "detail rows carry a numeric score",
      );
    }
    const missing = observedRows.length - scoredRows.length;
    if (Number(declaredMeta.missing) !== missing) {
      fail(`${label} dimensionScores.${dimension}.missing declares ${declaredMeta.missing} but detail shows ${missing}`);
    }
    if (declaredMeta.complete === true && scoredRows.length !== observedRows.length) {
      fail(
        `${label} dimensionScores.${dimension}.complete is true while ${missing} detail rows are unscored`,
      );
    }
  }

  const dimensionsComplete = Object.keys(weights).every(
    (dimension) => declared[dimension]?.complete === true,
  );
  const detailComplete = Object.values(observedByDimension)
    .flat()
    .every((row) => typeof row.score === "number");
  const reconciledComplete = dimensionsComplete && detailComplete && score.complete === true;
  if (score.complete === true && !reconciledComplete) {
    fail(`${label} declares complete=true but detail/dimension coverage does not reconcile`);
  }
  if (requirePromotionReady && !reconciledComplete) {
    fail(
      `${label} is not completely reconciled; promotion comparison requires every dimension fully scored `
      + "(structural checks run before resampling)",
    );
  }

  return {
    reconciledComplete,
    dimensionsComplete,
    detailComplete,
    seedCountByDimension,
    observedByDimension,
    seedById,
  };
}

// Optional #64 freeze: an explicitly named score view must not be silently
// substituted. When the artifact carries no view contract the analysis states
// that instead of guessing.
export function selectScoreView({ scoreView, requested, label }) {
  if (!requested) return scoreView;
  if (!scoreView.available) {
    fail(
      `${label} declares no strict/recoverable score view, so the requested view `
      + `${JSON.stringify(requested)} cannot be verified`,
    );
  }
  if (!SCORE_VIEW_NAMES.includes(requested)) {
    fail(
      `${label} requested score view ${JSON.stringify(requested)} is not a declared issue #64 view; `
      + `${SCORE_VIEW_CONTRACT_FILE} declares ${SCORE_VIEW_NAMES.map((name) => JSON.stringify(name)).join(" and ")}`,
    );
  }
  const available = new Set(
    SCORE_VIEW_NAMES.filter((name) => scoreView.metricKeys?.[name]),
  );
  if (!available.has(requested)) {
    fail(
      `${label} score view ${JSON.stringify(requested)} is not present in the source artifact `
      + `(available: ${[...available].join(", ") || "none"}; declared issue #64 views: `
      + `${SCORE_VIEW_NAMES.join(", ")})`,
    );
  }
  const substitutedPrimary = Boolean(scoreView.selected && scoreView.selected !== requested);
  return {
    ...scoreView,
    selected: requested,
    primaryScreeningView: scoreView.selected ?? requested,
    explicitlyRequested: true,
    substitutedPrimary,
  };
}

// Optional frozen comparison manifest: proves a score file was not edited
// after its hash was recorded. Format is deliberately small and explicit.
export function verifyFrozenScoreHashes({ manifestPath, entries, label = "Frozen score manifest" }) {
  if (!manifestPath) return null;
  const raw = fs.readFileSync(manifestPath, "utf8");
  let manifest;
  try {
    manifest = JSON.parse(raw);
  } catch (error) {
    fail(`${label} ${manifestPath} is not valid JSON: ${error?.message}`);
  }
  const recorded = {};
  const seen = new Set();
  const collect = (node) => {
    if (!node || typeof node !== "object") return;
    if (Array.isArray(node)) {
      node.forEach(collect);
      return;
    }
    const digest = node.scoreSha256 ?? node.scoreFileSha256 ?? node.sourceScoreFileSha256 ?? null;
    const pathValue = node.scorePath ?? node.path ?? node.file ?? null;
    if (isSha256Hex(digest) && typeof pathValue === "string") {
      const existing = recorded[pathValue];
      if (existing && existing !== digest) {
        fail(`${label} records two different hashes for ${pathValue}`);
      }
      recorded[pathValue] = digest;
      seen.add(pathValue);
    }
    Object.values(node).forEach(collect);
  };
  collect(manifest);
  if (!seen.size) fail(`${label} ${manifestPath} records no score file hashes`);

  const problems = [];
  for (const [name, digest] of Object.entries(entries)) {
    const expected = recorded[name] ?? recorded[path.resolve(name)];
    if (!isSha256Hex(expected)) {
      problems.push(`${name} is not recorded in the frozen manifest`);
      continue;
    }
    if (expected !== digest) {
      problems.push(`${name} hash is ${digest} but the frozen manifest recorded ${expected}`);
    }
  }
  if (problems.length) {
    fail(`${label} mismatch: ${problems.join("; ")}. A score artifact edited after scoring is not comparable.`);
  }
  return {
    manifestPath,
    manifestSha256: sha256Bytes(Buffer.from(raw, "utf8")),
    verifiedScoreFiles: Object.fromEntries(
      Object.entries(entries).map(([name, digest]) => [
        path.basename(name),
        { path: path.resolve(name), sha256: digest, recordedSha256: recorded[name] ?? recorded[path.resolve(name)] },
      ]),
    ),
  };
}

export function buildProvenance({
  label,
  scorePath,
  sourceScoreFileSha256,
  score,
  benchmarkDir,
  analysisScriptName,
  analysisScriptDir,
  scorerName,
  sourceScoreManifest,
  frozenScoreHashEntries = null,
  bootstrapSeed,
  iterations,
}) {
  const view = requireScoreViewContract(score, label, { benchmarkDir });
  const snapshot = bindBenchmarkSnapshot({ score, benchmarkDir, label });
  const analysisScriptPath = path.join(analysisScriptDir, analysisScriptName);
  const scorerPath = path.join(analysisScriptDir, scorerName);
  if (!fs.existsSync(scorerPath)) {
    fail(`Scorer identity ${scorerName} is missing from ${analysisScriptDir}; provenance cannot be recorded`);
  }
  const resultSchemaPath = path.join(benchmarkDir, "english-core-result-schema.json");
  const actualSchemaSha256 = isSha256Hex(view.resultSchema.schemaSha256) && fs.existsSync(resultSchemaPath)
    ? sha256File(resultSchemaPath)
    : null;

  return {
    view,
    snapshot,
    sourceScore: {
      path: path.resolve(scorePath),
      fileSha256: sourceScoreFileSha256,
      runId: score.runId ?? null,
      model: score.model ?? null,
      taskFile: score.taskFile ?? null,
      taskFileSha256: score.taskFileSha256 ?? null,
      taskCount: score.taskCount ?? null,
      scorerVersion: score.version ?? null,
      benchmarkInputs: score.benchmarkInputs,
    },
    scorer: {
      name: scorerName,
      path: scorerPath,
      sha256: sha256File(scorerPath),
    },
    analysis: {
      name: analysisScriptName,
      path: analysisScriptPath,
      sha256: sha256File(analysisScriptPath),
    },
    resultSchema: {
      ...view.resultSchema,
      localSchemaSha256: actualSchemaSha256,
      matchesLocalSchemaBytes: actualSchemaSha256 === view.resultSchema.schemaSha256,
    },
    scoreView: view.scoreView,
    benchmarkSnapshot: {
      directory: snapshot.dir,
      declaredInSourceScore: score.benchmarkInputs,
      consumedInputs: Object.fromEntries(
        Object.entries(snapshot.files).map(([key, file]) => [
          key,
          { file: file.file, path: file.path, sha256: file.sha256 },
        ]),
      ),
      allConsumedInputsVerified: true,
      extraDeclaredKeysNotConsumedHere: snapshot.declaredExtraKeys,
    },
    frozenScoreManifest: sourceScoreManifest
      ? verifyFrozenScoreHashes({
        manifestPath: sourceScoreManifest,
        entries: frozenScoreHashEntries ?? { [scorePath]: sourceScoreFileSha256 },
        label,
      })
      : null,
    bootstrap: {
      seed: bootstrapSeed,
      iterations,
      family: "nonparametric paired/hierarchical resampling (item + phenomenon cluster)",
    },
    interpretation: [
      "Every benchmark input consumed by this analysis was hashed and matched to the hash named by the source score artifact before any statistic was computed.",
      "The recorded source score file hash covers the exact bytes analyzed; editing a score JSON after scoring invalidates any frozen comparison manifest that pins its hash.",
      "Composite weights, dimension denominators and phenomenon grouping come from the bound snapshot bytes, not from whatever checkout executes the analysis.",
    ],
  };
}

// Provenance for a paired comparison, which consumes two score artifacts
// rather than one. Every element a reader needs to reproduce or challenge the
// comparison is recorded: both source score file hashes, the scorer and
// comparison-script hashes, the chosen score view, the bootstrap seed and
// iteration count, and the consumed benchmark input hashes.
export function buildComparisonProvenance({
  label,
  scores,
  benchmarkDir,
  analysisScriptName,
  analysisScriptDir,
  scorerName,
  frozenScoreManifest,
  scoreViews,
  bootstrapSeed,
  iterations,
}) {
  const snapshot = bindBenchmarkSnapshot({
    score: scores[0].score,
    benchmarkDir,
    label: scores[0].label,
  });
  const analysisScriptPath = path.join(analysisScriptDir, analysisScriptName);
  const scorerPath = path.join(analysisScriptDir, scorerName);
  if (!fs.existsSync(scorerPath)) {
    fail(`Scorer identity ${scorerName} is missing from ${analysisScriptDir}; provenance cannot be recorded`);
  }
  const resultSchemaPath = path.join(benchmarkDir, "english-core-result-schema.json");
  const schema = scoreViews[0].view.resultSchema;
  const localSchemaSha256 = isSha256Hex(schema.schemaSha256) && fs.existsSync(resultSchemaPath)
    ? sha256File(resultSchemaPath)
    : null;

  return {
    sourceScores: scores.map((entry, index) => ({
      label: entry.label,
      path: path.resolve(entry.path),
      fileSha256: entry.fileSha256,
      runId: entry.score.runId ?? null,
      model: entry.score.model ?? null,
      taskFile: entry.score.taskFile ?? null,
      taskFileSha256: entry.score.taskFileSha256 ?? null,
      taskCount: entry.score.taskCount ?? null,
      scorerVersion: entry.score.version ?? null,
      benchmarkInputs: entry.score.benchmarkInputs,
      resultSchema: scoreViews[index].view.resultSchema,
      scoreView: scoreViews[index].view.scoreView,
    })),
    scorer: {
      name: scorerName,
      path: scorerPath,
      sha256: sha256File(scorerPath),
    },
    analysis: {
      name: analysisScriptName,
      path: analysisScriptPath,
      sha256: sha256File(analysisScriptPath),
    },
    resultSchema: {
      ...schema,
      localSchemaSha256: localSchemaSha256,
      matchesLocalSchemaBytes: localSchemaSha256 === schema.schemaSha256,
    },
    scoreView: {
      selected: scoreViews[0].selected?.selected ?? null,
      explicitlyRequested: scoreViews[0].selected?.explicitlyRequested ?? false,
      substitutedPrimary: scoreViews[0].selected?.substitutedPrimary ?? false,
      contract: scoreViews[0].selected?.contract ?? null,
      metricKeys: scoreViews[0].selected?.metricKeys ?? null,
      identicalAcrossBothScores:
        scoreViews[0].selected?.selected === scoreViews[1].selected?.selected,
    },
    benchmarkSnapshot: {
      directory: snapshot.dir,
      declaredInSourceScore: scores[0].score.benchmarkInputs,
      identicalAcrossBothScores: scores.every(
        (entry) => JSON.stringify(entry.score.benchmarkInputs) === JSON.stringify(scores[0].score.benchmarkInputs),
      ),
      consumedInputs: Object.fromEntries(
        Object.entries(snapshot.files).map(([key, file]) => [
          key,
          { file: file.file, path: file.path, sha256: file.sha256 },
        ]),
      ),
      allConsumedInputsVerified: true,
      extraDeclaredKeysNotConsumedHere: snapshot.declaredExtraKeys,
    },
    frozenScoreManifest,
    bootstrap: {
      seed: bootstrapSeed,
      iterations,
      family: "nonparametric paired/hierarchical resampling (item + phenomenon cluster)",
    },
    interpretation: [
      "Both source score files were hashed, bound to the benchmark snapshot they name, and compared on the identical item set before any statistic was computed.",
      "Paired item and phenomenon-hierarchical intervals are resampled with a fixed seed; re-running with the recorded seed and iteration count reproduces the same intervals.",
      "Composite weights and per-dimension denominators come from the bound snapshot bytes, not from whatever checkout executes the comparison.",
    ],
  };
}

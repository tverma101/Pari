#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const seed = JSON.parse(fs.readFileSync(path.join(here, "english-core-shadow.seed.json"), "utf8"));
const config = JSON.parse(fs.readFileSync(path.join(here, "english-core-config.json"), "utf8"));

// This audit is intentionally conservative. It can detect structural/data-design
// problems, but it cannot certify linguistic correctness or replace independent
// human annotation. See ENGLISH_CORE_HUMAN_EVAL.md and issue #16.

const errors = [];
const warnings = [];
const rows = seed.cases ?? [];

function normalizeText(value) {
  return String(value ?? "")
    .toLowerCase()
    .normalize("NFKC")
    .replace(/[“”‘’]/g, "'")
    .replace(/[^a-z0-9' ]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function tokens(value) {
  return new Set(normalizeText(value).split(" ").filter(Boolean));
}

function jaccard(a, b) {
  const A = tokens(a);
  const B = tokens(b);
  if (!A.size && !B.size) return 1;
  const inter = [...A].filter((x) => B.has(x)).length;
  const union = new Set([...A, ...B]).size;
  return union ? inter / union : 0;
}

function rowText(row) {
  const values = [];
  for (const key of [
    "sentence", "sentenceA", "sentenceB", "source", "candidate", "text",
    "selection", "target"
  ]) {
    if (row[key]) values.push(row[key]);
  }
  if (Array.isArray(row.sentences)) values.push(...row.sentences);
  if (Array.isArray(row.choices)) {
    for (const choice of row.choices) {
      values.push(Array.isArray(choice) ? choice.join("-") : choice);
    }
  }
  return values.join(" || ");
}

function canonicalPayload(row) {
  const copy = {};
  for (const [k, v] of Object.entries(row)) {
    if (["id", "answer", "phenomenon"].includes(k)) continue;
    copy[k] = v;
  }
  return JSON.stringify(copy);
}

function inc(map, key) {
  map[key] = (map[key] ?? 0) + 1;
}

const ids = new Set();
const exactPayloads = new Map();
const byDimension = {};
const byTask = {};
const byPhenomenon = {};
const labelCounts = {};

for (const row of rows) {
  if (!row.id) errors.push("case missing id");
  else if (ids.has(row.id)) errors.push(`duplicate id: ${row.id}`);
  else ids.add(row.id);

  if (!row.dimension || !config.dimensions?.[row.dimension]) {
    errors.push(`${row.id ?? "<missing-id>"}: unknown/missing dimension ${row.dimension}`);
  }
  if (!row.task) errors.push(`${row.id}: missing task`);
  if (!row.phenomenon) warnings.push(`${row.id}: missing phenomenon tag`);

  inc(byDimension, row.dimension ?? "<missing>");
  inc(byTask, row.task ?? "<missing>");
  inc(byPhenomenon, `${row.dimension}:${row.phenomenon ?? "<missing>"}`);

  const payload = canonicalPayload(row);
  if (exactPayloads.has(payload)) {
    errors.push(`exact duplicate task payload: ${exactPayloads.get(payload)} and ${row.id}`);
  } else {
    exactPayloads.set(payload, row.id);
  }

  switch (row.task) {
    case "same_sense":
    case "same_meaning": {
      if (!new Set(["same", "different"]).has(row.answer)) {
        errors.push(`${row.id}: invalid ${row.task} answer ${JSON.stringify(row.answer)}`);
      }
      inc(labelCounts, `${row.task}:${row.answer}`);
      break;
    }
    case "relation_preservation": {
      if (!new Set(["preserved", "changed"]).has(row.answer)) {
        errors.push(`${row.id}: invalid relation_preservation answer ${JSON.stringify(row.answer)}`);
      }
      inc(labelCounts, `${row.task}:${row.answer}`);
      break;
    }
    case "acceptability_pair": {
      if (!new Set(["A", "B"]).has(row.answer)) errors.push(`${row.id}: answer must be A or B`);
      break;
    }
    case "best_substitute":
    case "minimal_pair":
    case "relation_label": {
      if (!Array.isArray(row.choices) || row.choices.length < 2) {
        errors.push(`${row.id}: ${row.task} requires at least two choices`);
      } else {
        const matches = row.choices.filter((x) => x === row.answer).length;
        if (matches !== 1) errors.push(`${row.id}: answer must occur exactly once in choices`);
        const normalized = row.choices.map(normalizeText);
        if (new Set(normalized).size !== normalized.length) errors.push(`${row.id}: duplicate normalized choices`);
      }
      break;
    }
    case "closer_register":
    case "closer_meaning_and_register":
    case "more_natural": {
      if (!Array.isArray(row.choices) || row.choices.length < 2) errors.push(`${row.id}: choices required`);
      if (!Number.isInteger(row.answer) || row.answer < 0 || row.answer >= (row.choices?.length ?? 0)) {
        errors.push(`${row.id}: answer index out of range`);
      }
      break;
    }
    case "sentence_order": {
      if (!Array.isArray(row.choices) || !Array.isArray(row.answer)) errors.push(`${row.id}: malformed sentence_order case`);
      else if (!row.choices.some((x) => JSON.stringify(x) === JSON.stringify(row.answer))) {
        errors.push(`${row.id}: sentence_order answer not present in choices`);
      }
      break;
    }
    case "generate_span_alternatives":
    case "rewrite_sentence":
    case "rewrite_paragraph":
    case "split_join": {
      if (!Array.isArray(row.scoring) || row.scoring.length < 2) warnings.push(`${row.id}: generative case has weak/missing scoring contract`);
      break;
    }
    default:
      errors.push(`${row.id}: unsupported task ${row.task}`);
  }
}

// Dataset-distribution audit. Kovatchev & Lease (NAACL 2024) show that test-data
// composition can materially alter absolute and relative model performance. These
// diagnostics are therefore reported, not silently collapsed into one score.
for (const dimension of Object.keys(config.dimensions ?? {})) {
  const count = byDimension[dimension] ?? 0;
  if (count === 0) errors.push(`dimension has zero shadow cases: ${dimension}`);
  else if (count < 6) warnings.push(`dimension ${dimension} has only ${count} cases; expect very wide uncertainty`);

  const phenomena = Object.keys(byPhenomenon).filter((x) => x.startsWith(`${dimension}:`));
  if (phenomena.length < 3) warnings.push(`dimension ${dimension} has only ${phenomena.length} distinct phenomenon tags`);
}

// Look for suspiciously similar cases within a dimension. This is only a warning:
// controlled minimal pairs and sense probes can legitimately share vocabulary.
const nearDuplicates = [];
for (let i = 0; i < rows.length; i += 1) {
  for (let j = i + 1; j < rows.length; j += 1) {
    if (rows[i].dimension !== rows[j].dimension) continue;
    const a = rowText(rows[i]);
    const b = rowText(rows[j]);
    if (!a || !b) continue;
    const similarity = jaccard(a, b);
    if (similarity >= 0.82) {
      nearDuplicates.push({ a: rows[i].id, b: rows[j].id, tokenJaccard: Number(similarity.toFixed(3)) });
    }
  }
}

// Binary-label balance is a diagnostic rather than a hard requirement because
// handcrafted cases need not be sampled from a balanced population. Choice order
// is separately randomized at build time, so canonical A/B placement is not used
// as a model-visible shortcut.
const balance = {};
for (const task of ["same_sense", "same_meaning", "relation_preservation"]) {
  const taskRows = rows.filter((x) => x.task === task);
  const counts = {};
  for (const row of taskRows) inc(counts, String(row.answer));
  balance[task] = { cases: taskRows.length, labels: counts };
  if (taskRows.length >= 6 && Object.keys(counts).length < 2) warnings.push(`${task}: only one gold label represented`);
}

const report = {
  version: 1,
  seedVersion: seed.version ?? null,
  validationStatus: seed.validationStatus ?? null,
  cases: rows.length,
  countsByDimension: byDimension,
  countsByTask: byTask,
  countsByPhenomenon: byPhenomenon,
  binaryLabelBalance: balance,
  nearDuplicateWarnings: nearDuplicates,
  errors,
  warnings,
  status: errors.length ? "fail" : warnings.length ? "pass_with_warnings" : "pass",
  interpretation: [
    "This audit detects structural and distributional risks; it does not validate linguistic gold labels.",
    "Near-duplicate similarity warnings are diagnostic because controlled linguistic items can legitimately share words.",
    "Independent annotation remains required before the shadow set supports strong research claims.",
    "Per-dimension/per-phenomenon counts should be inspected because benchmark composition can change model rankings."
  ],
  researchBasis: [
    "Kovatchev & Lease, NAACL 2024, Benchmark Transparency: Measuring the Impact of Data on Evaluation",
    "Liu et al., ACL 2024, Evidence-Centered Benchmark Design",
    "Mizrahi et al., TACL 2024, State of What Art? A Call for Multi-Prompt LLM Evaluation"
  ]
};

console.log(JSON.stringify(report, null, 2));
if (errors.length) process.exitCode = 1;

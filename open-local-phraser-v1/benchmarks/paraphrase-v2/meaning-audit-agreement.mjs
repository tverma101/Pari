#!/usr/bin/env node
/** Compute inter-rater agreement for completed blinded Pari v2 meaning audits. */
import fs from "fs";
import path from "path";

const args = process.argv.slice(2);

function values(flag) {
  const found = [];
  for (let index = 0; index < args.length; index += 1) {
    if (args[index] === flag && args[index + 1]) found.push(args[index + 1]);
  }
  return found;
}

function value(flag) {
  return values(flag)[0];
}

const ratingPaths = values("--ratings")
  .flatMap((entry) => entry.split(","))
  .filter(Boolean)
  .map((entry) => path.resolve(entry));
const keyPath = value("--key") ? path.resolve(value("--key")) : null;
const outPath = path.resolve(value("--out") ?? "meaning-audit-agreement.json");

if (ratingPaths.length < 2) {
  throw new Error(
    "usage: node benchmarks/paraphrase-v2/meaning-audit-agreement.mjs --ratings <rater-a.csv> --ratings <rater-b.csv> [--ratings <rater-c.csv>] [--key <meaning-audit-key.json>] [--out <summary.json>]",
  );
}

const auditKey = keyPath && fs.existsSync(keyPath)
  ? JSON.parse(fs.readFileSync(keyPath, "utf8")).audits ?? {}
  : {};

const raters = ratingPaths.map((filePath, index) => ({
  id: `rater-${index + 1}`,
  filePath,
  rows: indexRatings(parseCsv(fs.readFileSync(filePath, "utf8"))),
}));

const pairwise = [];
for (let left = 0; left < raters.length; left += 1) {
  for (let right = left + 1; right < raters.length; right += 1) {
    pairwise.push(compareRaters(raters[left], raters[right], auditKey));
  }
}

const summary = {
  schemaVersion: 1,
  benchmark: "pari-paraphrase-v2-human-meaning-audit-agreement",
  generatedAt: new Date().toISOString(),
  raters: raters.map((rater) => ({ id: rater.id, file: rater.filePath, validRows: rater.rows.size })),
  pairwise,
  macro: {
    preservedAgreement: mean(pairwise.map((pair) => pair.preserved.percentAgreement)),
    preservedKappa: mean(pairwise.map((pair) => pair.preserved.cohensKappa)),
    contradictionAgreement: mean(pairwise.map((pair) => pair.contradicted.percentAgreement)),
    contradictionKappa: mean(pairwise.map((pair) => pair.contradicted.cohensKappa)),
  },
  interpretation: {
    percentAgreement: "Observed exact agreement among rows that both raters completed for the field.",
    cohensKappa: "Chance-corrected agreement for each rater pair. Null means kappa is undefined because expected agreement is 1 or no jointly rated rows exist.",
    disagreementRows: "Use the emitted disagreement CSV for adjudication; do not silently average disagreements into a semantic-preservation score.",
    promotionUse: "Agreement is a reliability diagnostic, not a quality score for an engine.",
  },
};

fs.mkdirSync(path.dirname(outPath), { recursive: true });
fs.writeFileSync(outPath, JSON.stringify(summary, null, 2) + "\n");

const disagreementPath = outPath.replace(/\.json$/i, "-disagreements.csv");
const disagreementRows = pairwise.flatMap((pair) => pair.disagreements.map((row) => ({
  pair: `${pair.left} vs ${pair.right}`,
  ...row,
})));
fs.writeFileSync(disagreementPath, toCsv(disagreementRows) + (disagreementRows.length ? "\n" : ""));

console.log(`[v2:meaning-agreement] raters=${raters.length} pairs=${pairwise.length}`);
console.log(`[v2:meaning-agreement] summary -> ${outPath}`);
console.log(`[v2:meaning-agreement] disagreements -> ${disagreementPath}`);

function normalizePreserved(value) {
  const normalized = String(value ?? "").trim().toUpperCase();
  return ["Y", "N", "UNCLEAR"].includes(normalized) ? normalized : null;
}

function normalizeBinary(value) {
  const normalized = String(value ?? "").trim().toUpperCase();
  return ["Y", "N"].includes(normalized) ? normalized : null;
}

function indexRatings(rows) {
  const indexed = new Map();
  for (const row of rows) {
    const auditId = String(row.auditId ?? "").trim();
    const preserveItem = Number(row.preserveItem);
    if (!auditId || !Number.isInteger(preserveItem) || preserveItem < 1) continue;
    const key = `${auditId}:${preserveItem}`;
    if (indexed.has(key)) continue;
    indexed.set(key, {
      auditId,
      preserveItem,
      preserved: normalizePreserved(row.preserved),
      contradicted: normalizeBinary(row.contradicted),
      raw: row,
    });
  }
  return indexed;
}

function compareRaters(left, right, key) {
  const sharedKeys = [...left.rows.keys()].filter((rowKey) => right.rows.has(rowKey));
  const preservedPairs = [];
  const contradictionPairs = [];
  const disagreements = [];

  for (const rowKey of sharedKeys) {
    const a = left.rows.get(rowKey);
    const b = right.rows.get(rowKey);
    const meta = key[a.auditId] ?? {};

    if (a.preserved && b.preserved) preservedPairs.push([a.preserved, b.preserved]);
    if (a.contradicted && b.contradicted) contradictionPairs.push([a.contradicted, b.contradicted]);

    if (
      (a.preserved && b.preserved && a.preserved !== b.preserved) ||
      (a.contradicted && b.contradicted && a.contradicted !== b.contradicted)
    ) {
      disagreements.push({
        auditId: a.auditId,
        caseId: meta.caseId ?? a.raw.caseId ?? "",
        engine: meta.engine ?? "",
        preserveItem: a.preserveItem,
        mustPreserve: a.raw.mustPreserve ?? b.raw.mustPreserve ?? "",
        leftPreserved: a.preserved ?? "",
        rightPreserved: b.preserved ?? "",
        leftContradicted: a.contradicted ?? "",
        rightContradicted: b.contradicted ?? "",
      });
    }
  }

  return {
    left: left.id,
    right: right.id,
    sharedRows: sharedKeys.length,
    preserved: agreementStats(preservedPairs),
    contradicted: agreementStats(contradictionPairs),
    disagreementCount: disagreements.length,
    disagreements,
  };
}

function agreementStats(pairs) {
  if (!pairs.length) {
    return { jointlyRated: 0, agreements: 0, percentAgreement: null, cohensKappa: null };
  }

  const agreements = pairs.filter(([left, right]) => left === right).length;
  const observed = agreements / pairs.length;
  const leftCounts = counts(pairs.map(([left]) => left));
  const rightCounts = counts(pairs.map(([, right]) => right));
  const labels = new Set([...leftCounts.keys(), ...rightCounts.keys()]);
  let expected = 0;
  for (const label of labels) {
    expected += ((leftCounts.get(label) ?? 0) / pairs.length) * ((rightCounts.get(label) ?? 0) / pairs.length);
  }

  const kappa = expected >= 1
    ? null
    : (observed - expected) / (1 - expected);

  return {
    jointlyRated: pairs.length,
    agreements,
    percentAgreement: round(observed),
    cohensKappa: Number.isFinite(kappa) ? round(kappa) : null,
  };
}

function counts(values) {
  const result = new Map();
  for (const item of values) result.set(item, (result.get(item) ?? 0) + 1);
  return result;
}

function mean(values) {
  const finite = values.filter(Number.isFinite);
  return finite.length ? round(finite.reduce((sum, item) => sum + item, 0) / finite.length) : null;
}

function round(value) {
  return Number(value.toFixed(4));
}

function parseCsv(text) {
  const records = [];
  let record = [];
  let field = "";
  let quoted = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (quoted) {
      if (char === '"' && text[index + 1] === '"') {
        field += '"';
        index += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        field += char;
      }
      continue;
    }

    if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      record.push(field);
      field = "";
    } else if (char === "\n" || char === "\r") {
      if (char === "\r" && text[index + 1] === "\n") index += 1;
      record.push(field);
      field = "";
      if (record.some((cell) => cell.length > 0)) records.push(record);
      record = [];
    } else {
      field += char;
    }
  }

  if (field.length > 0 || record.length > 0) {
    record.push(field);
    if (record.some((cell) => cell.length > 0)) records.push(record);
  }
  if (quoted) throw new Error("Unterminated quoted field in ratings CSV");
  if (!records.length) return [];

  const headers = records[0];
  return records.slice(1).map((cells) =>
    Object.fromEntries(headers.map((header, index) => [header, cells[index] ?? ""])),
  );
}

function csvCell(value) {
  const text = String(value ?? "");
  return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function toCsv(rows) {
  if (!rows.length) return "";
  const columns = Object.keys(rows[0]);
  return [
    columns.join(","),
    ...rows.map((row) => columns.map((column) => csvCell(row[column])).join(",")),
  ].join("\n");
}

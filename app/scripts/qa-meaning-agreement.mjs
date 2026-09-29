#!/usr/bin/env node
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const script = path.join(ROOT_DIR, "benchmarks/paraphrase-v2/meaning-audit-agreement.mjs");
const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "pari-meaning-agreement-"));

function csvCell(value) {
  const text = String(value ?? "");
  return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function writeRatings(filePath, rows) {
  const columns = ["auditId", "caseId", "preserveItem", "mustPreserve", "preserved", "contradicted"];
  fs.writeFileSync(
    filePath,
    [
      columns.join(","),
      ...rows.map((row) => columns.map((column) => csvCell(row[column])).join(",")),
    ].join("\n") + "\n",
  );
}

try {
  const keyPath = path.join(tempDir, "meaning-audit-key.json");
  fs.writeFileSync(
    keyPath,
    JSON.stringify({
      audits: {
        "audit-a": { engine: "fixture", caseId: "case-1", expectedItems: 2 },
        "audit-b": { engine: "fixture", caseId: "case-2", expectedItems: 2 },
      },
    }),
  );

  const baseRows = [
    { auditId: "audit-a", caseId: "case-1", preserveItem: 1, mustPreserve: "The editor approved the draft." },
    { auditId: "audit-a", caseId: "case-1", preserveItem: 2, mustPreserve: "The deadline stayed Friday,\nnot Thursday." },
    { auditId: "audit-b", caseId: "case-2", preserveItem: 1, mustPreserve: "The result was negative." },
    { auditId: "audit-b", caseId: "case-2", preserveItem: 2, mustPreserve: "The sample contained 12 items." },
  ];

  const raterA = [
    { ...baseRows[0], preserved: "Y", contradicted: "N" },
    { ...baseRows[1], preserved: "Y", contradicted: "N" },
    { ...baseRows[2], preserved: "N", contradicted: "Y" },
    { ...baseRows[3], preserved: "UNCLEAR", contradicted: "N" },
  ];
  const raterB = [
    { ...baseRows[0], preserved: "Y", contradicted: "N" },
    { ...baseRows[1], preserved: "N", contradicted: "Y" },
    { ...baseRows[2], preserved: "N", contradicted: "Y" },
    { ...baseRows[3], preserved: "UNCLEAR", contradicted: "N" },
  ];

  const raterAPath = path.join(tempDir, "rater-a.csv");
  const raterBPath = path.join(tempDir, "rater-b.csv");
  const outPath = path.join(tempDir, "agreement.json");
  writeRatings(raterAPath, raterA);
  writeRatings(raterBPath, raterB);

  execFileSync(
    process.execPath,
    [
      script,
      "--ratings", raterAPath,
      "--ratings", raterBPath,
      "--key", keyPath,
      "--out", outPath,
    ],
    { cwd: ROOT_DIR, stdio: "pipe" },
  );

  const summary = JSON.parse(fs.readFileSync(outPath, "utf8"));
  assert.equal(summary.pairwise.length, 1, "two raters should produce one agreement pair");
  const pair = summary.pairwise[0];
  assert.equal(pair.sharedRows, 4, "multiline CSV parsing lost a rating row");
  assert.equal(pair.preserved.jointlyRated, 4);
  assert.equal(pair.preserved.percentAgreement, 0.75);
  assert.equal(pair.preserved.cohensKappa, 0.6364);
  assert.equal(pair.contradicted.jointlyRated, 4);
  assert.equal(pair.contradicted.percentAgreement, 0.75);
  assert.equal(pair.contradicted.cohensKappa, 0.5);
  assert.equal(pair.disagreementCount, 1, "one disagreement row should be exported once even when both fields differ");
  assert.equal(summary.macro.preservedKappa, 0.6364);
  assert.equal(summary.macro.contradictionKappa, 0.5);

  const disagreementCsv = fs.readFileSync(
    outPath.replace(/\.json$/i, "-disagreements.csv"),
    "utf8",
  );
  assert.match(disagreementCsv, /audit-a/);
  assert.match(disagreementCsv, /deadline stayed Friday/);

  console.log("qa:meaning-agreement passed");
} finally {
  fs.rmSync(tempDir, { recursive: true, force: true });
}

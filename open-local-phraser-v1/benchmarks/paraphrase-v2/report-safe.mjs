#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { assertComparableScoreBundles } from "./score-comparability.mjs";

const args = process.argv.slice(2);
const scorePaths = [];
for (let index = 0; index < args.length; index += 1) {
  if (args[index] !== "--scores" || !args[index + 1]) continue;
  scorePaths.push(...args[index + 1].split(",").filter(Boolean).map((value) => path.resolve(value)));
}

if (scorePaths.length < 1) {
  throw new Error("usage: node benchmarks/paraphrase-v2/report-safe.mjs --scores <score.json> [--scores <score.json>] [--out-dir <dir>]");
}

const bundles = scorePaths.map((filePath) => JSON.parse(fs.readFileSync(filePath, "utf8")));
const allowMixed = args.includes("--allow-mixed-judge");
const comparability = assertComparableScoreBundles(bundles, { allowMixed });

if (!comparability.comparable && allowMixed) {
  console.warn(`[v2:report] WARNING: explicitly allowing non-comparable score bundles: ${comparability.reasons.join("; ")}`);
}

await import("./report.mjs");

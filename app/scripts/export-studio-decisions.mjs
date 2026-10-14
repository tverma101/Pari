#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import {
  exportSavedDecisionsToJsonl,
  getDefaultDecisionLogPath,
} from "../src/lib/persistence/decisionLogger.ts";

const args = process.argv.slice(2);
let outputPath = "";

for (let i = 0; i < args.length; i += 1) {
  if (args[i] === "--output" || args[i] === "-o") {
    outputPath = args[i + 1] || "";
    i += 1;
  }
}

if (!outputPath) {
  outputPath = path.join(process.cwd(), "saved-studio-decisions.jsonl");
}

const sourceLog = getDefaultDecisionLogPath();
console.log(`Reading decisions from: ${sourceLog}`);
const result = exportSavedDecisionsToJsonl(path.resolve(outputPath), sourceLog);
console.log(`Exported ${result.exportedCount} saved studio decisions to: ${result.destination}`);

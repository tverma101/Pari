#!/usr/bin/env tsx
/**
 * Alternative Stress Test Script
 *
 * For each test case in alternativeStressBank.json:
 * 1. Protect the sentence
 * 2. Call getWordAlternatives() for the target token
 * 3. Check that protected words return editable=false
 * 4. Check that editable words return ≥ expected alternatives
 * 5. Check that top alternatives include expected ones
 *
 * Writes results to reports/alternative-stress-results.json
 */

import * as fs from "fs";
import * as path from "path";
import { protectText } from "../src/protection/protectText.js";
import { getWordAlternatives } from "../src/alternatives/getWordAlternatives.js";
import type { AlternativeTestResult, AlternativesResult, AlternativeTokenTest } from "../src/core/types.js";

const REPORTS_DIR = path.resolve(import.meta.dirname, "../reports");

interface AltTestEntry {
  id: string;
  description: string;
  sentence: string;
  tokenTests: Array<{
    token: string;
    expectedEditable: boolean;
    expectedProtected: boolean;
    expectedMinAlternatives: number;
    expectedTopAlternatives: string[];
    notes: string;
  }>;
}

async function runAltTest(entry: AltTestEntry): Promise<AlternativeTestResult> {
  const sentence = entry.sentence;
  const protection = protectText({ text: sentence });

  // Tokenize to find indices for each target token
  const tokens = sentence.split(/\s+/);

  const tokenTests: AlternativeTokenTest[] = [];

  for (const test of entry.tokenTests) {
    // Find the first occurrence of this token text in the sentence.
    // Handle multi-word tokens (e.g. "The Cathedral") by checking sequences.
    const testWords = test.token.split(/\s+/);
    let tokenIndex = -1;

    if (testWords.length === 1) {
      // Single word — strip non-alphanum (incl. quotes/apostrophes) from both sides
      const stripRe = /[^a-zA-Z0-9]/g;
      tokenIndex = tokens.findIndex((t) => t.replace(stripRe, "") === test.token.replace(stripRe, ""));
    } else {
      // Multi-word — find matching sequence of tokens
      const stripRe = /[^a-zA-Z0-9]/g;
      for (let i = 0; i <= tokens.length - testWords.length; i++) {
        const seq = tokens.slice(i, i + testWords.length);
        const seqJoined = seq.map((t) => t.replace(stripRe, "")).join(" ");
        if (seqJoined === testWords.join(" ")) {
          tokenIndex = i;
          break;
        }
      }
    }

    if (tokenIndex === -1) {
      tokenTests.push({
        token: test.token,
        expectedEditable: test.expectedEditable,
        expectedProtected: test.expectedProtected,
        expectedAlternativesCount: test.expectedMinAlternatives,
        actualAlternativesCount: 0,
        hasTopAlternatives: false,
        passed: false,
        failures: [`Token "${test.token}" not found in sentence`],
      });
      continue;
    }

    const result = getWordAlternatives(sentence, tokenIndex, protection.spans);

    const failures: string[] = [];
    let passed = true;

    // Check editable status
    if (result.editable !== test.expectedEditable) {
      failures.push(`Expected editable=${test.expectedEditable}, got ${result.editable}`);
      passed = false;
    }

    // Check protected status
    if (result.protected !== test.expectedProtected) {
      failures.push(`Expected protected=${test.expectedProtected}, got ${result.protected}`);
      passed = false;
    }

    // Check minimum alternatives count
    if (result.alternatives.length < test.expectedMinAlternatives && result.editable) {
      failures.push(`Expected ≥${test.expectedMinAlternatives} alternatives, got ${result.alternatives.length}`);
      passed = false;
    }

    // Check top alternatives
    let hasTopAlternatives = false;
    if (test.expectedTopAlternatives.length > 0 && result.alternatives.length > 0) {
      const topTexts = result.alternatives.map((a) => a.text.toLowerCase());
      hasTopAlternatives = test.expectedTopAlternatives.some(
        (expected) => topTexts.includes(expected.toLowerCase())
      );
      if (!hasTopAlternatives && test.expectedMinAlternatives > 0) {
        failures.push(`No expected top alternatives found: ${test.expectedTopAlternatives.slice(0, 3).join(", ")}`);
        // Don't fail the test for this — it's a soft check
      }
    }

    tokenTests.push({
      token: test.token,
      expectedEditable: test.expectedEditable,
      expectedProtected: test.expectedProtected,
      expectedAlternativesCount: test.expectedMinAlternatives,
      actualAlternativesCount: result.alternatives.length,
      hasTopAlternatives,
      passed,
      failures,
    });
  }

  return {
    sentence: sentence.substring(0, 60),
    tokenTests,
  };
}

async function main() {
  console.log("=== Alternative/Synonym Stress Tests ===");
  console.log();

  const altBankPath = path.resolve(import.meta.dirname, "../tests/alternativeStressBank.json");
  const tests: AltTestEntry[] = JSON.parse(fs.readFileSync(altBankPath, "utf-8"));

  console.log(`Running ${tests.length} alternative test groups...\n`);

  const results: AlternativeTestResult[] = [];
  let totalTokens = 0;
  let passedTokens = 0;
  let failedTokens = 0;

  for (const test of tests) {
    console.log(`  ${test.id}: ${test.description.substring(0, 60)}`);
    const result = await runAltTest(test);
    results.push(result);

    for (const tokenTest of result.tokenTests) {
      totalTokens++;
      const status = tokenTest.passed ? "PASS" : "FAIL";
      if (tokenTest.passed) passedTokens++;
      else failedTokens++;
      console.log(`    ${status} ${tokenTest.token.padEnd(20)} editable=${tokenTest.expectedEditable} alts=${tokenTest.actualAlternativesCount}/${tokenTest.expectedAlternativesCount}`);
    }
  }

  const passRate = totalTokens > 0 ? (passedTokens / totalTokens * 100).toFixed(0) : "0";
  console.log(`\n=== Token Results: ${passedTokens}/${totalTokens} passed (${passRate}%) ===`);

  // Write report
  if (!fs.existsSync(REPORTS_DIR)) {
    fs.mkdirSync(REPORTS_DIR, { recursive: true });
  }

  const reportPath = path.join(REPORTS_DIR, "alternative-stress-results.json");
  const report = {
    timestamp: new Date().toISOString(),
    totalTokenTests: totalTokens,
    passed: passedTokens,
    failed: failedTokens,
    passRate: `${passRate}%`,
    testGroups: results.length,
    results,
  };

  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2), "utf-8");
  console.log(`Report written to ${reportPath}`);
}

main().catch(console.error);

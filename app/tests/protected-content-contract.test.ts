import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  PROTECTED_CONTENT_CONTRACT_VERSION,
  RANGE_ENCODING_VERSION,
  computeProtectedSpanSha256,
  computeSelectionSha256,
  computeSourceSha256,
  extractProtectedSpans,
  isValidUtf16Boundary,
  sha256Hex,
  validateProtectedContent,
  type ProtectedSpan,
  type ProtectedValidationOptions,
} from "../src/lib/safety/protectedContentContract.ts";

interface FixtureSpan {
  id: string;
  kind: ProtectedSpan["kind"];
  scope: "required" | "context-only";
  text: string;
  start: number;
  end: number;
}

interface FixtureCase {
  id: string;
  route: "whole" | "local";
  anchorPolicy: "minimum" | "exact";
  sourceText: string;
  candidateText: string;
  selection?: { start: number; end: number };
  candidateRange?: { start: number; end: number };
  protectedSpans: FixtureSpan[];
  expect: {
    safe: boolean;
    failureClass?: string;
    spanIds?: string[];
  };
}

interface Fixture {
  contractVersion: number;
  rangeEncoding: string;
  identity: {
    algorithm: string;
    preimageFields: string[];
    preimageSeparator: string;
  };
  identityVectors: Array<{
    id: string;
    text: string;
    sourceSha256: string;
    range: { start: number; end: number };
    rangeSha256: string;
  }>;
  cases: FixtureCase[];
}

const FIXTURE_PATH = fileURLToPath(
  new URL("./fixtures/protected-content-contract-v1.json", import.meta.url)
);
const fixture = JSON.parse(readFileSync(FIXTURE_PATH, "utf8")) as Fixture;

function optionsFor(testCase: FixtureCase): ProtectedValidationOptions {
  const options: ProtectedValidationOptions = {
    route: testCase.route,
    anchorPolicy: testCase.anchorPolicy,
  };
  if (testCase.selection) options.selection = testCase.selection;
  if (testCase.candidateRange) options.candidateRange = testCase.candidateRange;
  return options;
}

function reportedSpanIds(result: {
  missingSpanIds?: string[];
  alteredSpanIds?: string[];
  repeatedMismatchSpanIds?: string[];
  positionDriftSpanIds?: string[];
  introducedSpanIds?: string[];
}): string[] {
  return [
    ...new Set([
      ...(result.missingSpanIds ?? []),
      ...(result.alteredSpanIds ?? []),
      ...(result.repeatedMismatchSpanIds ?? []),
      ...(result.positionDriftSpanIds ?? []),
      ...(result.introducedSpanIds ?? []),
    ]),
  ].sort();
}

test("fixture header matches the implemented contract", () => {
  assert.equal(fixture.contractVersion, PROTECTED_CONTENT_CONTRACT_VERSION);
  assert.equal(fixture.rangeEncoding, RANGE_ENCODING_VERSION);
  assert.equal(fixture.identity.algorithm, "sha256-utf8");
  assert.deepEqual(fixture.identity.preimageFields, [
    "rangeEncoding",
    "sourceSha256",
    "wireStart",
    "wireEnd",
    "text",
  ]);
  assert.equal(fixture.identity.preimageSeparator, "\u001f");
});

test("sha256 helper matches the shared identity vectors", () => {
  assert.equal(sha256Hex(""), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  assert.equal(sha256Hex("abc"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  for (const vector of fixture.identityVectors) {
    assert.equal(computeSourceSha256(vector.text), vector.sourceSha256, vector.id);
    const expected = computeProtectedSpanSha256(
      fixture.rangeEncoding,
      vector.sourceSha256,
      vector.range,
      vector.text.slice(vector.range.start, vector.range.end)
    );
    assert.equal(expected, vector.rangeSha256, vector.id);
  }
});

for (const testCase of fixture.cases) {
  test(`shared fixture: ${testCase.id}`, () => {
    const spans: ProtectedSpan[] = testCase.protectedSpans.map((span) => ({ ...span }));
    const result = validateProtectedContent(
      testCase.sourceText,
      testCase.candidateText,
      spans,
      optionsFor(testCase)
    );
    assert.equal(result.contractVersion, PROTECTED_CONTENT_CONTRACT_VERSION);
    assert.equal(result.rangeEncoding, RANGE_ENCODING_VERSION);
    assert.equal(result.safe, testCase.expect.safe, result.reason ?? "");
    if (!testCase.expect.safe) {
      assert.equal(result.failureClass, testCase.expect.failureClass);
    }
    if (testCase.expect.spanIds) {
      assert.deepEqual(reportedSpanIds(result), [...testCase.expect.spanIds].sort());
    }
  });
}

test("every extracted span reproduces its own source text", () => {
  const samples = [
    'Dr. Maya Chen wrote, "Keep the 42.5% result unchanged" in 2024. Email maya@example.com or visit https://example.com/report. The device may not change $1,200.',
    "Intro line.\n```json\n{\"a\": 1}\n```\nOutro line.",
    "Call `build_plan()` before review.",
    "Renew on 2026-08-10 and meet at 3:30.",
    "Pay $4,200 by 99.9% today.",
  ];
  for (const sample of samples) {
    for (const span of extractProtectedSpans(sample)) {
      assert.equal(sample.slice(span.start, span.end), span.text, `${span.kind} ${span.text}`);
      assert.ok(exactOccurrenceCount(sample, span.text) >= 1, `${span.kind} ${span.text}`);
    }
  }
});

test("extraction does not emit overlapping code spans", () => {
  const fenced = extractProtectedSpans('Text\n```json\n{"a":1}\n```\nmore');
  const code = fenced.filter((span) => span.kind === "code");
  assert.equal(code.length, 1);
  assert.equal(code[0].text, '```json\n{"a":1}\n```');

  const doubled = extractProtectedSpans("a ``x`` b").filter((span) => span.kind === "code");
  assert.equal(doubled.length, 1);
  assert.equal(doubled[0].text, "``x``");
});

test("nested numbers inside a container are not double counted", () => {
  const spans = extractProtectedSpans("The total is $1,200 on 2026-08-10 at 3:30 for 99.9%.");
  const numbers = spans.filter((span) => span.kind === "number").map((span) => span.text);
  assert.deepEqual(numbers, []);
  assert.ok(spans.some((span) => span.kind === "currency" && span.text === "$1,200"));
  assert.ok(spans.some((span) => span.kind === "date" && span.text === "2026-08-10"));
  assert.ok(spans.some((span) => span.kind === "time" && span.text === "3:30"));
  assert.ok(spans.some((span) => span.kind === "percentage" && span.text === "99.9%"));
});

test("stale identity fails closed", () => {
  const source = "Keep 2026 exactly in place.";
  const start = source.indexOf("2026");
  const span: ProtectedSpan = {
    id: "year",
    kind: "number",
    text: "2026",
    start,
    end: start + 4,
    scope: "required",
    rangeEncoding: RANGE_ENCODING_VERSION,
    sourceSha256: computeSourceSha256(source),
  };
  span.protectedSpanSha256 = computeProtectedSpanSha256(
    RANGE_ENCODING_VERSION,
    span.sourceSha256 as string,
    span,
    span.text
  );

  const good = validateProtectedContent(source, "Keep 2026 exactly.", [span]);
  assert.equal(good.safe, true);

  const staleSource = validateProtectedContent(source, "Keep 2026 exactly.", [
    { ...span, sourceSha256: computeSourceSha256("something else") },
  ]);
  assert.equal(staleSource.safe, false);
  assert.equal(staleSource.failureClass, "identity_mismatch");

  const staleDigest = validateProtectedContent(source, "Keep 2026 exactly.", [
    { ...span, protectedSpanSha256: "0".repeat(64) },
  ]);
  assert.equal(staleDigest.failureClass, "identity_mismatch");

  const mismatchedText = validateProtectedContent(source, "Keep 2026 exactly.", [
    { ...span, text: "2027" },
  ]);
  assert.equal(mismatchedText.failureClass, "identity_mismatch");

  const staleSelection = validateProtectedContent(
    source,
    "Keep 2026 exactly.",
    [span],
    { selection: { start, end: start + 4 }, selectionSha256: "f".repeat(64) }
  );
  assert.equal(staleSelection.failureClass, "identity_mismatch");
});

test("selection identity binds position, source, and exact text", () => {
  const source = "Alpha 2026 beta.";
  const selection = { start: 6, end: 10 };
  const digest = computeSelectionSha256(
    RANGE_ENCODING_VERSION,
    computeSourceSha256(source),
    selection,
    source.slice(selection.start, selection.end)
  );
  const matches = validateProtectedContent(source, "Alpha 2026 beta.", extractProtectedSpans(source), {
    route: "local",
    selection,
    selectionSha256: digest,
  });
  assert.equal(matches.safe, true);
  const repeatedSource = "Alpha 2026 beta. 2026 stays outside.";
  const drifted = validateProtectedContent(
    repeatedSource,
    "Beta gamma. 2026 stays outside.",
    extractProtectedSpans(repeatedSource),
    {
      route: "local",
      selection,
      candidateDocumentText: "Beta gamma. 2026 stays outside.",
      candidateRange: { start: 0, end: 10 },
      selectionSha256: computeSelectionSha256(
        RANGE_ENCODING_VERSION,
        computeSourceSha256(repeatedSource),
        selection,
        "2026"
      ),
    }
  );
  assert.equal(drifted.failureClass, "protected_position_drift");
  const reordered = validateProtectedContent(source, "Beta 2026 alpha.", extractProtectedSpans(source), {
    route: "local",
    selection,
    selectionSha256: digest,
  });
  assert.equal(reordered.safe, true);
});

test("utf16 boundaries reject offsets inside a surrogate pair", () => {
  const text = "\u{1F600}Keep 99.9% exactly.";
  assert.equal(isValidUtf16Boundary(text, 0), true);
  assert.equal(isValidUtf16Boundary(text, 1), false);
  assert.equal(isValidUtf16Boundary(text, 2), true);
  assert.equal(isValidUtf16Boundary(text, 3), true);
  assert.equal(isValidUtf16Boundary(text, text.length + 1), false);
});

test("non-BMP prefixes keep protected payloads intact", () => {
  const source = "\u{1F600}\u{1F601} Keep 99.9% exactly.";
  const spans = extractProtectedSpans(source);
  const sla = spans.find((span) => span.kind === "percentage");
  assert.ok(sla);
  assert.equal(source.slice(sla.start, sla.end), "99.9%");
  assert.equal(
    validateProtectedContent(source, "\u{1F600}\u{1F601} Keep 99.9% precisely.", spans).safe,
    true
  );
  assert.equal(
    validateProtectedContent(source, "\u{1F600}\u{1F601} Keep the rate precisely.", spans).failureClass,
    "protected_missing"
  );
});

test("legacy callers keep their three-argument contract", () => {
  const original = "Pay $1,200 by 3:30 to maya@example.com.";
  const spans = extractProtectedSpans(original);
  assert.equal(validateProtectedContent(original, original, spans).safe, true);
  assert.equal(
    validateProtectedContent(original, "Pay $1,300 by 3:30 to maya@example.com.", spans).safe,
    false
  );
  assert.equal(validateProtectedContent(original, "Send it soon.").safe, false);
});

test("introduced proper names are reported separately from missing anchors", () => {
  const original = "Maya Chen wrote the memo.";
  const introduced = validateProtectedContent(original, "Maya Chen and Jordan Lee wrote the memo.", [
    ...extractProtectedSpans(original),
  ]);
  assert.equal(introduced.safe, false);
  assert.equal(introduced.failureClass, "protected_introduced");
  assert.deepEqual(introduced.introduced, ["Jordan Lee"]);

  const swapped = validateProtectedContent(original, "Jordan Lee wrote the memo.", [
    ...extractProtectedSpans(original),
  ]);
  assert.equal(swapped.safe, false);
  assert.equal(swapped.failureClass, "protected_altered");
  assert.ok((swapped.alteredSpanIds ?? []).length > 0);
  assert.ok((swapped.introduced ?? []).includes("Jordan Lee"));
});

test("sentence-initial capitalization is not treated as an introduced name", () => {
  const original = "Maya Chen wrote the memo.";
  const heading = validateProtectedContent(original, "Memo rewrite\nMaya Chen wrote it.", [
    ...extractProtectedSpans(original),
  ]);
  assert.equal(heading.safe, true);
});

function exactOccurrenceCount(text: string, needle: string): number {
  let count = 0;
  let cursor = 0;
  while (cursor <= text.length - needle.length) {
    const index = text.indexOf(needle, cursor);
    if (index < 0) break;
    count += 1;
    cursor = index + 1;
  }
  return count;
}

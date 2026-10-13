export const PROTECTED_CONTENT_CONTRACT_VERSION = 1;
export const RANGE_ENCODING_VERSION = "utf16-v1";
export const SUPPORTED_RANGE_ENCODINGS: readonly string[] = [RANGE_ENCODING_VERSION];
export const IDENTITY_PREIMAGE_SEPARATOR = "\u001f";

export type ProtectedSpanKind =
  | "url"
  | "email"
  | "quote"
  | "citation"
  | "date"
  | "time"
  | "number"
  | "percentage"
  | "currency"
  | "name"
  | "negation"
  | "modality"
  | "list-marker"
  | "code";

export type ProtectedSpanScope = "required" | "context-only";
export type ProtectedRoute = "whole" | "local";
export type ProtectedAnchorPolicy = "minimum" | "exact";
export type ProtectedFailureClass =
  | "identity_mismatch"
  | "protected_altered"
  | "protected_missing"
  | "protected_repeated_mismatch"
  | "protected_position_drift"
  | "protected_introduced";

export interface ProtectedRange {
  start: number;
  end: number;
}

export interface ProtectedSpan {
  id: string;
  kind: ProtectedSpanKind;
  text: string;
  start: number;
  end: number;
  scope?: ProtectedSpanScope;
  rangeEncoding?: string;
  sourceSha256?: string;
  protectedSpanSha256?: string;
  candidateStart?: number;
  candidateEnd?: number;
}

export interface ProtectedValidationOptions {
  route?: ProtectedRoute;
  anchorPolicy?: ProtectedAnchorPolicy;
  selection?: ProtectedRange;
  candidateRange?: ProtectedRange;
  candidateDocumentText?: string;
  sourceSha256?: string;
  selectionSha256?: string;
}

export interface ProtectionValidation {
  safe: boolean;
  reason?: string;
  missing?: ProtectedSpan;
  failureClass?: ProtectedFailureClass;
  failureSpanIds?: string[];
  contractVersion?: number;
  rangeEncoding?: string;
  missingSpanIds?: string[];
  alteredSpanIds?: string[];
  repeatedMismatchSpanIds?: string[];
  positionDriftSpanIds?: string[];
  introducedSpanIds?: string[];
  introduced?: string[];
}

interface CandidateSpan {
  kind: ProtectedSpanKind;
  text: string;
  start: number;
  end: number;
  priority: number;
}

const ANCHOR_KINDS: ReadonlySet<ProtectedSpanKind> = new Set<ProtectedSpanKind>([
  "negation",
  "modality",
]);
const ANCHOR_ALTERED_KINDS: ReadonlySet<ProtectedSpanKind> = new Set<ProtectedSpanKind>([
  "negation",
  "modality",
]);
const SAME_KIND_ALTERED_KINDS: ReadonlySet<ProtectedSpanKind> = new Set<ProtectedSpanKind>([
  "url",
  "email",
  "quote",
  "citation",
  "name",
  "code",
]);
const NUMERIC_KINDS: ReadonlySet<ProtectedSpanKind> = new Set<ProtectedSpanKind>([
  "number",
  "percentage",
  "currency",
  "date",
  "time",
]);
const FAILURE_PRECEDENCE: readonly ProtectedFailureClass[] = [
  "identity_mismatch",
  "protected_altered",
  "protected_repeated_mismatch",
  "protected_missing",
  "protected_position_drift",
  "protected_introduced",
];

const WORD_RE = /[\p{L}\p{N}_]/u;
const DIGIT_RE = /\d/;
const LEADING_SYMBOL_RE = /[$€£¥%@]/;
const NUMERIC_TOKEN_RE = /[$€£¥]?\d[\d,]*(?:\.\d+)?%?/g;

// ---------------------------------------------------------------------------
// Identity helpers (mirrors studio_backend/protected_content.py)
// ---------------------------------------------------------------------------

const SHA256_K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

function rotateRight(value: number, bits: number): number {
  return ((value >>> bits) | (value << (32 - bits))) >>> 0;
}

function sha256HexFromBytes(bytes: Uint8Array): string {
  const state = new Uint32Array([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ]);
  const paddedLength = Math.ceil((bytes.length + 9) / 64) * 64;
  const buffer = new Uint8Array(paddedLength);
  buffer.set(bytes);
  buffer[bytes.length] = 0x80;
  const view = new DataView(buffer.buffer);
  const bitLength = bytes.length * 8;
  view.setUint32(paddedLength - 8, Math.floor(bitLength / 0x100000000), false);
  view.setUint32(paddedLength - 4, bitLength >>> 0, false);

  const schedule = new Uint32Array(64);
  for (let block = 0; block < paddedLength; block += 64) {
    for (let index = 0; index < 16; index += 1) {
      schedule[index] = view.getUint32(block + index * 4, false);
    }
    for (let index = 16; index < 64; index += 1) {
      const previous = schedule[index - 15];
      const recent = schedule[index - 2];
      const s0 = rotateRight(previous, 7) ^ rotateRight(previous, 18) ^ (previous >>> 3);
      const s1 = rotateRight(recent, 17) ^ rotateRight(recent, 19) ^ (recent >>> 10);
      schedule[index] = (schedule[index - 16] + s0 + schedule[index - 7] + s1) >>> 0;
    }

    let a = state[0];
    let b = state[1];
    let c = state[2];
    let d = state[3];
    let e = state[4];
    let f = state[5];
    let g = state[6];
    let h = state[7];

    for (let index = 0; index < 64; index += 1) {
      const s1 = rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25);
      const choose = (e & f) ^ (~e & g);
      const temp1 = (h + s1 + choose + SHA256_K[index] + schedule[index]) >>> 0;
      const s0 = rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22);
      const majority = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (s0 + majority) >>> 0;
      h = g;
      g = f;
      f = e;
      e = (d + temp1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (temp1 + temp2) >>> 0;
    }

    state[0] = (state[0] + a) >>> 0;
    state[1] = (state[1] + b) >>> 0;
    state[2] = (state[2] + c) >>> 0;
    state[3] = (state[3] + d) >>> 0;
    state[4] = (state[4] + e) >>> 0;
    state[5] = (state[5] + f) >>> 0;
    state[6] = (state[6] + g) >>> 0;
    state[7] = (state[7] + h) >>> 0;
  }

  let hex = "";
  for (let index = 0; index < state.length; index += 1) {
    hex += state[index].toString(16).padStart(8, "0");
  }
  return hex;
}

export function sha256Hex(text: string): string {
  return sha256HexFromBytes(new TextEncoder().encode(text));
}

export function computeSourceSha256(text: string): string {
  return sha256Hex(text);
}

export function computeRangeSha256(
  rangeEncoding: string,
  sourceSha256: string,
  wireStart: number,
  wireEnd: number,
  text: string
): string {
  return sha256Hex(
    [rangeEncoding, sourceSha256, String(wireStart), String(wireEnd), text].join(
      IDENTITY_PREIMAGE_SEPARATOR
    )
  );
}

export function computeSelectionSha256(
  rangeEncoding: string,
  sourceSha256: string,
  selection: ProtectedRange,
  selectedText: string
): string {
  return computeRangeSha256(rangeEncoding, sourceSha256, selection.start, selection.end, selectedText);
}

export function computeProtectedSpanSha256(
  rangeEncoding: string,
  sourceSha256: string,
  span: ProtectedRange,
  text: string
): string {
  return computeRangeSha256(rangeEncoding, sourceSha256, span.start, span.end, text);
}

// ---------------------------------------------------------------------------
// UTF-16 range validation (issue #50 semantics)
// ---------------------------------------------------------------------------

export function isValidUtf16Boundary(text: string, offset: number): boolean {
  if (!Number.isInteger(offset) || offset < 0 || offset > text.length) return false;
  if (offset === 0 || offset === text.length) return true;
  const code = text.charCodeAt(offset);
  return !(code >= 0xdc00 && code <= 0xdfff);
}

export function isValidUtf16Range(text: string, range: ProtectedRange): boolean {
  return (
    Number.isInteger(range.start) &&
    Number.isInteger(range.end) &&
    range.start >= 0 &&
    range.end > range.start &&
    range.end <= text.length &&
    isValidUtf16Boundary(text, range.start) &&
    isValidUtf16Boundary(text, range.end)
  );
}

// ---------------------------------------------------------------------------
// Class-aware exact occurrence matching
// ---------------------------------------------------------------------------

function normalizeAnchor(text: string): string {
  return text.toLowerCase();
}

function numericTokenShapes(text: string): Set<string> {
  const shapes = new Set<string>();
  const pattern = new RegExp(NUMERIC_TOKEN_RE.source, "g");
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text)) !== null) {
    shapes.add(match[0].replace(/\d+/g, "#"));
  }
  return shapes;
}

function boundaryAllows(text: string, index: number, needle: string): boolean {
  const first = needle[0];
  const last = needle[needle.length - 1];
  const before = index > 0 ? text[index - 1] : "";
  const afterIndex = index + needle.length;
  const after = afterIndex < text.length ? text[afterIndex] : "";
  const afterNext = afterIndex + 1 < text.length ? text[afterIndex + 1] : "";

  const startsWordish = WORD_RE.test(first) || LEADING_SYMBOL_RE.test(first);
  if (startsWordish && before) {
    if (WORD_RE.test(before)) return false;
    if (LEADING_SYMBOL_RE.test(first) && DIGIT_RE.test(before)) return false;
  }

  const endsWordish = WORD_RE.test(last);
  const identifierish = endsWordish && /[./:@-]/.test(needle);
  const numericTail = DIGIT_RE.test(last) || last === "%";

  if (endsWordish) {
    if (after && WORD_RE.test(after)) return false;
    if (identifierish && after && /[/:@-]/.test(after)) return false;
    if (identifierish && after === "." && afterNext && !/\s/.test(afterNext)) return false;
    // A hyphenated continuation extends the protected token rather than
    // reproducing it (`Maya Chen` inside `Maya Chen-Sato`). A possessive
    // apostrophe is ordinary grammar and stays allowed.
    if (after === "-" && afterNext && WORD_RE.test(afterNext)) return false;
  }

  if (numericTail) {
    if (after && WORD_RE.test(after)) return false;
    if (after && /[.,:/-]/.test(after) && DIGIT_RE.test(afterNext)) return false;
  }

  return true;
}

export function exactOccurrences(text: string, needle: string): number[] {
  if (!needle) return [];
  const positions: number[] = [];
  let cursor = 0;
  while (cursor <= text.length - needle.length) {
    const index = text.indexOf(needle, cursor);
    if (index < 0) break;
    if (boundaryAllows(text, index, needle)) positions.push(index);
    cursor = index + 1;
  }
  return positions;
}

// ---------------------------------------------------------------------------
// Detection
// ---------------------------------------------------------------------------

const PROTECTED_PATTERNS: Array<{
  kind: ProtectedSpanKind;
  pattern: RegExp;
  priority: number;
}> = [
  { kind: "url", pattern: /\bhttps?:\/\/[^\s<>)\]]+/gi, priority: 100 },
  { kind: "email", pattern: /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi, priority: 100 },
  { kind: "quote", pattern: /(?:["“„])[^"”\n]+(?:["”])/g, priority: 90 },
  { kind: "citation", pattern: /\[[^\]\n]{1,100}\]/g, priority: 85 },
  { kind: "citation", pattern: /\([A-Z][^()\n]{0,70}\b\d{4}\b[^()\n]*\)/g, priority: 85 },
  {
    kind: "currency",
    pattern: /(?:[$€£¥]\s*\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\s*(?:USD|EUR|GBP|JPY)\b)/gi,
    priority: 80,
  },
  { kind: "percentage", pattern: /\b\d+(?:\.\d+)?\s?%(?!\w)/g, priority: 80 },
  {
    kind: "date",
    pattern:
      /\b(?:\d{1,4}[-/]\d{1,2}[-/]\d{1,4}|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:,\s*\d{4})?)\b/gi,
    priority: 78,
  },
  { kind: "time", pattern: /\b\d{1,2}:\d{2}(?:\s?[AP]M)?\b/gi, priority: 78 },
  {
    kind: "number",
    pattern: /\b\d[\d,]*(?:\.\d+)?(?:\s?(?:kg|g|lb|lbs|km|mi|MB|GB|ms|s|hours?|minutes?|years?))?\b/gi,
    priority: 72,
  },
  { kind: "list-marker", pattern: /^[ \t]*(?:[-*•]|\d+[.)])(?=\s)/gm, priority: 70 },
  {
    kind: "negation",
    pattern: /\b(?:not|never|no|without|cannot|can't|don't|doesn't|didn't|won't|wouldn't|shouldn't)\b/gi,
    priority: 65,
  },
  {
    kind: "modality",
    pattern: /\b(?:may|might|could|can|must|should|will|would|shall)\b/gi,
    priority: 64,
  },
  {
    kind: "code",
    pattern:
      /(?:[A-Za-z0-9_@~-]+[\\/])*[A-Za-z0-9_@~-]+\.(?:pdf|docx?|xlsx?|pptx?|txt|csv|json|md|ya?ml|toml|ini|log|py|ts|tsx|js|jsx|mjs|cjs|rs|go|java|kt|swift|c|h|cc|cpp|hpp|sh)(?![\w.-])/gi,
    priority: 92,
  },
];

const NAME_PATTERN = /\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})+\b/g;
const HONORIFIC_NAME_PATTERN = /\b(?:Dr|Mr|Ms|Mrs|Prof|Professor)\.?\s+([A-Z][a-z]{2,})\b/g;
const CONTAINER_KINDS: ReadonlySet<ProtectedSpanKind> = new Set<ProtectedSpanKind>([
  "quote",
  "code",
  "date",
  "time",
  "currency",
  "percentage",
]);

function countRun(text: string, index: number, marker: string): number {
  let end = index;
  while (end < text.length && text[end] === marker) end += 1;
  return end - index;
}

function scanFencedCode(text: string): CandidateSpan[] {
  const spans: CandidateSpan[] = [];
  let offset = 0;
  let open: { start: number; marker: string; length: number } | null = null;

  for (const line of text.split("\n")) {
    const trimmed = line.trimStart();
    const match = /^(`{3,}|~{3,})/.exec(trimmed);
    if (match) {
      const marker = match[1];
      const markerStart = offset + line.indexOf(marker);
      if (!open) {
        open = { start: markerStart, marker: marker[0], length: marker.length };
      } else if (marker[0] === open.marker && marker.length >= open.length && trimmed === marker) {
        const end = markerStart + marker.length;
        spans.push({ kind: "code", text: text.slice(open.start, end), start: open.start, end, priority: 92 });
        open = null;
      }
    }
    offset += line.length + 1;
  }

  if (open) {
    spans.push({ kind: "code", text: text.slice(open.start), start: open.start, end: text.length, priority: 92 });
  }
  return spans;
}

function scanInlineCode(text: string, fenced: CandidateSpan[]): CandidateSpan[] {
  const inFence = (index: number): boolean =>
    fenced.some((span) => index >= span.start && index < span.end);
  const spans: CandidateSpan[] = [];
  let index = 0;
  while (index < text.length) {
    if (text[index] !== "`" || inFence(index)) {
      index += 1;
      continue;
    }
    const runLength = countRun(text, index, "`");
    let cursor = index + runLength;
    let closing = -1;
    while (cursor < text.length) {
      if (text[cursor] === "`" && !inFence(cursor)) {
        const length = countRun(text, cursor, "`");
        if (length === runLength) {
          closing = cursor;
          break;
        }
        cursor += length;
        continue;
      }
      cursor += 1;
    }
    if (closing < 0) {
      index += runLength;
      continue;
    }
    const end = closing + runLength;
    spans.push({ kind: "code", text: text.slice(index, end), start: index, end, priority: 92 });
    index = end;
  }
  return spans;
}

// Sentence punctuation is not part of the protected payload. Numeric patterns
// greedily consume a trailing separator (`$20,`) and URL patterns consume a
// sentence-final period, so both classes need the same trailing trim.
function trimTrailingPunctuation(kind: ProtectedSpanKind, text: string): string {
  if (kind === "quote" || kind === "citation" || kind === "code") return text;
  return text.replace(/[.,;:!?]+$/g, "");
}

function collectCandidates(text: string): CandidateSpan[] {
  const candidates: CandidateSpan[] = [];

  for (const { kind, pattern, priority } of PROTECTED_PATTERNS) {
    pattern.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(text)) !== null) {
      const candidateText = trimTrailingPunctuation(kind, match[0]);
      if (!candidateText) continue;
      candidates.push({
        kind,
        text: candidateText,
        start: match.index,
        end: match.index + candidateText.length,
        priority,
      });
    }
  }

  const fenced = scanFencedCode(text);
  candidates.push(...fenced, ...scanInlineCode(text, fenced));

  NAME_PATTERN.lastIndex = 0;
  let nameMatch: RegExpExecArray | null;
  while ((nameMatch = NAME_PATTERN.exec(text)) !== null) {
    candidates.push({
      kind: "name",
      text: nameMatch[0],
      start: nameMatch.index,
      end: nameMatch.index + nameMatch[0].length,
      priority: 75,
    });
  }

  HONORIFIC_NAME_PATTERN.lastIndex = 0;
  let honorificMatch: RegExpExecArray | null;
  while ((honorificMatch = HONORIFIC_NAME_PATTERN.exec(text)) !== null) {
    const name = honorificMatch[1];
    const start = honorificMatch.index + honorificMatch[0].lastIndexOf(name);
    const end = start + name.length;
    if (/^\s+[A-Z][a-z]{2,}\b/.test(text.slice(end))) continue;
    candidates.push({ kind: "name", text: name, start, end, priority: 74 });
  }

  return candidates;
}

function overlaps(left: CandidateSpan, right: CandidateSpan): boolean {
  return left.start < right.end && right.start < left.end;
}

function contains(container: CandidateSpan, inner: CandidateSpan): boolean {
  return container.start <= inner.start && container.end >= inner.end && container !== inner;
}

function isRedundantNestedNumber(container: CandidateSpan, candidate: CandidateSpan): boolean {
  return (
    candidate.kind === "number" &&
    container.kind !== candidate.kind &&
    CONTAINER_KINDS.has(container.kind) &&
    contains(container, candidate)
  );
}

export function extractProtectedSpans(text: string): ProtectedSpan[] {
  const selected: CandidateSpan[] = [];
  const ordered = collectCandidates(text).sort((left, right) => {
    if (left.start !== right.start) return left.start - right.start;
    if (left.priority !== right.priority) return right.priority - left.priority;
    return right.end - left.end;
  });

  for (const candidate of ordered) {
    const rejected = selected.some(
      (existing) =>
        (existing.kind === candidate.kind &&
          existing.start === candidate.start &&
          existing.end === candidate.end) ||
        (existing.kind === "code" && candidate.kind === "code" && overlaps(existing, candidate)) ||
        isRedundantNestedNumber(existing, candidate)
    );
    if (rejected) continue;
    selected.push(candidate);
  }

  const rangeEncoding = RANGE_ENCODING_VERSION;
  const sourceSha256 = computeSourceSha256(text);

  return selected
    .sort((left, right) => left.start - right.start)
    .map((span, index) => ({
      id: `protected-${index}-${span.start}`,
      kind: span.kind,
      text: span.text,
      start: span.start,
      end: span.end,
      scope: "required" as ProtectedSpanScope,
      rangeEncoding,
      sourceSha256,
      protectedSpanSha256: computeProtectedSpanSha256(rangeEncoding, sourceSha256, span, span.text),
    }));
}

// ---------------------------------------------------------------------------
// Evaluation
// ---------------------------------------------------------------------------

function anchorKey(span: ProtectedSpan): string {
  return `${span.kind}:${normalizeAnchor(span.text)}`;
}

function groupKey(span: ProtectedSpan): string {
  return `${span.kind}\u0000${ANCHOR_KINDS.has(span.kind) ? normalizeAnchor(span.text) : span.text}`;
}

function isHeadingLike(text: string, index: number): boolean {
  const lineStart = text.lastIndexOf("\n", index - 1) + 1;
  const prefix = text.slice(lineStart, index);
  return /^\s*(?:[-*#>]+|\d+[.)])\s*$/.test(prefix);
}

function unprotectedIntroductions(originalText: string, regionText: string): string[] {
  const originalNames = new Set(
    extractProtectedSpans(originalText)
      .filter((span) => span.kind === "name")
      .map((span) => normalizeAnchor(span.text))
  );
  return extractProtectedSpans(regionText)
    .filter(
      (span) =>
        span.kind === "name" &&
        !originalNames.has(normalizeAnchor(span.text)) &&
        !isHeadingLike(regionText, span.start)
    )
    .map((span) => span.text);
}

function classifyAbsentSpan(
  span: ProtectedSpan,
  regionText: string,
  regionSpans: ProtectedSpan[],
  repeated: boolean
): ProtectedFailureClass {
  if (NUMERIC_KINDS.has(span.kind)) {
    const shapes = numericTokenShapes(span.text);
    for (const token of numericTokenShapes(regionText)) {
      if (shapes.has(token)) return "protected_altered";
    }
  }
  if (ANCHOR_ALTERED_KINDS.has(span.kind) || SAME_KIND_ALTERED_KINDS.has(span.kind)) {
    // A replacement of the same class (different query string, citation
    // punctuation, swapped modal, extended filename) changed the protected
    // payload instead of omitting it.
    if (regionSpans.some((other) => other.kind === span.kind)) return "protected_altered";
  }
  if (SAME_KIND_ALTERED_KINDS.has(span.kind) && regionText.includes(span.text)) {
    // Byte-exact payload was extended or embedded (for example
    // `report.txt` inside `report.txt.bak`); the protected unit itself changed.
    return "protected_altered";
  }
  if (repeated) return "protected_repeated_mismatch";
  return "protected_missing";
}

function spansOverlapping(spans: ProtectedSpan[], range: ProtectedRange): ProtectedSpan[] {
  return spans.filter((span) => span.start < range.end && span.end > range.start);
}

function failuresHas(failures: Map<ProtectedFailureClass, string[]>, spanId: string): boolean {
  for (const ids of failures.values()) {
    if (ids.includes(spanId)) return true;
  }
  return false;
}

function resolveFailures(
  failures: Map<ProtectedFailureClass, string[]>
): { failureClass?: ProtectedFailureClass; failureSpanIds: string[] } {
  for (const failureClass of FAILURE_PRECEDENCE) {
    const spanIds = failures.get(failureClass);
    if (spanIds && spanIds.length > 0) {
      return { failureClass, failureSpanIds: [...new Set(spanIds)] };
    }
  }
  return { failureSpanIds: [] };
}

function describe(failureClass: ProtectedFailureClass, span: ProtectedSpan): string {
  switch (failureClass) {
    case "identity_mismatch":
      return `Protected span identity did not match the source revision: “${span.text}”`;
    case "protected_altered":
      return `Protected ${span.kind} was changed: “${span.text}”`;
    case "protected_missing":
      return `Protected ${span.kind} was removed: “${span.text}”`;
    case "protected_repeated_mismatch":
      return `Protected ${span.kind} did not survive with its original multiplicity: “${span.text}”`;
    case "protected_position_drift":
      return `Protected ${span.kind} survived outside its bound position: “${span.text}”`;
    default:
      return `The rewrite introduced unsupported protected ${span.kind} content: “${span.text}”`;
  }
}

function emptyValidation(): ProtectionValidation {
  return {
    safe: true,
    contractVersion: PROTECTED_CONTENT_CONTRACT_VERSION,
    rangeEncoding: RANGE_ENCODING_VERSION,
    missingSpanIds: [],
    alteredSpanIds: [],
    repeatedMismatchSpanIds: [],
    positionDriftSpanIds: [],
    introducedSpanIds: [],
    introduced: [],
  };
}

function finalize(
  failures: Map<ProtectedFailureClass, string[]>,
  introduced: string[],
  primary: ProtectedSpan | undefined
): ProtectionValidation {
  const { failureClass, failureSpanIds } = resolveFailures(failures);
  const idsFor = (target: ProtectedFailureClass): string[] => failures.get(target) ?? [];
  const introducedIds = idsFor("protected_introduced");
  const result: ProtectionValidation = {
    ...emptyValidation(),
    safe: failureClass === undefined,
    failureClass,
    failureSpanIds,
    missingSpanIds: idsFor("protected_missing"),
    alteredSpanIds: idsFor("protected_altered"),
    repeatedMismatchSpanIds: idsFor("protected_repeated_mismatch"),
    positionDriftSpanIds: idsFor("protected_position_drift"),
    introducedSpanIds: [...new Set(introducedIds)],
    introduced: [...new Set(introduced)],
  };
  if (failureClass !== undefined && primary) {
    result.reason = describe(failureClass, primary);
    if (failureClass === "protected_missing" || failureClass === "protected_altered") {
      result.missing = primary;
    }
  }
  return result;
}

function recordFailure(
  failures: Map<ProtectedFailureClass, string[]>,
  failureClass: ProtectedFailureClass,
  spanId: string
): void {
  const ids = failures.get(failureClass) ?? [];
  if (!ids.includes(spanId)) failures.set(failureClass, [...ids, spanId]);
}

function validateWholeRoute(
  originalText: string,
  candidateText: string,
  spans: ProtectedSpan[],
  anchorPolicy: ProtectedAnchorPolicy
): ProtectionValidation {
  const failures = new Map<ProtectedFailureClass, string[]>();
  const introduced: string[] = [];
  const groups = new Map<string, ProtectedSpan[]>();
  const candidateSpans = extractProtectedSpans(candidateText);

  for (const span of spans) {
    const key = groupKey(span);
    const bucket = groups.get(key);
    if (bucket) bucket.push(span);
    else groups.set(key, [span]);
  }

  for (const group of groups.values()) {
    const first = group[0];
    const expected = group.length;
    const actual = exactOccurrences(candidateText, first.text).length;
    if (actual < expected) {
      const failureClass =
        actual > 0
          ? "protected_repeated_mismatch"
          : classifyAbsentSpan(first, candidateText, candidateSpans, expected > 1);
      for (const span of group) recordFailure(failures, failureClass, span.id);
      continue;
    }
    if (actual > expected) {
      for (const span of group) recordFailure(failures, "protected_introduced", span.id);
      introduced.push(first.text);
    }
  }

  if (anchorPolicy === "exact") {
    const sourceAnchors = new Set(spans.filter((span) => ANCHOR_KINDS.has(span.kind)).map(anchorKey));
    const sourceByKind = new Map<ProtectedSpanKind, ProtectedSpan[]>();
    for (const span of spans) {
      if (!ANCHOR_KINDS.has(span.kind)) continue;
      const bucket = sourceByKind.get(span.kind);
      if (bucket) bucket.push(span);
      else sourceByKind.set(span.kind, [span]);
    }
    for (const span of candidateSpans) {
      if (ANCHOR_KINDS.has(span.kind) && !sourceAnchors.has(anchorKey(span))) {
        const sameKind = sourceByKind.get(span.kind);
        recordFailure(
          failures,
          "protected_introduced",
          sameKind?.[0]?.id ?? `introduced-${span.kind}:${normalizeAnchor(span.text)}`
        );
        introduced.push(span.text);
      }
    }
  }

  const addedNames = unprotectedIntroductions(originalText, candidateText);
  if (addedNames.length > 0) {
    for (const name of addedNames) {
      recordFailure(failures, "protected_introduced", `introduced-name:${name}`);
      introduced.push(name);
    }
  }

  const primary = spans.find((span) => failuresHas(failures, span.id));
  return finalize(failures, introduced, primary);
}

function validateLocalRoute(
  originalText: string,
  candidateText: string,
  spans: ProtectedSpan[],
  options: ProtectedValidationOptions,
  anchorPolicy: ProtectedAnchorPolicy
): ProtectionValidation {
  const selection = options.selection;
  if (!selection || !isValidUtf16Range(originalText, selection)) {
    return {
      ...emptyValidation(),
      safe: false,
      failureClass: "identity_mismatch",
      failureSpanIds: spans.map((span) => span.id),
      reason: "Local protected-content validation requires a valid selection range.",
    };
  }

  const candidateDocumentText = options.candidateDocumentText ?? candidateText;
  const candidateRange = options.candidateRange ?? {
    start: 0,
    end: candidateDocumentText.length,
  };
  if (!isValidUtf16Range(candidateDocumentText, candidateRange)) {
    return {
      ...emptyValidation(),
      safe: false,
      failureClass: "identity_mismatch",
      failureSpanIds: spans.map((span) => span.id),
      reason: "Candidate replacement range does not match the candidate document.",
    };
  }
  const regionText = candidateDocumentText.slice(candidateRange.start, candidateRange.end);
  const regionSpans = extractProtectedSpans(regionText);
  const failures = new Map<ProtectedFailureClass, string[]>();
  const introduced: string[] = [];

  const insideSelection = spansOverlapping(spans, selection);
  const insideIds = new Set(insideSelection.map((span) => span.id));
  const outsideSelection = spans.filter((span) => !insideIds.has(span.id));

  const consumed = new Set<number>();
  let previousSourceEnd = -1;
  let previousRegionIndex = -1;

  for (const span of insideSelection) {
    const positions = exactOccurrences(regionText, span.text);
    const ordered = positions.filter((position) => position >= previousRegionIndex);
    const nextIndex = ordered.length > 0 ? ordered[0] : positions[0];

    if (positions.length === 0) {
      if (exactOccurrences(candidateDocumentText, span.text).length > 0) {
        recordFailure(failures, "protected_position_drift", span.id);
      } else {
        recordFailure(
          failures,
          classifyAbsentSpan(span, regionText, regionSpans, span.end <= previousSourceEnd),
          span.id
        );
      }
      continue;
    }

    if (span.candidateStart !== undefined && span.candidateEnd !== undefined) {
      const boundStart = span.candidateStart - candidateRange.start;
      const boundEnd = span.candidateEnd - candidateRange.start;
      if (
        boundStart < 0 ||
        boundEnd > regionText.length ||
        regionText.slice(boundStart, boundEnd) !== span.text
      ) {
        recordFailure(failures, "protected_position_drift", span.id);
        continue;
      }
    }

    if (ordered.length === 0 && positions.length === 1 && previousRegionIndex >= 0) {
      recordFailure(failures, "protected_position_drift", span.id);
      continue;
    }

    previousSourceEnd = Math.max(previousSourceEnd, span.end);
    previousRegionIndex = nextIndex + span.text.length;
    consumed.add(nextIndex);
  }

  for (const span of outsideSelection) {
    if (exactOccurrences(regionText, span.text).length > 0) {
      recordFailure(failures, "protected_introduced", span.id);
      introduced.push(span.text);
    }
  }

  const sourceAnchors = new Set(spans.filter((span) => ANCHOR_KINDS.has(span.kind)).map(anchorKey));
  const sourceNames = new Set(
    spans.filter((span) => span.kind === "name").map((span) => normalizeAnchor(span.text))
  );
  for (const span of regionSpans) {
    if (consumed.has(span.start)) continue;
    if (ANCHOR_KINDS.has(span.kind)) {
      if (anchorPolicy !== "exact" || sourceAnchors.has(anchorKey(span))) continue;
      recordFailure(failures, "protected_introduced", span.id);
      introduced.push(span.text);
      continue;
    }
    if (span.kind === "name" && !sourceNames.has(normalizeAnchor(span.text))) {
      if (isHeadingLike(regionText, span.start)) continue;
      recordFailure(failures, "protected_introduced", span.id);
      introduced.push(span.text);
    }
  }

  const primary = spans.find((span) => failuresHas(failures, span.id));
  return finalize(failures, introduced, primary);
}

function validateIdentity(
  originalText: string,
  spans: ProtectedSpan[],
  options: ProtectedValidationOptions
): ProtectedSpan | null {
  const sourceSha256 = computeSourceSha256(originalText);
  if (options.sourceSha256 && options.sourceSha256 !== sourceSha256) {
    return spans[0];
  }
  for (const span of spans) {
    if (!isValidUtf16Range(originalText, span)) return span;
    if (originalText.slice(span.start, span.end) !== span.text) return span;
    if (span.rangeEncoding && span.rangeEncoding !== RANGE_ENCODING_VERSION) return span;
    if (span.sourceSha256 && span.sourceSha256 !== sourceSha256) return span;
    if (
      span.protectedSpanSha256 &&
      span.protectedSpanSha256 !==
        computeProtectedSpanSha256(
          span.rangeEncoding ?? RANGE_ENCODING_VERSION,
          sourceSha256,
          span,
          span.text
        )
    ) {
      return span;
    }
  }
  if (options.selection && options.selectionSha256) {
    const selected = originalText.slice(options.selection.start, options.selection.end);
    const expected = computeSelectionSha256(
      RANGE_ENCODING_VERSION,
      sourceSha256,
      options.selection,
      selected
    );
    if (expected !== options.selectionSha256) return spans[0];
  }
  return null;
}

export function validateProtectedContent(
  originalText: string,
  candidateText: string,
  protectedSpans: ProtectedSpan[] = extractProtectedSpans(originalText),
  options: ProtectedValidationOptions = {}
): ProtectionValidation {
  const route = options.route ?? "whole";
  const anchorPolicy = options.anchorPolicy ?? (route === "local" ? "exact" : "minimum");

  const identityFailure = validateIdentity(originalText, protectedSpans, options);
  if (identityFailure) {
    return {
      ...emptyValidation(),
      safe: false,
      failureClass: "identity_mismatch",
      failureSpanIds: [identityFailure.id],
      reason: describe("identity_mismatch", identityFailure),
    };
  }

  return route === "local"
    ? validateLocalRoute(originalText, candidateText, protectedSpans, options, anchorPolicy)
    : validateWholeRoute(originalText, candidateText, protectedSpans, anchorPolicy);
}

export function serializeProtectedSpans(spans: ProtectedSpan[]): string {
  return spans.map((span) => span.text).join(", ");
}

export function hashText(text: string): string {
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

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
  | "list-marker";

export interface ProtectedSpan {
  id: string;
  kind: ProtectedSpanKind;
  text: string;
  start: number;
  end: number;
}

export interface ProtectionValidation {
  safe: boolean;
  reason?: string;
  missing?: ProtectedSpan;
}

interface CandidateSpan {
  kind: ProtectedSpanKind;
  text: string;
  start: number;
  end: number;
  priority: number;
}

const TIME_ZONE = "(?:ET|CT|MT|PT|EST|EDT|CST|CDT|MST|MDT|PST|PDT|UTC|GMT|BST|CET|CEST|EET|EEST|IST|JST|KST|AEST|AEDT|ACST|ACDT|AWST)";
const MONTH = "(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)";
const WEEKDAY = "(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)";
// Include the SI metre symbol `m` explicitly. The number pattern below keeps
// the quantity and unit as one factual anchor, so `5 m` cannot silently turn
// into another length such as `5 ft` while retaining the same numeral.
const MEASUREMENT_UNIT = "(?:kg|mg|mcg|µg|g|oz|lb|lbs|mm|cm|m|km|mL|ml|L|mi|ft|yd|MB|GB|TB|KiB|MiB|GiB|ms|sec|secs|seconds?|min|mins|minutes?|hours?|days?|weeks?|months?|years?|°C|°F|Hz|kHz|MHz|GHz|Mbps|Gbps|tokens?|words?|pages?)";
const NEGATIVE_AUXILIARY = "(?:can|could|do|does|did|have|has|had|is|are|was|were|will|would|should|must|might|shall|need)";

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
    pattern: new RegExp(
      `\\b(?:` +
        `\\d{1,4}[-/]\\d{1,2}[-/]\\d{1,4}` +
        `|${MONTH}\\s+\\d{1,2}(?:st|nd|rd|th)?(?:,?\\s*\\d{4})?` +
        `|\\d{1,2}(?:st|nd|rd|th)?\\s+${MONTH}(?:\\s+\\d{4})?` +
      `)\\b`,
      "gi",
    ),
    priority: 78,
  },
  {
    kind: "date",
    pattern: new RegExp(
      `\\b(?:today|tomorrow|yesterday|tonight|${WEEKDAY}|(?:this|next|last)\\s+(?:morning|afternoon|evening|night|week|month|year|${WEEKDAY}))\\b`,
      "gi",
    ),
    priority: 78,
  },
  // Treat semantic versions as one protected number. Protecting only each
  // decimal component lets sentence repair split `2.4.1` at its periods.
  {
    kind: "number",
    pattern: /\b\d+(?:\.\d+){2,}(?:[-+][A-Za-z0-9.-]+)?\b/gi,
    priority: 74,
  },
  // Protect the whole clock expression, including meridiem and timezone when
  // present. The older pattern handled `15:30` and `3:30 PM` but protected
  // only the number in common pasted forms such as `6pm PST`, allowing a
  // rewrite to silently lose or change PM/PST while still passing anchors.
  {
    kind: "time",
    pattern: new RegExp(
      `\\b(?:` +
        `\\d{1,2}(?::\\d{2})?\\s?(?:A\\.?M\\.?|P\\.?M\\.?)(?:\\s*${TIME_ZONE})?` +
        `|\\d{1,2}:\\d{2}(?:\\s*${TIME_ZONE})?` +
        `|\\d{1,2}(?::\\d{2})?\\s+${TIME_ZONE}` +
        `|(?:noon|midnight)(?:\\s+${TIME_ZONE})?` +
      `)(?=\\s|$|[),.;:!?])`,
      "gi",
    ),
    priority: 78,
  },
  {
    kind: "number",
    pattern: new RegExp(`\\b\\d[\\d,]*(?:\\.\\d+)?(?:\\s?${MEASUREMENT_UNIT})?\\b`, "gi"),
    priority: 72,
  },
  { kind: "list-marker", pattern: /^\s*(?:[-*•]|\d+[.)])(?=\s)/gm, priority: 70 },
  {
    kind: "negation",
    // Consume expanded auxiliary+not as one semantic anchor so harmless
    // contraction/expansion edits can be compared as equivalents.
    pattern: new RegExp(
      `\\b(?:failed\\s+to|fails\\s+to|${NEGATIVE_AUXILIARY}\\s+not|not|never|no|without|cannot|can['’]t|couldn['’]t|don['’]t|doesn['’]t|didn['’]t|haven['’]t|hasn['’]t|hadn['’]t|won['’]t|wouldn['’]t|shouldn['’]t|mustn['’]t|mightn['’]t|shan['’]t|needn['’]t|isn['’]t|aren['’]t|wasn['’]t|weren['’]t|hardly|rarely|seldom|invalid|unacceptable|impossible)\\b`,
      "gi",
    ),
    priority: 65,
  },
  {
    kind: "modality",
    pattern: /\b(?:may|might|could|can|must|should|will|would|shall)\b/gi,
    priority: 64,
  },
];

function isSentenceStart(text: string, index: number): boolean {
  const before = text.slice(0, index).trimEnd();
  if (!before) return true;
  return /[.!?]$/.test(before);
}

function collectCandidates(text: string): CandidateSpan[] {
  const candidates: CandidateSpan[] = [];

  for (const { kind, pattern, priority } of PROTECTED_PATTERNS) {
    pattern.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(text)) !== null) {
      // Sentence punctuation is not part of a URL. Keeping a trailing period
      // in the protected payload makes the validator reject an unchanged URL
      // whenever it appears at the end of a sentence.
      const candidateText = kind === "url" ? match[0].replace(/[.,!?;:]+$/g, "") : match[0];
      candidates.push({
        kind,
        text: candidateText,
        start: match.index,
        end: match.index + candidateText.length,
        priority,
      });
    }
  }

  const namePattern = /\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})+\b/g;
  let nameMatch: RegExpExecArray | null;
  while ((nameMatch = namePattern.exec(text)) !== null) {
    candidates.push({
      kind: "name",
      text: nameMatch[0],
      start: nameMatch.index,
      end: nameMatch.index + nameMatch[0].length,
      priority: 75,
    });
  }

  // Preserve high-signal technical/proper tokens regardless of sentence
  // position: acronyms, mixed-case brands, and letter+digit model names.
  const technicalNamePattern = /\b(?:[A-Z]{2,}[A-Z0-9-]*|[A-Z][a-z]+[A-Z][A-Za-z0-9-]*|[A-Z][A-Za-z-]*\d[A-Za-z0-9-]*)\b/g;
  let technicalNameMatch: RegExpExecArray | null;
  while ((technicalNameMatch = technicalNamePattern.exec(text)) !== null) {
    candidates.push({
      kind: "name",
      text: technicalNameMatch[0],
      start: technicalNameMatch.index,
      end: technicalNameMatch.index + technicalNameMatch[0].length,
      priority: 76,
    });
  }

  // A sentence-internal capitalized word is a useful conservative signal for
  // a single-token proper name, product, place, weekday, or titled entity
  // (for example `Maya`, `Grammarly`, or `Monday`). Protecting it may reduce a
  // little rewrite freedom, but losing one of these anchors is much costlier.
  // Sentence-start capitalization stays unclassified to avoid treating every
  // ordinary first word as a name.
  const singleInternalNamePattern = /\b[A-Z][a-z]{2,}\b/g;
  let singleInternalNameMatch: RegExpExecArray | null;
  while ((singleInternalNameMatch = singleInternalNamePattern.exec(text)) !== null) {
    if (isSentenceStart(text, singleInternalNameMatch.index)) continue;
    candidates.push({
      kind: "name",
      text: singleInternalNameMatch[0],
      start: singleInternalNameMatch.index,
      end: singleInternalNameMatch.index + singleInternalNameMatch[0].length,
      priority: 73,
    });
  }

  // A single capitalized word is ambiguous at sentence start. Keep it
  // protected when an honorific makes the name context explicit.
  const honorificNamePattern = /\b(?:Dr|Mr|Ms|Mrs|Prof|Professor)\.?\s+([A-Z][a-z]{2,})\b/g;
  let honorificNameMatch: RegExpExecArray | null;
  while ((honorificNameMatch = honorificNamePattern.exec(text)) !== null) {
    const name = honorificNameMatch[1];
    const nameStart = honorificNameMatch.index + honorificNameMatch[0].lastIndexOf(name);
    const nameEnd = nameStart + name.length;
    if (/^\s+[A-Z][a-z]{2,}\b/.test(text.slice(nameEnd))) continue;
    candidates.push({
      kind: "name",
      text: name,
      start: nameStart,
      end: nameEnd,
      priority: 74,
    });
  }

  return candidates;
}

export function extractProtectedSpans(text: string): ProtectedSpan[] {
  const selected: CandidateSpan[] = [];

  for (const candidate of collectCandidates(text).sort((left, right) => {
    if (left.start !== right.start) return left.start - right.start;
    if (left.priority !== right.priority) return right.priority - left.priority;
    return right.end - left.end;
  })) {
    // Negative modal contractions/expansions already preserve their modal
    // carrier as part of the higher-priority negation span. Keeping an
    // overlapping `can`/`could` span would make `can't` -> `cannot` fail exact
    // matching even though the semantic anchor is unchanged.
    if (
      candidate.kind === "modality" &&
      selected.some((existing) =>
        existing.kind === "negation" &&
        existing.start <= candidate.start &&
        existing.end >= candidate.end
      )
    ) {
      continue;
    }

    const duplicate = selected.some(
      (existing) =>
        existing.kind === candidate.kind &&
        existing.start === candidate.start &&
        existing.end === candidate.end
    );
    if (!duplicate) selected.push(candidate);
  }

  return selected
    .sort((left, right) => left.start - right.start)
    .map((span, index) => ({
      id: `protected-${index}-${span.start}`,
      kind: span.kind,
      text: span.text,
      start: span.start,
      end: span.end,
    }));
}

function countExact(text: string, fragment: string): number {
  if (!fragment) return 0;
  let count = 0;
  let cursor = 0;
  while (cursor < text.length) {
    const index = text.indexOf(fragment, cursor);
    if (index < 0) break;
    count += 1;
    cursor = index + Math.max(1, fragment.length);
  }
  return count;
}

function countCaseInsensitive(text: string, fragment: string): number {
  if (!fragment) return 0;
  const pattern = new RegExp(fragment.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
  return [...text.matchAll(pattern)].length;
}

function canonicalNegationPattern(fragment: string): RegExp | null {
  const normalized = fragment.toLowerCase().replace(/’/g, "'").replace(/\s+/g, " ").trim();
  const forms: Record<string, string> = {
    "cannot": "(?:cannot|can\\s+not|can['’]t)",
    "can not": "(?:cannot|can\\s+not|can['’]t)",
    "can't": "(?:cannot|can\\s+not|can['’]t)",
    "could not": "(?:could\\s+not|couldn['’]t)",
    "couldn't": "(?:could\\s+not|couldn['’]t)",
    "do not": "(?:do\\s+not|don['’]t)",
    "don't": "(?:do\\s+not|don['’]t)",
    "does not": "(?:does\\s+not|doesn['’]t)",
    "doesn't": "(?:does\\s+not|doesn['’]t)",
    "did not": "(?:did\\s+not|didn['’]t)",
    "didn't": "(?:did\\s+not|didn['’]t)",
    "have not": "(?:have\\s+not|haven['’]t)",
    "haven't": "(?:have\\s+not|haven['’]t)",
    "has not": "(?:has\\s+not|hasn['’]t)",
    "hasn't": "(?:has\\s+not|hasn['’]t)",
    "had not": "(?:had\\s+not|hadn['’]t)",
    "hadn't": "(?:had\\s+not|hadn['’]t)",
    "is not": "(?:is\\s+not|isn['’]t)",
    "isn't": "(?:is\\s+not|isn['’]t)",
    "are not": "(?:are\\s+not|aren['’]t)",
    "aren't": "(?:are\\s+not|aren['’]t)",
    "was not": "(?:was\\s+not|wasn['’]t)",
    "wasn't": "(?:was\\s+not|wasn['’]t)",
    "were not": "(?:were\\s+not|weren['’]t)",
    "weren't": "(?:were\\s+not|weren['’]t)",
    "will not": "(?:will\\s+not|won['’]t)",
    "won't": "(?:will\\s+not|won['’]t)",
    "would not": "(?:would\\s+not|wouldn['’]t)",
    "wouldn't": "(?:would\\s+not|wouldn['’]t)",
    "should not": "(?:should\\s+not|shouldn['’]t)",
    "shouldn't": "(?:should\\s+not|shouldn['’]t)",
    "must not": "(?:must\\s+not|mustn['’]t)",
    "mustn't": "(?:must\\s+not|mustn['’]t)",
    "might not": "(?:might\\s+not|mightn['’]t)",
    "mightn't": "(?:might\\s+not|mightn['’]t)",
    "shall not": "(?:shall\\s+not|shan['’]t)",
    "shan't": "(?:shall\\s+not|shan['’]t)",
    "need not": "(?:need\\s+not|needn['’]t)",
    "needn't": "(?:need\\s+not|needn['’]t)",
  };
  const source = forms[normalized];
  return source ? new RegExp(`\\b${source}\\b`, "gi") : null;
}

function countEquivalentNegation(text: string, fragment: string): number {
  const pattern = canonicalNegationPattern(fragment);
  if (!pattern) return countCaseInsensitive(text, fragment);
  return [...text.matchAll(pattern)].length;
}

function uniqueTexts(spans: ProtectedSpan[]): string[] {
  return [...new Set(spans.map((span) => span.text))];
}

const FACTUAL_ADDITION_KINDS = new Set<ProtectedSpanKind>([
  "date", "time", "number", "percentage", "currency",
]);

function spanCountKey(span: Pick<ProtectedSpan, "kind" | "text">): string {
  return `${span.kind}\u0000${span.text}`;
}

function hasUnsupportedProtectedAddition(original: string, candidate: string): ProtectedSpan | null {
  const originalSpans = extractProtectedSpans(original);
  const candidateSpans = extractProtectedSpans(candidate);
  const originalNames = new Set(
    originalSpans.filter((span) => span.kind === "name").map((span) => span.text)
  );

  const addedName = candidateSpans.find(
    (span) => span.kind === "name" && !originalNames.has(span.text)
  );
  if (addedName) return addedName;

  const originalCounts = new Map<string, number>();
  for (const span of originalSpans) {
    if (!FACTUAL_ADDITION_KINDS.has(span.kind)) continue;
    const key = spanCountKey(span);
    originalCounts.set(key, (originalCounts.get(key) ?? 0) + 1);
  }
  const seenCandidateCounts = new Map<string, number>();
  for (const span of candidateSpans) {
    if (!FACTUAL_ADDITION_KINDS.has(span.kind)) continue;
    const key = spanCountKey(span);
    const next = (seenCandidateCounts.get(key) ?? 0) + 1;
    seenCandidateCounts.set(key, next);
    if (next > (originalCounts.get(key) ?? 0)) return span;
  }
  return null;
}

export function validateProtectedContent(
  originalText: string,
  candidateText: string,
  protectedSpans: ProtectedSpan[] = extractProtectedSpans(originalText)
): ProtectionValidation {
  for (const text of uniqueTexts(protectedSpans)) {
    const matchingSpans = protectedSpans.filter((span) => span.text === text);
    const expected = matchingSpans.length;
    const actual = countExact(candidateText, text);
    const equivalentNegation = matchingSpans.every((span) => span.kind === "negation") &&
      countEquivalentNegation(candidateText, text) >= expected;
    if (actual < expected && !equivalentNegation) {
      const missing = protectedSpans.find((span) => span.text === text);
      return {
        safe: false,
        reason: `Protected ${missing?.kind ?? "content"} was changed or removed: “${text}”`,
        missing,
      };
    }
  }

  const unsupported = hasUnsupportedProtectedAddition(originalText, candidateText);
  if (unsupported) {
    return {
      safe: false,
      reason: unsupported.kind === "name"
        ? `The rewrite introduced an unsupported name: “${unsupported.text}”`
        : `The rewrite introduced an unsupported ${unsupported.kind}: “${unsupported.text}”`,
    };
  }

  return { safe: true };
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

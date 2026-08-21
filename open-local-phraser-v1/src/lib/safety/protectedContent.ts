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
    pattern: /\b(?:\d{1,4}[-/]\d{1,2}[-/]\d{1,4}|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:,\s*\d{4})?)\b/gi,
    priority: 78,
  },
  { kind: "time", pattern: /\b\d{1,2}:\d{2}(?:\s?[AP]M)?\b/gi, priority: 78 },
  {
    kind: "number",
    pattern: /\b\d[\d,]*(?:\.\d+)?(?:\s?(?:kg|g|lb|lbs|km|mi|MB|GB|ms|s|hours?|minutes?|years?))?\b/gi,
    priority: 72,
  },
  { kind: "list-marker", pattern: /^\s*(?:[-*•]|\d+[.)])(?=\s)/gm, priority: 70 },
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
];

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

  // A single capitalized word is ambiguous in headings and sentence-internal
  // titles (for example, the word “Can” in a question-style heading). Keep
  // it protected when an honorific makes the name context explicit, while
  // leaving ordinary title words available to the rewriter.
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

function uniqueTexts(spans: ProtectedSpan[]): string[] {
  return [...new Set(spans.map((span) => span.text))];
}

function hasUnsupportedProtectedAddition(original: string, candidate: string): string | null {
  const originalSpans = extractProtectedSpans(original);
  const candidateSpans = extractProtectedSpans(candidate);
  const originalNames = new Set(
    originalSpans.filter((span) => span.kind === "name").map((span) => span.text)
  );

  const addedName = candidateSpans.find(
    (span) => span.kind === "name" && !originalNames.has(span.text)
  );
  return addedName?.text ?? null;
}

export function validateProtectedContent(
  originalText: string,
  candidateText: string,
  protectedSpans: ProtectedSpan[] = extractProtectedSpans(originalText)
): ProtectionValidation {
  for (const text of uniqueTexts(protectedSpans)) {
    const expected = protectedSpans.filter((span) => span.text === text).length;
    const actual = countExact(candidateText, text);
    if (actual < expected) {
      const missing = protectedSpans.find((span) => span.text === text);
      return {
        safe: false,
        reason: `Protected ${missing?.kind ?? "content"} was changed or removed: “${text}”`,
        missing,
      };
    }
  }

  const unsupportedName = hasUnsupportedProtectedAddition(originalText, candidateText);
  if (unsupportedName) {
    return {
      safe: false,
      reason: `The rewrite introduced an unsupported name: “${unsupportedName}”`,
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

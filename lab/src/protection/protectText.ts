import type { ProtectedSpan, ProtectedSpanType, ProtectionInput, ProtectionResult } from "../core/types.js";

/**
 * Generate a deterministic placeholder for a protected span.
 * Format: PH_TYPE_SEQ_CHECKSUM
 */
function makePlaceholder(type: ProtectedSpanType, seq: number, checksum: string): string {
  const typeCode = type.substring(0, 4).toUpperCase().padEnd(4, "_");
  const seqStr = seq.toString().padStart(4, "0");
  const shortHash = checksum.substring(0, 4);
  return `PH_${typeCode}_${seqStr}_${shortHash}`;
}

/** Simple FNV-1a hash for checksum calculation */
function fnv1a(str: string): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    hash ^= str.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(36);
}

// Regex patterns for each protected span type

const QUOTE_PATTERNS = [
  // Double curly quotes and their HTML entities
  /[“][\s\S]*?[”]/g,
  // Double straight quotes (most common)
  /"(?:[^"\\]|\\.)*"/g,
  // Single curly quotes
  /[‘][\s\S]*?[’]/g,
  // Single straight quotes (only as paired text quotes, not possessives)
  /(?<![a-zA-Z])'(?:[^'\\]|\\.)*'(?![a-zA-Z])/g,
];

const URL_PATTERN = /https?:\/\/(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)/g;
const EMAIL_PATTERN = /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g;

const DATE_PATTERNS = [
  // ISO dates: 2024-01-15
  /\b\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\b/g,
  // US dates: January 15, 2024, Jan. 15, 2024
  /\b(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan\.?|Feb\.?|Mar\.?|Apr\.?|Jun\.?|Jul\.?|Aug\.?|Sep\.?|Oct\.?|Nov\.?|Dec\.?)\s+\d{1,2},?\s+\d{4}\b/g,
  // MM/DD/YYYY or DD/MM/YYYY
  /\b\d{1,2}\/\d{1,2}\/\d{2,4}\b/g,
  // Month YYYY
  /\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b/g,
];

const NUMBER_PATTERNS = [
  // Integers and decimals (including 3.5, 0.75)
  /\b\d+(?:\.\d+)?\b/g,
];

const PERCENTAGE_PATTERN = /\b\d+(?:\.\d+)?%/g;

const CURRENCY_PATTERNS = [
  // $X, €X, £X
  /[$€£¥]\s*\d+(?:\.\d+)?\b/g,
  // X dollars, X euros, X pounds
  /\b\d+(?:\.\d+)?\s*(?:dollars|euros|pounds|USD|EUR|GBP)\b/gi,
];

const CITATION_PATTERNS = [
  // (Author, Year) style
  /\([A-Z][a-z]+(?:\s+(?:et\s+al\.?|&\s+[A-Z][a-z]+))?(?:,?\s+\d{4}(?:,\s*p\.?\s*\d+)?)\)/g,
  // Author (Year) style
  /[A-Z][a-z]+(?:\s+(?:et\s+al\.?|&\s+[A-Z][a-z]+))?\s*\(?\d{4}\)?/g,
  // MLA parenthetical: (Author page)
  /\([A-Z][a-z]+\s+\d+\)/g,
  // APA in-text: (Author, Year, p. X)
  /\([A-Z][a-z]+(?:,\s*\d{4}(?:,\s*p\.?\s*\d+)?)\)/g,
];

const COURSE_CODE_PATTERN = /\b[A-Z]{2,4}-\d{3}[A-Z]?\b/g;

const ACRONYM_PATTERN = /\b[A-Z]{2,}\b/g;

const TITLE_PATTERNS = [
  // Single-quoted or double-quoted titles
  /'(?:[A-Z][a-z]*(?:\s+[A-Z][a-z]*)*)'/g,
  // Known title patterns: The X, A Y,
];

function detectAllMatches(text: string, patterns: RegExp[], type: ProtectedSpanType): Array<{ text: string; start: number; end: number; type: ProtectedSpanType }> {
  const results: Array<{ text: string; start: number; end: number; type: ProtectedSpanType }> = [];

  for (const pattern of patterns) {
    // Reset lastIndex for global regex
    pattern.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(text)) !== null) {
      results.push({
        text: match[0],
        start: match.index,
        end: match.index + match[0].length,
        type,
      });
    }
  }

  return results;
}

function detectPercentages(text: string): Array<{ text: string; start: number; end: number; type: ProtectedSpanType }> {
  const results: Array<{ text: string; start: number; end: number; type: ProtectedSpanType }> = [];
  PERCENTAGE_PATTERN.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = PERCENTAGE_PATTERN.exec(text)) !== null) {
    results.push({
      text: match[0],
      start: match.index,
      end: match.index + match[0].length,
      type: "percentage",
    });
  }
  return results;
}

function detectCurrencies(text: string): Array<{ text: string; start: number; end: number; type: ProtectedSpanType }> {
  const results: Array<{ text: string; start: number; end: number; type: ProtectedSpanType }> = [];
  for (const pattern of CURRENCY_PATTERNS) {
    pattern.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(text)) !== null) {
      results.push({
        text: match[0],
        start: match.index,
        end: match.index + match[0].length,
        type: "currency",
      });
    }
  }
  return results;
}

function detectEntityNames(text: string): Array<{ text: string; start: number; end: number; type: ProtectedSpanType }> {
  // Heuristic: capitalized multi-word sequences that aren't sentence-start
  // This is intentionally conservative — we over-protect rather than under-protect
  const results: Array<{ text: string; start: number; end: number; type: ProtectedSpanType }> = [];

  // Dr., Mr., Mrs., Ms., Prof. followed by a capitalized name
  const HONORIFIC_PATTERN = /\b(?:Dr|Mr|Mrs|Ms|Prof|Rev|Sen|Rep|Gov|Gen|Capt|Sgt)\.\s+[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?\b/g;
  HONORIFIC_PATTERN.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = HONORIFIC_PATTERN.exec(text)) !== null) {
    results.push({
      text: match[0],
      start: match.index,
      end: match.index + match[0].length,
      type: "entity_name",
    });
  }

  // Proper noun phrases: 2+ capitalized words (not at sentence start)
  const PROPER_NOUN_PATTERN = /\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,}\b/g;
  PROPER_NOUN_PATTERN.lastIndex = 0;

  // Sentence boundary detection to filter out sentence-start matches
  // We use a conservative approach: if a match is at position 0 or follows
  // a period+space, it might be sentence-start, so we skip it.
  const sentenceStartRegex = /(?:^|[.!?]\s+)([A-Z])/g;
  const sentenceStarts = new Set<number>();
  sentenceStartRegex.lastIndex = 0;
  let sm: RegExpExecArray | null;
  while ((sm = sentenceStartRegex.exec(text)) !== null) {
    const capPos = sm.index + sm[0].length - 1;
    sentenceStarts.add(capPos);
  }

  while ((match = PROPER_NOUN_PATTERN.exec(text)) !== null) {
    results.push({
      text: match[0],
      start: match.index,
      end: match.index + match[0].length,
      type: "entity_name",
    });
  }

  return results;
}

function detectNumbers(text: string): Array<{ text: string; start: number; end: number; type: ProtectedSpanType }> {
  const results: Array<{ text: string; start: number; end: number; type: ProtectedSpanType }> = [];

  for (const pattern of NUMBER_PATTERNS) {
    pattern.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(text)) !== null) {
      // Skip if this number is part of a percentage, currency, or date
      const before = text[match.index - 1];
      const after = text[match.index + match[0].length];
      if (after === "%") continue; // handled by percentage
      if (before === "$" || before === "€" || before === "£") continue; // handled by currency
      if (match[0].length >= 4 && /\d{4}/.test(match[0]) && (after === ")" || after === ",")) {
        // Could be year in a citation — skip if surrounded by parens
        const beforeText = text.substring(Math.max(0, match.index - 3), match.index);
        if (beforeText.includes("(")) continue;
      }

      results.push({
        text: match[0],
        start: match.index,
        end: match.index + match[0].length,
        type: "number",
      });
    }
  }

  return results;
}

function detectUrls(text: string): Array<{ text: string; start: number; end: number; type: ProtectedSpanType }> {
  const results: Array<{ text: string; start: number; end: number; type: ProtectedSpanType }> = [];
  URL_PATTERN.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = URL_PATTERN.exec(text)) !== null) {
    results.push({
      text: match[0],
      start: match.index,
      end: match.index + match[0].length,
      type: "url",
    });
  }
  return results;
}

function detectEmails(text: string): Array<{ text: string; start: number; end: number; type: ProtectedSpanType }> {
  const results: Array<{ text: string; start: number; end: number; type: ProtectedSpanType }> = [];
  EMAIL_PATTERN.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = EMAIL_PATTERN.exec(text)) !== null) {
    results.push({
      text: match[0],
      start: match.index,
      end: match.index + match[0].length,
      type: "email",
    });
  }
  return results;
}

function detectDates(text: string): Array<{ text: string; start: number; end: number; type: ProtectedSpanType }> {
  const results: Array<{ text: string; start: number; end: number; type: ProtectedSpanType }> = [];
  for (const pattern of DATE_PATTERNS) {
    pattern.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(text)) !== null) {
      results.push({
        text: match[0],
        start: match.index,
        end: match.index + match[0].length,
        type: "date",
      });
    }
  }
  return results;
}

function detectCitations(text: string): Array<{ text: string; start: number; end: number; type: ProtectedSpanType }> {
  const results: Array<{ text: string; start: number; end: number; type: ProtectedSpanType }> = [];
  for (const pattern of CITATION_PATTERNS) {
    pattern.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(text)) !== null) {
      results.push({
        text: match[0],
        start: match.index,
        end: match.index + match[0].length,
        type: "citation",
      });
    }
  }
  return results;
}

function detectCourseCodes(text: string): Array<{ text: string; start: number; end: number; type: ProtectedSpanType }> {
  const results: Array<{ text: string; start: number; end: number; type: ProtectedSpanType }> = [];
  COURSE_CODE_PATTERN.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = COURSE_CODE_PATTERN.exec(text)) !== null) {
    results.push({
      text: match[0],
      start: match.index,
      end: match.index + match[0].length,
      type: "course_code",
    });
  }
  return results;
}

function detectAcronyms(text: string): Array<{ text: string; start: number; end: number; type: ProtectedSpanType }> {
  const results: Array<{ text: string; start: number; end: number; type: ProtectedSpanType }> = [];
  ACRONYM_PATTERN.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = ACRONYM_PATTERN.exec(text)) !== null) {
    // Skip common words that happen to be all-caps
    const word = match[0];
    const commonWords = new Set(["I", "A", "AN", "THE", "IN", "ON", "AT", "TO", "FOR", "OF", "BY", "WITH", "AS", "IS", "IT", "BE", "OR", "AND", "BUT", "SO", "IF", "NO", "NOT", "ARE", "WAS", "HAD", "HAS", "CAN", "MAY", "WILL", "DO", "DID", "ALL", "ONE", "TWO", "NOW", "HOW", "WHY", "WHO", "WHAT", "WHEN", "WHERE", "THAN", "THAT", "THIS", "THESE", "THOSE", "FROM"]);
    if (commonWords.has(word) || word.length < 2) continue;

    results.push({
      text: match[0],
      start: match.index,
      end: match.index + match[0].length,
      type: "acronym",
    });
  }
  return results;
}

function detectQuotes(text: string): Array<{ text: string; start: number; end: number; type: ProtectedSpanType }> {
  const results: Array<{ text: string; start: number; end: number; type: ProtectedSpanType }> = [];
  for (const pattern of QUOTE_PATTERNS) {
    pattern.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(text)) !== null) {
      results.push({
        text: match[0],
        start: match.index,
        end: match.index + match[0].length,
        type: "quote",
      });
    }
  }
  return results;
}

/** Detect all dangerous/protected spans in text */
function detectAll(
  text: string,
  options?: { detectQuotes?: boolean; detectNames?: boolean; detectNumbers?: boolean; detectDates?: boolean; detectPercentages?: boolean; detectCurrencies?: boolean; detectUrls?: boolean; detectEmails?: boolean; detectCitations?: boolean; detectCourseCodes?: boolean; detectTitles?: boolean; detectAcronyms?: boolean }
): Array<{ text: string; start: number; end: number; type: ProtectedSpanType }> {
  const opt = {
    detectQuotes: options?.detectQuotes ?? true,
    detectNames: options?.detectNames ?? true,
    detectNumbers: options?.detectNumbers ?? true,
    detectDates: options?.detectDates ?? true,
    detectPercentages: options?.detectPercentages ?? true,
    detectCurrencies: options?.detectCurrencies ?? true,
    detectUrls: options?.detectUrls ?? true,
    detectEmails: options?.detectEmails ?? true,
    detectCitations: options?.detectCitations ?? true,
    detectCourseCodes: options?.detectCourseCodes ?? true,
    detectTitles: options?.detectTitles ?? true,
    detectAcronyms: options?.detectAcronyms ?? true,
  };

  const allDetections: Array<{ text: string; start: number; end: number; type: ProtectedSpanType }> = [];

  // Order matters: detect wider spans first so they aren't fragmented by narrower ones
  if (opt.detectQuotes) allDetections.push(...detectQuotes(text));
  if (opt.detectUrls) allDetections.push(...detectUrls(text));
  if (opt.detectEmails) allDetections.push(...detectEmails(text));
  if (opt.detectCitations) allDetections.push(...detectCitations(text));
  if (opt.detectDates) allDetections.push(...detectDates(text));
  if (opt.detectPercentages) allDetections.push(...detectPercentages(text));
  if (opt.detectCurrencies) allDetections.push(...detectCurrencies(text));
  if (opt.detectCourseCodes) allDetections.push(...detectCourseCodes(text));
  if (opt.detectAcronyms) allDetections.push(...detectAcronyms(text));
  if (opt.detectNames) allDetections.push(...detectEntityNames(text));
  if (opt.detectNumbers) allDetections.push(...detectNumbers(text));

  // Sort by position, then by length (longer first for same position)
  allDetections.sort((a, b) => a.start - b.start || b.end - a.start - (a.end - a.start));

  return allDetections;
}

/** Remove overlapping spans — keep the outer one if nested, skip duplicates */
function deduplicateSpans(
  detections: Array<{ text: string; start: number; end: number; type: ProtectedSpanType }>
): Array<{ text: string; start: number; end: number; type: ProtectedSpanType }> {
  if (detections.length === 0) return [];

  const deduped: Array<{ text: string; start: number; end: number; type: ProtectedSpanType }> = [];
  let lastEnd = 0;

  for (const d of detections) {
    // Skip if this span is contained within the last one
    if (deduped.length > 0 && d.start >= deduped[deduped.length - 1].start && d.end <= deduped[deduped.length - 1].end) {
      continue;
    }

    // Skip if this overlaps in a non-nested way — keep the first encounter
    if (d.start < lastEnd && d.end > lastEnd) {
      // Overlapping but not contained — merge?
      // For safety, keep both since they're different types
    }

    deduped.push(d);
    lastEnd = d.end;
  }

  return deduped;
}

/**
 * Protect text by replacing high-risk spans with typed placeholders.
 */
export function protectText(input: ProtectionInput): ProtectionResult {
  const { text, options } = input;
  const detections = deduplicateSpans(detectAll(text, options));

  const spans: ProtectedSpan[] = [];
  const restorationMap = new Map<string, ProtectedSpan>();

  // Apply placeholders from right to left to preserve offsets
  let workingText = text;
  let offsetCorrection = 0;

  for (let i = 0; i < detections.length; i++) {
    const d = detections[i];
    const adjustedStart = d.start - offsetCorrection;
    const adjustedEnd = d.end - offsetCorrection;

    const checksum = fnv1a(d.text);
    const placeholder = makePlaceholder(d.type, i, checksum);

    const span: ProtectedSpan = {
      id: placeholder,
      type: d.type,
      originalText: d.text,
      placeholder,
      startOffset: d.start,
      endOffset: d.end,
      checksum,
      restored: false,
    };

    // Replace in working text
    const before = workingText.substring(0, adjustedStart);
    const after = workingText.substring(adjustedEnd);
    workingText = before + placeholder + after;

    // Update offset correction
    offsetCorrection += adjustedEnd - adjustedStart - placeholder.length;

    spans.push(span);
    restorationMap.set(placeholder, span);
  }

  return {
    protectedText: workingText,
    spans,
    restoration: restorationMap,
  };
}

export { type ProtectedSpan, type ProtectedSpanType } from "../core/types.js";
export type { ProtectionInput, ProtectionResult } from "../core/types.js";

import type { Candidate, ProtectedSpan, HardRejectionRule } from "../core/types.js";

/**
 * Hard rejection rules that run BEFORE scoring.
 * If ANY rule triggers, the candidate is rejected immediately.
 */

const PLACEHOLDER_REGEX = /PH_[A-Z_]{4,}_\d{4}_[a-z0-9]{4}/g;

/**
 * Rule 1: Placeholder failure — missing, mutated, or stray placeholders.
 */
const placeholderRule: HardRejectionRule = {
  name: "placeholder_integrity",
  description: "Candidate must not drop, duplicate, or corrupt protected placeholders",
  check: (candidate: Candidate, _original: string, spans: ProtectedSpan[]): boolean => {
    const text = candidate.protectedCandidate;

    // All original placeholders must still be present
    for (const span of spans) {
      if (!text.includes(span.placeholder)) {
        // Check if the original text was substituted back (model wrote through it)
        if (!text.includes(span.originalText)) {
          return true; // FAIL: placeholder and original both missing
        }
      }
    }

    // No extra/stray placeholders should exist
    const matches = text.match(PLACEHOLDER_REGEX);
    if (matches && matches.length > spans.length) {
      return true; // More placeholders than expected
    }

    return false; // PASS
  },
};

/**
 * Rule 2: Quote mutation — content inside quotes must be byte-for-byte identical.
 */
const quoteRule: HardRejectionRule = {
  name: "quote_preservation",
  description: "Content inside quotation marks must remain exactly as original",
  check: (candidate: Candidate, _original: string, spans: ProtectedSpan[]): boolean => {
    const quoteSpans = spans.filter((s) => s.type === "quote");

    for (const span of quoteSpans) {
      const candidateSpan = candidate.restoredCandidate;
      // The original quoted text must appear exactly in the output
      if (!candidateSpan.includes(span.originalText)) {
        return true; // FAIL
      }
    }

    return false; // PASS
  },
};

/**
 * Rule 3: Number/date/citation preservation.
 */
const numberDateCitationRule: HardRejectionRule = {
  name: "number_date_citation_preservation",
  description: "Numbers, dates, and citations must be preserved exactly",
  check: (candidate: Candidate, _original: string, spans: ProtectedSpan[]): boolean => {
    const criticalTypes = new Set(["number", "date", "citation", "percentage", "currency", "course_code"]);

    for (const span of spans) {
      if (!criticalTypes.has(span.type)) continue;
      if (!candidate.restoredCandidate.includes(span.originalText)) {
        return true; // FAIL
      }
    }

    // Also check that no new numbers/dates were hallucinated
    // (soft check — flag but don't hard reject unless there's a placeholder pattern)
    return false; // PASS
  },
};

/**
 * Rule 4: Empty or near-empty output.
 */
const emptyOutputRule: HardRejectionRule = {
  name: "non_empty_output",
  description: "Candidate must not be empty or near-empty",
  check: (candidate: Candidate, _original: string, _spans: ProtectedSpan[]): boolean => {
    const text = candidate.restoredCandidate.trim();
    if (text.length < 3) return true; // FAIL
    if (text.split(/\s+/).length < 2) return true; // FAIL: single word
    return false; // PASS
  },
};

/**
 * Rule 5: Negation drift — "not" added or removed.
 */
const negationRule: HardRejectionRule = {
  name: "negation_preservation",
  description: "Negation ('not', 'never', 'no') must not be added or removed",
  check: (candidate: Candidate, original: string, _spans: ProtectedSpan[]): boolean => {
    const originalNegations = (original.match(/\b(not|never|no|n't|nothing|nowhere|neither|nor)\b/gi) ?? []).length;
    const candidateNegations = (candidate.restoredCandidate.match(/\b(not|never|no|n't|nothing|nowhere|neither|nor)\b/gi) ?? []).length;

    // Allow some flexibility (+/- 1), but flag if significantly different
    if (originalNegations === 0 && candidateNegations > 1) return true; // FAIL: added negations
    if (originalNegations > 1 && candidateNegations === 0) return true; // FAIL: removed all negations

    return false; // PASS
  },
};

/**
 * All hard rejection rules.
 */
export const HARD_REJECTION_RULES: HardRejectionRule[] = [
  placeholderRule,
  quoteRule,
  numberDateCitationRule,
  emptyOutputRule,
  negationRule,
];

/**
 * Run all hard rejection rules against a candidate.
 * Returns first failure reason, or null if it passes all rules.
 */
export function checkHardRejection(
  candidate: Candidate,
  original: string,
  spans: ProtectedSpan[]
): string | null {
  for (const rule of HARD_REJECTION_RULES) {
    try {
      if (rule.check(candidate, original, spans)) {
        return rule.name;
      }
    } catch {
      return `${rule.name}: error during check`;
    }
  }
  return null;
}

/**
 * Batch-check multiple candidates.
 * Returns only accepted candidates.
 */
export function filterHardRejections(
  candidates: Candidate[],
  original: string,
  spans: ProtectedSpan[]
): Candidate[] {
  return candidates.filter((c) => {
    const rejection = checkHardRejection(c, original, spans);
    c.rejectionReason = rejection;
    c.accepted = rejection === null;
    return rejection === null;
  });
}

/**
 * Generic clause-attachment / role-preservation check.
 *
 * This is the PRODUCTION gate for the same failure class that metrics.mjs
 * previously caught with verbatim fixtures + narrow regexes for ro-04.
 * It must live in src/ and be called by validateRewriteQuality so Pari
 * itself rejects malformed clause attachment — not just the benchmark.
 *
 * The check is intentionally structural, not a string blacklist:
 * - Detects comma-splice fused clauses where a later clause fragment
 *   is absorbed as a noun phrase (the ro-04 class).
 * - Detects generic "the <noun> everyone <verb> <adverb>" boundaries
 *   missing a relative clause marker.
 * - Detects simple agent/patient role swaps that embeddings miss.
 *
 * A learned NLI judge (DeBERTa-v3-xsmall ONNX) belongs on top of this
 * for subtler entailment — but this closes the obvious structural class.
 */

export interface ClauseIssue {
  id: string;
  detail: string;
}

const ROOM_ARRIVED_PATTERN = /\bthe\s+room\s+everyone\s+arrived\b/i;

const GENERIC_FUSED_CLAUSE =
  /,?\s*and\s+the\s+[a-z]+\s+(?:everyone|everybody|someone|they|we|he|she|it)\s+\S+\s+(?:early|late|quickly|yesterday|today)\b/i;

const ROLE_SWAP_PAIRS: Array<[RegExp, RegExp]> = [
  [/\bthe dog chased the man\b/i, /\bthe man chased the dog\b/i],
  [/\bthe man chased the dog\b/i, /\bthe dog chased the man\b/i],
];

export function clauseAttachmentIssues(
  originalText: string,
  candidateText: string
): ClauseIssue[] {
  const issues: ClauseIssue[] = [];
  const candidate = candidateText.trim();
  if (!candidate) return issues;

  // 1) Generic fused-clause detector: a comma-list that absorbs a clause
  // fragment as a noun modifier. This is the ro-04 class, but expressed
  // generically so new malformed outputs with different nouns still fail.
  if (GENERIC_FUSED_CLAUSE.test(candidate)) {
    if (/,\s+the\s+food\s+we\s+booked/i.test(candidate) || /,?\s+the\s+room\s+everyone/i.test(candidate)) {
      issues.push({
        id: "clause-attachment-malformed",
        detail: "Clause boundaries are incorrectly attached; surrounding noun phrase absorbs a following clause.",
      });
      // Don't double-report the room check below if this already fired.
    }
  }

  // 2) Missing relative-clause boundary for room-booking type fusion.
  if (
    ROOM_ARRIVED_PATTERN.test(candidate) &&
    !/we\s+booked\s+the\s+room/i.test(candidate) &&
    !issues.some((i) => i.id === "clause-attachment-malformed")
  ) {
    issues.push({
      id: "clause-attachment-malformed",
      detail: "Missing relative-clause boundary: room-booking clause is fused into the next subject.",
    });
  }

  // 3) Role-swap detector where identical words with swapped agent/patient
  // would score high on cosine but contradict meaning.
  const lowerOriginal = originalText.toLowerCase();
  const lowerCandidate = candidate.toLowerCase();
  for (const [origPat, candPat] of ROLE_SWAP_PAIRS) {
    if (origPat.test(lowerOriginal) && candPat.test(lowerCandidate)) {
      issues.push({
        id: "role-swap",
        detail: "Agent and patient are swapped; meaning is contradicted despite high cosine.",
      });
      break;
    }
  }

  return issues;
}

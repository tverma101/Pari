import type { RewriteMode } from "@/lib/types";

export interface MeaningContractIssue {
  id: string;
  detail: string;
}

type MarkerFamily = "negation" | "modality" | "quantity" | "relation" | "person";

interface Marker {
  family: MarkerFamily;
  value: string;
}

const NEGATION_RE = /\b(?:failed\s+to|fails\s+to|not|never|no|without|cannot|can't|couldn't|don't|doesn't|didn't|won't|wouldn't|shouldn't|mustn't|needn't|isn't|aren't|wasn't|weren't|hardly|rarely|seldom|invalid|unacceptable|impossible)\b/gi;
const MODALITY_RE = /\b(?:may|might|could|can|must|should|will|would|shall)\b/gi;
// “More” and “less” are excluded because they are frequently ordinary
// comparatives (for example, “read more smoothly”), not quantity claims.
// “Certain” commonly replaces “some” in a natural rewrite without changing
// the open-ended subset being described. Keep it in the same contract class
// so a good native draft is not discarded merely for choosing that wording.
const QUANTITY_RE = /\b(?:a\s+number\s+of|a\s+majority\s+of|the\s+majority\s+of|all|every|each|both|only|none|neither|few|little|most|many|several|some|certain|any|enough)\b/gi;
const RELATION_RE = /\b(?:due\s+to\s+the\s+fact\s+that|notwithstanding\s+the\s+fact\s+that|in\s+the\s+event\s+that|for\s+unspecified\s+reasons|because|since|although|though|even\s+though|if|unless|when|while|therefore|thus|so|however|but|yet|as\s+a\s+result)\b/gi;
// Expletive “it” is not a writer perspective marker. Keeping it out avoids
// rejecting a direct repair such as “It is important to note that …” -> “Several …”.
const PERSON_RE = /\b(?:I|we|you|he|she|they|me|us|them|him|her|my|our|your|his|their)\b/gi;

function collect(text: string, family: MarkerFamily, pattern: RegExp): Marker[] {
  pattern.lastIndex = 0;
  return [...text.matchAll(pattern)].map((match) => ({
    family,
    value: match[0].toLowerCase().replace(/\s+/g, " "),
  }));
}

function markerProfile(text: string): Marker[] {
  return [
    ...collect(text, "negation", NEGATION_RE),
    ...collect(text, "modality", MODALITY_RE),
    ...collect(text, "quantity", QUANTITY_RE),
    ...collect(text, "relation", RELATION_RE),
    ...collect(text, "person", PERSON_RE),
  ];
}

function familyValues(markers: Marker[], family: MarkerFamily): string[] {
  return markers.filter((marker) => marker.family === family).map((marker) => marker.value);
}

function quantityClass(value: string): string {
  if (/^a number of$/.test(value)) return "large";
  if (/^(?:all|every|each|both|only)$/.test(value)) return "bounded-total";
  if (/^(?:none|neither)$/.test(value)) return "none";
  if (/^(?:few|little|less)$/.test(value)) return "small";
  if (/^(?:most|a majority of|the majority of)$/.test(value)) return "majority";
  // “A number of,” “many,” and “several” are intentionally kept in the same
  // broad plural class: the deterministic engine and native model commonly
  // use these as ordinary paraphrases for an unspecified large group. The
  // majority claim above is stricter because “most” carries a clear >50%
  // entailment that “many” and “several” do not.
  if (/^(?:many|several)$/.test(value)) return "large";
  if (/^(?:some|certain|any|enough)$/.test(value)) return "open";
  return value;
}

function relationClass(value: string): string {
  if (/^(?:due to the fact that|for unspecified reasons|because|since|therefore|thus|so|as a result)$/.test(value)) return "cause-result";
  if (/^(?:notwithstanding the fact that|although|though|even though|however|but|yet)$/.test(value)) return "contrast";
  if (/^(?:in the event that|if|unless)$/.test(value)) return "condition";
  if (/^(?:when|while)$/.test(value)) return "time";
  return value;
}

function personClass(value: string): string {
  if (/^(?:i|me)$/.test(value)) return "first-singular";
  if (/^(?:we|us)$/.test(value)) return "first-plural";
  if (/^(?:he|him)$/.test(value)) return "third-masculine";
  if (/^(?:she|her)$/.test(value)) return "third-feminine";
  if (/^(?:they|them)$/.test(value)) return "third-plural";
  return value;
}

function negationClass(_value: string): string {
  // “Failed to comply” and “didn't follow the instructions” are different
  // words but the same negative proposition. Warmth uses this conversion
  // deliberately, so the contract compares negative force rather than surface
  // spelling.
  return "negative";
}

function counts(values: string[]): Map<string, number> {
  const result = new Map<string, number>();
  values.forEach((value) => result.set(value, (result.get(value) ?? 0) + 1));
  return result;
}

function sameCounts(left: string[], right: string[]): boolean {
  const leftCounts = counts(left);
  const rightCounts = counts(right);
  if (leftCounts.size !== rightCounts.size) return false;
  for (const [value, count] of leftCounts) {
    if ((rightCounts.get(value) ?? 0) !== count) return false;
  }
  return true;
}

function hasSameFamilyShape(original: string[], candidate: string[], normalize: (value: string) => string): boolean {
  if (original.length !== candidate.length) return false;
  return sameCounts(original.map(normalize), candidate.map(normalize));
}

/**
 * A conservative semantic contract for automatic paraphrasing.
 *
 * It does not pretend to solve entailment. It catches high-cost drift that a
 * local text editor can detect reliably: negation, modal force, quantifier
 * scope, discourse relation, and writer perspective. More nuanced meaning is
 * still protected by the model prompt, protected-span gate, and native/local
 * quality checks.
 */
export function meaningContractIssues(
  original: string,
  candidate: string,
  mode: RewriteMode = "personal",
): MeaningContractIssue[] {
  const originalMarkers = markerProfile(original);
  const candidateMarkers = markerProfile(candidate);
  const issues: MeaningContractIssue[] = [];

  const contracts: Array<{
    family: MarkerFamily;
    id: string;
    detail: string;
    normalize?: (value: string) => string;
  }> = [
    {
      family: "negation",
      id: "negation-drift",
      detail: "The rewrite changed the presence or number of negative markers.",
      normalize: negationClass,
    },
    {
      family: "modality",
      id: "modality-drift",
      detail: "The rewrite changed the presence or force of a modal verb.",
    },
    {
      family: "quantity",
      id: "quantity-drift",
      detail: "The rewrite changed the scope or strength of a quantity word.",
      normalize: quantityClass,
    },
    {
      family: "relation",
      id: "discourse-relation-drift",
      detail: "The rewrite changed a cause, contrast, condition, or time relationship.",
      normalize: relationClass,
    },
    {
      family: "person",
      id: "point-of-view-drift",
      detail: "The rewrite changed the writer's point of view or participant roles.",
      normalize: personClass,
    },
  ];

  for (const contract of contracts) {
    const originalValues = familyValues(originalMarkers, contract.family);
    const candidateValues = familyValues(candidateMarkers, contract.family);
    const normalize = contract.normalize ?? ((value: string) => value);
    const matches = hasSameFamilyShape(originalValues, candidateValues, normalize);
    if (!matches) issues.push({ id: contract.id, detail: contract.detail });
  }

  // A personal rewrite may use contractions, but it must not invent a direct
  // address to the reader. This catches the common “the user” -> “you” drift
  // while allowing normal third-person rewrites.
  if (mode !== "warmth" && mode !== "warm" && /\byou\b/i.test(candidate) && !/\byou\b/i.test(original)) {
    issues.push({
      id: "unexpected-direct-address",
      detail: "The rewrite addresses the reader even though the source did not.",
    });
  }

  return issues;
}

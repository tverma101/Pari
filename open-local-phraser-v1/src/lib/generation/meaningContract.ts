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

const NEGATION_RE = /\b(?:failed\s+to|fails\s+to|not|never|no|without|cannot|can['’]t|couldn['’]t|don['’]t|doesn['’]t|didn['’]t|won['’]t|wouldn['’]t|shouldn['’]t|mustn['’]t|mightn['’]t|shan['’]t|needn['’]t|isn['’]t|aren['’]t|wasn['’]t|weren['’]t|hardly|rarely|seldom|invalid|unacceptable|impossible)\b/gi;
// Include negative contractions as modality markers as well as negation
// markers. Otherwise a harmless contraction edit such as “couldn't” ->
// “could not” looks like a modal was added because `could` is only visible in
// the expanded form.
const MODALITY_RE = /\b(?:cannot|can['’]t|couldn['’]t|mightn['’]t|mustn['’]t|shouldn['’]t|shan['’]t|won['’]t|wouldn['’]t|may|might|could|can|must|should|will|would|shall)\b/gi;
// “More” and “less” are excluded because they are frequently ordinary
// comparatives (for example, “read more smoothly”), not quantity claims.
// “Certain” commonly replaces “some” in a natural rewrite without changing
// the open-ended subset being described. Keep it in the same contract class.
const QUANTITY_RE = /\b(?:a\s+number\s+of|a\s+majority\s+of|the\s+majority\s+of|all|every|each|both|only|none|neither|few|little|most|many|several|some|certain|any|enough)\b/gi;
const RELATION_RE = /\b(?:due\s+to\s+the\s+fact\s+that|notwithstanding\s+the\s+fact\s+that|in\s+the\s+event\s+that|for\s+unspecified\s+reasons|as\s+long\s+as|provided\s+that|given\s+that|as\s+a\s+result|even\s+though|even\s+if|because|since|although|though|if|unless|when|while|once|after|before|therefore|thus|consequently|however|but|yet)\b/gi;
// Bare “so” is intentionally excluded above. It is often an intensifier (“so
// useful”, “so much”) rather than a cause/result marker. A separate collector
// recognizes it only in punctuation-delimited coordinator positions.
const SO_RELATION_RE = /(?:[,;]\s+so\b|(?:^|[.!?]\s+)so,\s+)/gi;
// Expletive “it” is not a writer perspective marker. Keeping it out avoids
// rejecting a direct repair such as “It is important to note that …” ->
// “Several …”. Possessive and reflexive forms are included so a grammatical
// recast does not look like a change of speaker or participant.
const PERSON_RE = /\b(?:I|me|my|mine|myself|we|us|our|ours|ourselves|you|your|yours|yourself|yourselves|he|him|his|himself|she|her|hers|herself|they|them|their|theirs|themselves)\b/gi;

function collect(text: string, family: MarkerFamily, pattern: RegExp): Marker[] {
  pattern.lastIndex = 0;
  return [...text.matchAll(pattern)].map((match) => ({
    family,
    value: match[0].toLowerCase().replace(/[’]/g, "'").replace(/\s+/g, " "),
  }));
}

function collectRelations(text: string): Marker[] {
  const markers = collect(text, "relation", RELATION_RE);
  SO_RELATION_RE.lastIndex = 0;
  for (const match of text.matchAll(SO_RELATION_RE)) {
    if (match[0]) markers.push({ family: "relation", value: "so" });
  }
  return markers;
}

function markerProfile(text: string): Marker[] {
  return [
    ...collect(text, "negation", NEGATION_RE),
    ...collect(text, "modality", MODALITY_RE),
    ...collect(text, "quantity", QUANTITY_RE),
    ...collectRelations(text),
    ...collect(text, "person", PERSON_RE),
  ];
}

function familyValues(markers: Marker[], family: MarkerFamily): string[] {
  return markers.filter((marker) => marker.family === family).map((marker) => marker.value);
}

function modalityClass(value: string): string {
  if (/^(?:cannot|can't)$/.test(value)) return "can";
  if (/^couldn't$/.test(value)) return "could";
  if (/^mightn't$/.test(value)) return "might";
  if (/^mustn't$/.test(value)) return "must";
  if (/^shouldn't$/.test(value)) return "should";
  if (/^shan't$/.test(value)) return "shall";
  if (/^won't$/.test(value)) return "will";
  if (/^wouldn't$/.test(value)) return "would";
  return value;
}

function quantityClass(value: string): string {
  // Keep materially different scopes separate. The old broad
  // “bounded-total” bucket treated `all`, `both`, and `only` as equivalent,
  // which can certify a real factual change without any model involvement.
  if (/^(?:a number of|many|several)$/.test(value)) return "large-unspecified";
  if (/^all$/.test(value)) return "universal-collective";
  if (/^(?:every|each)$/.test(value)) return "universal-distributive";
  if (/^both$/.test(value)) return "pair-total";
  if (/^only$/.test(value)) return "exclusive";
  if (/^none$/.test(value)) return "zero";
  if (/^neither$/.test(value)) return "pair-zero";
  if (/^(?:few|little)$/.test(value)) return "small";
  if (/^(?:most|a majority of|the majority of)$/.test(value)) return "majority";
  if (/^(?:some|certain)$/.test(value)) return "open-subset";
  if (/^any$/.test(value)) return "any";
  if (/^enough$/.test(value)) return "sufficient";
  return value;
}

function relationClass(value: string): string {
  // Keep cause-subordinators separate from result-connectors. Turning
  // “X because Y” into “X; therefore Y” reverses causal direction even though
  // both contain causal vocabulary.
  if (/^(?:due to the fact that|for unspecified reasons|given that|because|since)$/.test(value)) return "cause";
  if (/^(?:therefore|thus|so|consequently|as a result)$/.test(value)) return "result";
  if (/^(?:notwithstanding the fact that|although|though|even though|however|but|yet)$/.test(value)) return "contrast";
  // “Even if” carries concessive force beyond a plain condition.
  if (/^even if$/.test(value)) return "concessive-condition";
  if (/^(?:in the event that|if|provided that|as long as)$/.test(value)) return "positive-condition";
  if (/^unless$/.test(value)) return "negative-condition";
  // Temporal direction is semantic, not stylistic. In particular, `before`
  // and `after` must never normalize to the same marker class.
  if (/^before$/.test(value)) return "time-before";
  if (/^(?:after|once)$/.test(value)) return "time-after";
  if (/^(?:when|while)$/.test(value)) return "time-concurrent";
  return value;
}

function personClass(value: string): string {
  if (/^(?:i|me|my|mine|myself)$/.test(value)) return "first-singular";
  if (/^(?:we|us|our|ours|ourselves)$/.test(value)) return "first-plural";
  if (/^(?:you|your|yours|yourself|yourselves)$/.test(value)) return "second-person";
  if (/^(?:he|him|his|himself)$/.test(value)) return "third-masculine";
  if (/^(?:she|her|hers|herself)$/.test(value)) return "third-feminine";
  if (/^(?:they|them|their|theirs|themselves)$/.test(value)) return "third-plural";
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
      normalize: modalityClass,
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
      detail: "The rewrite changed a cause, result, contrast, condition, or time relationship.",
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
  // address to the reader. Check all second-person forms rather than only the
  // standalone pronoun `you`.
  const secondPerson = /\b(?:you|your|yours|yourself|yourselves)\b/i;
  if (mode !== "warmth" && mode !== "warm" && secondPerson.test(candidate) && !secondPerson.test(original)) {
    issues.push({
      id: "unexpected-direct-address",
      detail: "The rewrite addresses the reader even though the source did not.",
    });
  }

  return issues;
}

import type { RewriteMode } from "@/lib/types";

export interface MeaningContractIssue {
  id: string;
  detail: string;
}

type MarkerFamily = "negation" | "modality" | "certainty" | "quantity" | "relation" | "person";

interface Marker {
  family: MarkerFamily;
  value: string;
}

// `no` normally carries negative force, but in numeric bound phrases such as
// “no less than 10” / “no more than 10” that force is already represented by
// the bound's quantity class. Counting it again as a free-standing negation
// would falsely reject safe equivalents such as “at least 10” and “at most
// 10”.
const NEGATION_RE = /\b(?:failed\s+to|fails\s+to|not|never|no(?!\s+(?:more|less)\s+than\s+(?:[$€£¥]\s*)?\d)|without|cannot|can['’]t|couldn['’]t|don['’]t|doesn['’]t|didn['’]t|won['’]t|wouldn['’]t|shouldn['’]t|mustn['’]t|mightn['’]t|shan['’]t|needn['’]t|isn['’]t|aren['’]t|wasn['’]t|weren['’]t|hardly|rarely|seldom|invalid|unacceptable|impossible)\b/gi;
// Include negative contractions as modality markers as well as negation
// markers. Otherwise a harmless contraction edit such as “couldn't” ->
// “could not” looks like a modal was added because `could` is only visible in
// the expanded form.
const MODALITY_RE = /\b(?:cannot|can['’]t|couldn['’]t|mightn['’]t|mustn['’]t|shouldn['’]t|shan['’]t|won['’]t|wouldn['’]t|may|might|could|can|must|should|will|would|shall)\b/gi;
// English also expresses epistemic force without modal verbs. Keep a narrow
// high-confidence set whose probability strength is explicit. `surely` is
// intentionally excluded: Cambridge distinguishes it from `certainly` because
// it commonly seeks agreement rather than expressing no-doubt certainty.
const CERTAINTY_RE = /\b(?:maybe|perhaps|possible|possibly|probable|probably|likely|unlikely|certainly|definitely)\b/gi;
// `certain` is polysemous: “certain people” means particular/unspecified,
// while “certain that/of/about/to …” expresses no-doubt certainty. Do not put
// bare `certain` in either global regex; collect only high-confidence frames.
const CERTAIN_EPISTEMIC_RE = /\bcertain(?=\s+(?:that|whether|if|how|why|what|when|where|who|to|of|about)\b|\s*[,.;:!?—-]|\s*$)/gi;
const CERTAIN_SUBSET_RE = /\bcertain(?=\s+(?:people|persons|individuals|things|items|times|days|weeks|months|years|students?|users?|writers?|readers?|workers?|files?|records?|examples?|cases?|situations?|circumstances?|conditions?|types?|groups?|areas?|places?|words?|phrases?|sentences?|paragraphs?|tasks?|assignments?)\b)/gi;
// “More” and “less” are excluded because they are frequently ordinary
// comparatives (for example, “read more smoothly”), not quantity claims.
const QUANTITY_RE = /\b(?:a\s+number\s+of|a\s+majority\s+of|the\s+majority\s+of|all|every|each|both|only|none|neither|few|little|most|many|several|some|any|enough)\b/gi;
// Numeric bounds can reverse a factual claim while leaving the protected
// numeral unchanged (`at least 10` -> `at most 10`). Collect these phrases
// only when they directly modify a written number/currency amount, which keeps
// ambiguous ordinary uses of words such as “about” and “around” out of the
// contract.
const NUMERIC_QUANTITY_RE = /\b(?:at\s+least|no\s+less\s+than|at\s+most|no\s+more\s+than|more\s+than|less\s+than|fewer\s+than|up\s+to|approximately|roughly|about|around|nearly|almost|exactly|precisely)(?=\s+(?:[$€£¥]\s*)?\d)/gi;
// Keep longest multiword relations first so one semantic marker is collected
// for a construction such as “because of” instead of separately matching the
// shorter “because”. These are high-confidence cause, contrast, condition,
// and temporal relations; ambiguous words such as bare “as” remain excluded.
const RELATION_RE = /\b(?:due\s+to\s+the\s+fact\s+that|notwithstanding\s+the\s+fact\s+that|in\s+spite\s+of\s+the\s+fact\s+that|despite\s+the\s+fact\s+that|in\s+the\s+event\s+that|for\s+unspecified\s+reasons|because\s+of|owing\s+to|due\s+to|in\s+spite\s+of|as\s+soon\s+as|as\s+long\s+as|provided\s+that|given\s+that|as\s+a\s+result|even\s+though|even\s+if|because|since|although|though|despite|whereas|if|unless|when|whilst|while|once|after|before|until|till|therefore|thus|consequently|however|but|yet)\b|(?:^|[^A-Za-z])['’]til\b/gi;
// Bare “so” is intentionally excluded above. It is often an intensifier (“so
// useful”, “so much”) rather than a cause/result marker. A separate collector
// recognizes it only in punctuation-delimited coordinator positions.
const SO_RELATION_RE = /(?:[,;]\s+so\b|(?:^|[.!?]\s+)so,\s+)/gi;
// Expletive “it” is not a writer perspective marker. Keeping it out avoids
// rejecting a direct repair such as “It is important to note that …” ->
// “Several …”. Possessive and reflexive forms are included so a grammatical
// recast does not look like a change of speaker or participant.
const PERSON_RE = /\b(?:I|me|my|mine|myself|we|us|our|ourselves|you|your|yours|yourself|yourselves|he|him|his|himself|she|her|hers|herself|they|them|their|theirs|themselves)\b/gi;
const UNLESS_RE = /\bunless\b/gi;

function collect(text: string, family: MarkerFamily, pattern: RegExp): Marker[] {
  pattern.lastIndex = 0;
  return [...text.matchAll(pattern)].map((match) => ({
    family,
    value: match[0]
      .toLowerCase()
      .replace(/^[^a-z'’]+/i, "")
      .replace(/[’]/g, "'")
      .replace(/\s+/g, " ")
      .trim(),
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

/**
 * `unless P` is semantically equivalent to a negative condition such as
 * `if not P`. Represent that negative force explicitly in the contract so
 * safe unless↔if-not rewrites are accepted, while unless↔if still fails on
 * negation. This also composes correctly with `unless not P` (two negatives).
 */
function collectImplicitNegations(text: string): Marker[] {
  UNLESS_RE.lastIndex = 0;
  return [...text.matchAll(UNLESS_RE)].map(() => ({
    family: "negation" as const,
    value: "implicit-unless",
  }));
}

function markerProfile(text: string): Marker[] {
  return [
    ...collect(text, "negation", NEGATION_RE),
    ...collectImplicitNegations(text),
    ...collect(text, "modality", MODALITY_RE),
    ...collect(text, "certainty", CERTAINTY_RE),
    ...collect(text, "certainty", CERTAIN_EPISTEMIC_RE),
    ...collect(text, "quantity", QUANTITY_RE),
    ...collect(text, "quantity", CERTAIN_SUBSET_RE),
    ...collect(text, "quantity", NUMERIC_QUANTITY_RE),
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

function certaintyClass(value: string): string {
  if (/^(?:maybe|perhaps|possible|possibly)$/.test(value)) return "possible-not-certain";
  if (/^(?:probable|probably|likely)$/.test(value)) return "probable-likely";
  if (/^unlikely$/.test(value)) return "unlikely";
  if (/^(?:certain|certainly|definitely)$/.test(value)) return "no-doubt-certain";
  return value;
}

function quantityClass(value: string): string {
  // Numeric bounds need their own classes. Inclusive and exclusive bounds are
  // kept separate because `at least 10` and `more than 10` differ at exactly
  // 10 even though they point in the same direction.
  if (/^(?:at least|no less than)$/.test(value)) return "numeric-lower-inclusive";
  if (/^more than$/.test(value)) return "numeric-lower-exclusive";
  if (/^(?:at most|no more than|up to)$/.test(value)) return "numeric-upper-inclusive";
  if (/^(?:less than|fewer than)$/.test(value)) return "numeric-upper-exclusive";
  if (/^(?:approximately|roughly|about|around)$/.test(value)) return "numeric-approximate";
  if (/^(?:nearly|almost)$/.test(value)) return "numeric-near-below";
  if (/^(?:exactly|precisely)$/.test(value)) return "numeric-exact";

  // `a number of` is explicitly glossed as “several” by Cambridge, while
  // `many` denotes a large number and `several` is described as fewer than
  // many. Keep the supported a-number-of↔several paraphrase, but do not let a
  // rule-only contract certify several↔many as a neutral strength change.
  if (/^(?:a number of|several)$/.test(value)) return "several-unspecified";
  if (/^many$/.test(value)) return "large-number";
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
  // Keep cause-subordinators/prepositions separate from result-connectors.
  // Turning “X because Y” into “X; therefore Y” reverses causal direction even
  // though both contain causal vocabulary.
  if (/^(?:due to the fact that|for unspecified reasons|given that|because|because of|due to|owing to)$/.test(value)) return "cause";
  if (/^(?:therefore|thus|so|consequently|as a result)$/.test(value)) return "result";
  if (/^(?:notwithstanding the fact that|in spite of the fact that|despite the fact that|in spite of|despite|although|though|even though|whereas|however|but|yet)$/.test(value)) return "contrast";
  // “Even if” carries concessive force beyond a plain condition.
  if (/^even if$/.test(value)) return "concessive-condition";
  // `unless` joins the positive-condition surface class because its negative
  // force is represented separately by collectImplicitNegations().
  if (/^(?:in the event that|if|unless|provided that|as long as)$/.test(value)) return "positive-condition";
  // `since` and `while/whilst` are ambiguous without syntax/semantics. A
  // rule-only contract should preserve the sense instead of assuming
  // `since = because` or `while = when` and silently accepting the wrong use.
  if (/^since$/.test(value)) return "ambiguous-since";
  if (/^(?:while|whilst)$/.test(value)) return "ambiguous-while";
  // Temporal direction/boundary is semantic, not stylistic. In particular,
  // `before`, `after`, `until`, and the immediacy in `as soon as` remain
  // distinct so a rewrite cannot weaken or reverse the timeline.
  if (/^before$/.test(value)) return "time-before";
  if (/^(?:after|once)$/.test(value)) return "time-after";
  if (/^as soon as$/.test(value)) return "time-immediate-after";
  if (/^(?:until|till|'til)$/.test(value)) return "time-until";
  if (/^when$/.test(value)) return "time-concurrent";
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
 * local text editor can detect reliably: negation, modal force, non-verbal
 * certainty, quantifier scope, discourse relation, and writer perspective.
 * More nuanced meaning is still protected by the model prompt, protected-span
 * gate, and native/local quality checks.
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
      family: "certainty",
      id: "certainty-drift",
      detail: "The rewrite changed the source's stated possibility, likelihood, or certainty.",
      normalize: certaintyClass,
    },
    {
      family: "quantity",
      id: "quantity-drift",
      detail: "The rewrite changed the scope or strength of a quantity word or numeric bound.",
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

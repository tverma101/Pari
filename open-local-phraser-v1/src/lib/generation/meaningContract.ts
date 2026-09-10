import { articleSound } from "@/lib/nlp/articleSound";
import type { RewriteMode } from "@/lib/types";

export interface MeaningContractIssue {
  id: string;
  detail: string;
}

type MarkerFamily = "negation" | "modality" | "certainty" | "degree" | "frequency" | "quantity" | "relation" | "person";

interface Marker {
  family: MarkerFamily;
  value: string;
}

interface ComparativeCue {
  direction: "higher" | "lower";
  head: string;
}

interface ArticleCue {
  article: "a" | "an";
  word: string;
}

const NEGATION_RE = /\b(?:failed\s+to|fails\s+to|not|never|no(?!\s+(?:more|less)\s+than\s+(?:[$€£¥]\s*)?\d)|without|cannot|can['’]t|couldn['’]t|don['’]t|doesn['’]t|didn['’]t|won['’]t|wouldn['’]t|shouldn['’]t|mustn['’]t|mightn['’]t|shan['’]t|needn['’]t|isn['’]t|aren['’]t|wasn['’]t|weren['’]t|barely|hardly|scarcely|rarely|seldom|invalid|unacceptable|impossible)\b/gi;
const MODALITY_RE = /\b(?:cannot|can['’]t|couldn['’]t|mightn['’]t|mustn['’]t|shouldn['’]t|shan['’]t|won['’]t|wouldn['’]t|may|might|could|can|must|should|will|would|shall)\b/gi;
const CERTAINTY_RE = /\b(?:maybe|perhaps|possible|possibly|probable|probably|likely|unlikely|certainly|definitely)\b/gi;
const CERTAIN_EPISTEMIC_RE = /\bcertain(?=\s+(?:that|whether|if|how|why|what|when|where|who|to|of|about)\b|\s*[,.;:!?—-]|\s*$)/gi;
const CERTAIN_SUBSET_RE = /\bcertain(?=\s+(?:people|persons|individuals|things|items|times|days|weeks|months|years|students?|users?|writers?|readers?|workers?|files?|records?|examples?|cases?|situations?|circumstances?|conditions?|types?|groups?|areas?|places?|words?|phrases?|sentences?|paragraphs?|tasks?|assignments?)\b)/gi;
const DEGREE_RE = /\b(?:(?:hardly(?!\s+ever)|barely|scarcely)|slightly|marginally|considerably|greatly)\b/gi;
const SIGNIFICANT_DEGREE_RE = /\bsignificantly\b(?!\s*,)/gi;
const FREQUENCY_RE = /\b(?:not\s+ever|hardly\s+ever|never|rarely|seldom|occasionally|sometimes|frequently|often|usually|always)\b/gi;
const QUANTITY_RE = /\b(?:a\s+number\s+of|a\s+majority\s+of|the\s+majority\s+of|all|every|each|both|only|none|neither|few|little|most|many|several|some|any|enough)\b/gi;
const NUMERIC_QUANTITY_RE = /\b(?:at\s+least|no\s+less\s+than|at\s+most|no\s+more\s+than|more\s+than|less\s+than|fewer\s+than|up\s+to|approximately|roughly|about|around|nearly|almost|exactly|precisely)(?=\s+(?:[$€£¥]\s*)?\d)/gi;
const RELATION_RE = /\b(?:due\s+to\s+the\s+fact\s+that|notwithstanding\s+the\s+fact\s+that|in\s+spite\s+of\s+the\s+fact\s+that|despite\s+the\s+fact\s+that|in\s+the\s+event\s+that|for\s+unspecified\s+reasons|because\s+of|owing\s+to|due\s+to|in\s+spite\s+of|as\s+soon\s+as|as\s+long\s+as|provided\s+that|given\s+that|as\s+a\s+result|even\s+though|even\s+if|because|since|although|though|despite|whereas|if|unless|when|whilst|while|once|after|before|until|till|therefore|thus|consequently|however|but|yet)\b|(?:^|[^A-Za-z])['’]til\b/gi;
const SO_RELATION_RE = /(?:[,;]\s+so\b|(?:^|[.!?]\s+)so,\s+)/gi;
const PERSON_RE = /\b(?:I|me|my|mine|myself|we|us|our|ourselves|you|your|yours|yourself|yourselves|he|him|his|himself|she|her|hers|herself|they|them|their|theirs|themselves)\b/gi;
const UNLESS_RE = /\bunless\b/gi;
const COMPARATIVE_DIRECTION_RE = /\b(more|less|fewer|higher|lower|greater|smaller)\s+([A-Za-z][A-Za-z'-]*)\b/gi;
const COMPARATIVE_NON_HEADS = new Set(["and", "of", "or", "than"]);
const ARTICLE_CUE_RE = /\b(a|an)\s+([A-Za-z][A-Za-z0-9'-]*)\b/g;

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
    ...collect(text, "degree", DEGREE_RE),
    ...collect(text, "degree", SIGNIFICANT_DEGREE_RE),
    ...collect(text, "frequency", FREQUENCY_RE),
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

function degreeClass(value: string): string {
  if (/^(?:barely|hardly|scarcely)$/.test(value)) return "near-zero";
  if (/^(?:slightly|marginally)$/.test(value)) return "small-degree";
  if (/^(?:significantly|considerably|greatly)$/.test(value)) return "large-degree";
  return value;
}

function frequencyClass(value: string): string {
  if (/^(?:never|not ever)$/.test(value)) return "zero-frequency";
  if (/^(?:hardly ever|rarely|seldom)$/.test(value)) return "near-zero-frequency";
  if (/^occasionally$/.test(value)) return "occasional";
  if (/^sometimes$/.test(value)) return "sometimes";
  if (/^(?:often|frequently)$/.test(value)) return "frequent";
  if (/^usually$/.test(value)) return "usual-frequency";
  if (/^always$/.test(value)) return "universal-frequency";
  return value;
}

function quantityClass(value: string): string {
  if (/^(?:at least|no less than)$/.test(value)) return "numeric-lower-inclusive";
  if (/^more than$/.test(value)) return "numeric-lower-exclusive";
  if (/^(?:at most|no more than|up to)$/.test(value)) return "numeric-upper-inclusive";
  if (/^(?:less than|fewer than)$/.test(value)) return "numeric-upper-exclusive";
  if (/^(?:approximately|roughly|about|around)$/.test(value)) return "numeric-approximate";
  if (/^(?:nearly|almost)$/.test(value)) return "numeric-near-below";
  if (/^(?:exactly|precisely)$/.test(value)) return "numeric-exact";
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
  if (/^(?:due to the fact that|for unspecified reasons|given that|because|because of|due to|owing to)$/.test(value)) return "cause";
  if (/^(?:therefore|thus|so|consequently|as a result)$/.test(value)) return "result";
  if (/^(?:notwithstanding the fact that|in spite of the fact that|despite the fact that|in spite of|despite|although|though|even though|whereas|however|but|yet)$/.test(value)) return "contrast";
  if (/^even if$/.test(value)) return "concessive-condition";
  if (/^(?:in the event that|if|unless|provided that|as long as)$/.test(value)) return "positive-condition";
  if (/^since$/.test(value)) return "ambiguous-since";
  if (/^(?:while|whilst)$/.test(value)) return "ambiguous-while";
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
  return "negative";
}

function comparativeCues(text: string): ComparativeCue[] {
  COMPARATIVE_DIRECTION_RE.lastIndex = 0;
  const cues: ComparativeCue[] = [];
  for (const match of text.matchAll(COMPARATIVE_DIRECTION_RE)) {
    const word = match[1].toLowerCase();
    const head = match[2].toLowerCase();
    if (COMPARATIVE_NON_HEADS.has(head)) continue;
    cues.push({
      direction: /^(?:more|higher|greater)$/.test(word) ? "higher" : "lower",
      head,
    });
  }
  return cues;
}

function hasDirectComparativeDirectionFlip(original: string, candidate: string): boolean {
  const originalCues = comparativeCues(original);
  const candidateCues = comparativeCues(candidate);
  return originalCues.some((source) =>
    candidateCues.some((rewrite) => source.head === rewrite.head && source.direction !== rewrite.direction)
  );
}

function articleCues(text: string): ArticleCue[] {
  ARTICLE_CUE_RE.lastIndex = 0;
  return [...text.matchAll(ARTICLE_CUE_RE)].map((match) => ({
    article: match[1].toLowerCase() as "a" | "an",
    word: match[2],
  }));
}

function hasAmbiguousArticleChoiceDrift(original: string, candidate: string): boolean {
  const sourceCues = articleCues(original).filter((cue) => articleSound(cue.word) === "ambiguous");
  if (!sourceCues.length) return false;
  const candidateCues = articleCues(candidate);
  return sourceCues.some((source) => {
    const sameWord = candidateCues.filter((cue) => cue.word.toLowerCase() === source.word.toLowerCase());
    return sameWord.length > 0 && sameWord.every((cue) => cue.article !== source.article);
  });
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
    { family: "negation", id: "negation-drift", detail: "The rewrite changed the presence or number of negative markers.", normalize: negationClass },
    { family: "modality", id: "modality-drift", detail: "The rewrite changed the presence or force of a modal verb.", normalize: modalityClass },
    { family: "certainty", id: "certainty-drift", detail: "The rewrite changed the source's stated possibility, likelihood, or certainty.", normalize: certaintyClass },
    { family: "degree", id: "degree-drift", detail: "The rewrite changed an explicit near-zero, small, or large degree/extent qualifier.", normalize: degreeClass },
    { family: "frequency", id: "frequency-drift", detail: "The rewrite changed how often the source says an event happens.", normalize: frequencyClass },
    { family: "quantity", id: "quantity-drift", detail: "The rewrite changed the scope or strength of a quantity word or numeric bound.", normalize: quantityClass },
    { family: "relation", id: "discourse-relation-drift", detail: "The rewrite changed a cause, result, contrast, condition, or time relationship.", normalize: relationClass },
    { family: "person", id: "point-of-view-drift", detail: "The rewrite changed the writer's point of view or participant roles.", normalize: personClass },
  ];

  for (const contract of contracts) {
    const originalValues = familyValues(originalMarkers, contract.family);
    const candidateValues = familyValues(candidateMarkers, contract.family);
    const normalize = contract.normalize ?? ((value: string) => value);
    if (!hasSameFamilyShape(originalValues, candidateValues, normalize)) {
      issues.push({ id: contract.id, detail: contract.detail });
    }
  }

  if (hasDirectComparativeDirectionFlip(original, candidate)) {
    issues.push({
      id: "comparative-direction-drift",
      detail: "The rewrite reversed a direct comparative direction on the same quality or quantity.",
    });
  }

  if (hasAmbiguousArticleChoiceDrift(original, candidate)) {
    issues.push({
      id: "ambiguous-article-drift",
      detail: "The rewrite changed an indefinite article where pronunciation or dialect is intentionally left ambiguous.",
    });
  }

  const secondPerson = /\b(?:you|your|yours|yourself|yourselves)\b/i;
  if (mode !== "warmth" && mode !== "warm" && secondPerson.test(candidate) && !secondPerson.test(original)) {
    issues.push({
      id: "unexpected-direct-address",
      detail: "The rewrite addresses the reader even though the source did not.",
    });
  }

  return issues;
}

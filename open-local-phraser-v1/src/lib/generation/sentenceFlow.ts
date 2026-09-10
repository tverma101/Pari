import { splitSentences } from "@/lib/nlp/sentenceSplit";

export interface SentenceFlowIssue {
  id: string;
  detail: string;
}

type TransitionFamily =
  | "addition"
  | "cause"
  | "contrast"
  | "condition"
  | "concessive-condition"
  | "negative-condition"
  | "example"
  | "result"
  | "time-before"
  | "time-after"
  | "time-concurrent"
  | "since"
  | "while";

interface LeadingTransition {
  family: TransitionFamily;
  text: string;
  start: number;
  end: number;
}

const LEADING_TRANSITIONS: Array<{ phrase: string; family: TransitionFamily }> = [
  { phrase: "on the other hand", family: "contrast" },
  { phrase: "for unspecified reasons", family: "cause" },
  { phrase: "as long as", family: "condition" },
  { phrase: "provided that", family: "condition" },
  { phrase: "as a result", family: "result" },
  { phrase: "for example", family: "example" },
  { phrase: "in addition", family: "addition" },
  { phrase: "even though", family: "contrast" },
  { phrase: "even if", family: "concessive-condition" },
  { phrase: "given that", family: "cause" },
  { phrase: "moreover", family: "addition" },
  { phrase: "furthermore", family: "addition" },
  { phrase: "therefore", family: "result" },
  { phrase: "consequently", family: "result" },
  { phrase: "because", family: "cause" },
  { phrase: "although", family: "contrast" },
  { phrase: "however", family: "contrast" },
  { phrase: "whereas", family: "contrast" },
  { phrase: "though", family: "contrast" },
  // `while` and `since` are lexically ambiguous: each can carry a temporal
  // sense, while `while` can also contrast and `since` can give a reason.
  // Preserve the exact marker instead of guessing its sense in a rule-only
  // finalizer.
  { phrase: "while", family: "while" },
  { phrase: "since", family: "since" },
  { phrase: "when", family: "time-concurrent" },
  { phrase: "once", family: "time-after" },
  { phrase: "after", family: "time-after" },
  { phrase: "before", family: "time-before" },
  { phrase: "unless", family: "negative-condition" },
  { phrase: "also", family: "addition" },
  { phrase: "thus", family: "result" },
  { phrase: "but", family: "contrast" },
  { phrase: "yet", family: "contrast" },
  { phrase: "if", family: "condition" },
];

const VAGUE_SENTENCE_OPENERS = /^(?:it|this|that|they|these|those)\b/i;
const VERB_LIST_LEAD = /^(?:to|can|could|may|might|must|should|will|would)\b/i;

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function embeddedTransition(sentence: string): LeadingTransition | null {
  // Prefer the transition that appears first in the sentence. The previous
  // loop returned the first phrase in the transition table that happened to
  // match anywhere, so a later long phrase could hide an earlier relationship.
  // Longer phrases still win ties at the same character position.
  const ordered = [...LEADING_TRANSITIONS].sort((left, right) => right.phrase.length - left.phrase.length);
  let best: LeadingTransition | null = null;
  for (const transition of ordered) {
    const match = sentence.match(new RegExp(`\\b${escapeRegExp(transition.phrase).replace(/\s+/g, "\\s+")}\\b`, "i"));
    if (!match || match.index === undefined) continue;
    const candidate = {
      family: transition.family,
      text: match[0],
      start: match.index,
      end: match.index + match[0].length,
    } satisfies LeadingTransition;
    if (!best || candidate.start < best.start || (candidate.start === best.start && candidate.text.length > best.text.length)) {
      best = candidate;
    }
  }
  return best;
}

function relationClause(sentence: string, relation: LeadingTransition): string {
  const relationStart = sentence.slice(relation.start);
  const remainder = relationStart.slice(relation.text.length);
  const boundary = remainder.search(/[,.;!?]/);
  const clauseEnd = boundary >= 0
    ? relationStart.length - remainder.length + boundary
    : relationStart.length;
  return sentence.slice(relation.start, relation.start + clauseEnd).trim();
}

function restoreDroppedEmbeddedRelation(
  originalSentence: string,
  candidateSentence: string,
  originalRelation: LeadingTransition,
  candidateRelation: LeadingTransition | null,
): string {
  if (candidateRelation) return candidateSentence;

  const sourceClause = relationClause(originalSentence, originalRelation);
  const sourceContentWords = sourceClause
    .slice(originalRelation.text.length)
    .match(/[A-Za-z]{5,}/g)
    ?.map((word) => word.toLowerCase()) ?? [];
  const anchor = sourceContentWords.at(-1);
  if (!anchor || !new RegExp(`\\b${escapeRegExp(anchor)}\\b`, "i").test(candidateSentence)) {
    return candidateSentence;
  }

  const commaSegments = candidateSentence.split(",");
  const targetIndex = commaSegments.findIndex((segment, index) =>
    index > 0 && new RegExp(`\\b${escapeRegExp(anchor)}\\b`, "i").test(segment)
  );
  if (targetIndex < 0) return candidateSentence;

  const segment = commaSegments[targetIndex];
  const leadingWhitespace = segment.match(/^\s*/)?.[0] ?? "";
  const body = segment.slice(leadingWhitespace.length);
  const coordinatorMatch = body.match(/^(?:and|or|but)\s+/i);
  const leadingCoordinator = coordinatorMatch?.[0] ?? "";
  const remainder = body.slice(leadingCoordinator.length);
  if (!remainder.trim()) return candidateSentence;

  // Restore only the missing relationship marker. The previous implementation
  // replaced the candidate segment with the source clause and, for embedded
  // time clauses, invented the word “especially”. Prefixing the existing
  // candidate clause preserves its wording/details and cannot add emphasis
  // that was absent from the source.
  commaSegments[targetIndex] = `${leadingWhitespace}${leadingCoordinator}${originalRelation.text} ${remainder.replace(/^\s+/, "")}`;
  return commaSegments.join(",");
}

function leadingTransition(sentence: string): LeadingTransition | null {
  const leadingWhitespace = sentence.match(/^\s*/)?.[0].length ?? 0;
  const body = sentence.slice(leadingWhitespace);
  const normalizedBody = body.toLowerCase();

  const ordered = [...LEADING_TRANSITIONS].sort((left, right) => right.phrase.length - left.phrase.length);
  for (const transition of ordered) {
    const phrase = transition.phrase;
    const boundary = normalizedBody[phrase.length];
    if (
      normalizedBody === phrase ||
      (normalizedBody.startsWith(phrase) && (!boundary || /[\s,;:]/.test(boundary)))
    ) {
      return {
        family: transition.family,
        text: body.slice(0, phrase.length),
        start: leadingWhitespace,
        end: leadingWhitespace + phrase.length,
      };
    }
  }

  return null;
}

function inflectionForm(value: string): "base" | "ing" | "past" | "other" {
  const normalized = value.toLowerCase();
  if (normalized.endsWith("ing")) return "ing";
  if (normalized.endsWith("ed")) return "past";
  if (/^[a-z]+$/.test(normalized)) return "base";
  return "other";
}

function parallelStructureIssues(text: string): SentenceFlowIssue[] {
  const issues: SentenceFlowIssue[] = [];
  const seriesPattern = /\b((?:to|can|could|may|might|must|should|will|would)\s+)?([A-Za-z]+(?:ing|ed)?),\s+([A-Za-z]+(?:ing|ed)?),\s+and\s+([A-Za-z]+(?:ing|ed)?)\b/gi;
  let match: RegExpExecArray | null;

  while ((match = seriesPattern.exec(text)) !== null) {
    const forms = [match[2], match[3], match[4]].map(inflectionForm);
    const inflectedCount = forms.filter((form) => form === "ing" || form === "past").length;
    const hasVerbLead = Boolean(match[1]) && VERB_LIST_LEAD.test(match[1].trim());
    const mixedForms = new Set(forms).size > 1;

    // Only treat a list as verbal when a modal/infinitive introduces it or
    // enough items carry an unmistakable verb inflection. This avoids
    // flagging ordinary adjective lists such as "clear, direct, and simple."
    if (mixedForms && (hasVerbLead || inflectedCount >= 2)) {
      issues.push({
        id: "parallel-verb-series",
        detail: "Coordinate actions should use the same grammatical form throughout the series.",
      });
      break;
    }
  }

  return issues;
}

const GERUND_DOUBLING: Record<string, string> = {
  begin: "beginning",
  get: "getting",
  plan: "planning",
  put: "putting",
  run: "running",
  sit: "sitting",
  stop: "stopping",
  swim: "swimming",
  win: "winning",
};

function toGerund(value: string): string {
  const normalized = value.toLowerCase();
  const irregular = GERUND_DOUBLING[normalized];
  if (irregular) return value[0] === value[0].toUpperCase()
    ? irregular[0].toUpperCase() + irregular.slice(1)
    : irregular;
  if (normalized.endsWith("ing")) return value;
  if (normalized.endsWith("ie")) return `${value.slice(0, -2)}ying`;
  if (normalized.endsWith("e") && !/(?:ee|ye|oe)$/.test(normalized)) return `${value.slice(0, -1)}ing`;
  return `${value}ing`;
}

function repairParallelVerbSeries(text: string): string {
  // This is deliberately limited to verbs that select a gerund complement.
  // It repairs “likes reading, writing, and revise” without trying to infer
  // tense or rewrite arbitrary noun/adjective lists.
  return text.replace(
    /\b((?:likes?|enjoys?|keeps?|starts?|stops?|avoids?|finishes?|continues?|prefers?)\s+)([A-Za-z]+ing),\s+([A-Za-z]+ing),\s+and\s+([A-Za-z]+)\b/gi,
    (_match, lead: string, first: string, second: string, final: string) =>
      `${lead}${first}, ${second}, and ${toGerund(final)}`,
  );
}

export function analyzeSentenceFlow(original: string, candidate: string): SentenceFlowIssue[] {
  const issues: SentenceFlowIssue[] = [];
  const originalSentences = splitSentences(original);
  const candidateSentences = splitSentences(candidate);

  if (originalSentences.length !== candidateSentences.length) return issues;

  for (let index = 0; index < originalSentences.length; index += 1) {
    const originalSentence = originalSentences[index].text;
    const candidateSentence = candidateSentences[index].text;
    const originalLead = leadingTransition(originalSentence);
    const candidateLead = leadingTransition(candidateSentence);

    if (originalLead && candidateLead && originalLead.family !== candidateLead.family) {
      issues.push({
        id: "transition-relationship-drift",
        detail: "The sentence changed the relationship between ideas; keep the original causal, contrastive, temporal, or conditional link.",
      });
    }

    if (
      index > 0 &&
      VAGUE_SENTENCE_OPENERS.test(candidateSentence.trim()) &&
      !VAGUE_SENTENCE_OPENERS.test(originalSentence.trim())
    ) {
      issues.push({
        id: "vague-sentence-opening",
        detail: "The rewrite introduces a vague sentence opener instead of carrying forward a clear topic.",
      });
    }
  }

  issues.push(...parallelStructureIssues(candidate));
  return issues;
}

export function repairSentenceFlow(original: string, candidate: string): string {
  const originalSentences = splitSentences(original);
  const candidateSentences = splitSentences(candidate);
  let repaired = repairParallelVerbSeries(candidate);
  if (originalSentences.length !== candidateSentences.length) return repaired;

  // Preserve relationships inside a sentence as well as at its opening.
  // Native drafts often turn “when there are distractions” into “although
  // there are distractions” while keeping every content word; this is a
  // fluent sentence with the wrong logic, so restore the source transition.
  let repairedSentences = splitSentences(repaired);
  if (repairedSentences.length === originalSentences.length) {
    for (let index = repairedSentences.length - 1; index >= 0; index -= 1) {
      const originalRelation = embeddedTransition(originalSentences[index].text);
      const candidateRelation = embeddedTransition(repairedSentences[index].text);
      if (!originalRelation || !candidateRelation || originalRelation.family === candidateRelation.family) continue;
      const sentence = repaired.slice(repairedSentences[index].start, repairedSentences[index].end);
      const candidatePattern = new RegExp(escapeRegExp(candidateRelation.text), "i");
      const restoredSentence = sentence.replace(candidatePattern, originalRelation.text);
      repaired = repaired.slice(0, repairedSentences[index].start) + restoredSentence + repaired.slice(repairedSentences[index].end);
      repairedSentences = splitSentences(repaired);
    }

    for (let index = repairedSentences.length - 1; index >= 0; index -= 1) {
      const originalRelation = embeddedTransition(originalSentences[index].text);
      const candidateRelation = embeddedTransition(repairedSentences[index].text);
      if (!originalRelation) continue;

      const candidateSentence = repaired.slice(repairedSentences[index].start, repairedSentences[index].end);
      const restoredSentence = restoreDroppedEmbeddedRelation(
        originalSentences[index].text,
        candidateSentence,
        originalRelation,
        candidateRelation,
      );
      if (restoredSentence === candidateSentence) continue;

      repaired = repaired.slice(0, repairedSentences[index].start) + restoredSentence + repaired.slice(repairedSentences[index].end);
      repairedSentences = splitSentences(repaired);
    }
  }

  repairedSentences = splitSentences(repaired);

  for (let index = repairedSentences.length - 1; index >= 0; index -= 1) {
    const originalLead = leadingTransition(originalSentences[index].text);
    const candidateLead = leadingTransition(repairedSentences[index].text);
    if (!originalLead || !candidateLead || originalLead.family === candidateLead.family) continue;

    const sentence = repaired.slice(repairedSentences[index].start, repairedSentences[index].end);
    const nextSentence = originalLead.text + sentence.slice(candidateLead.end);
    repaired = repaired.slice(0, repairedSentences[index].start) + nextSentence + repaired.slice(repairedSentences[index].end);
  }

  return repaired;
}

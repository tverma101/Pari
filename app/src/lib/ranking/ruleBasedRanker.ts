import { preferredIndefiniteArticle } from "@/lib/nlp/articleSound";
import {
  detectAdjectiveDegree,
  detectNounNumber,
  detectVerbForm,
  morphologyCompatibility,
} from "@/lib/nlp/morphology";
import { grammarCompatibility } from "@/lib/nlp/posTagger";
import { isWarmthMode, type RewriteMode, type RiskLevel } from "@/lib/types";

import type { CandidateOption, RankingContext, RankingResult } from "./types";

const CLAIM_WARNING_MAP: Record<string, string> = {
  proves: "Stronger claim",
  guarantees: "Stronger claim",
  always: "Absolute claim",
  never: "Absolute claim",
  damages: "Negative meaning shift",
  destroys: "Strong negative shift",
  controls: "Stronger claim",
};

function riskPenalty(risk: RiskLevel): number {
  if (risk === "high") return 0.2;
  if (risk === "medium") return 0.08;
  return 0;
}

function modeFitBonus(mode: RewriteMode, option: CandidateOption): number {
  const replacementLength = option.replacement.length;
  const originalLength = option.original.length;

  if (option.modePreference?.includes(mode) || (isWarmthMode(mode) && option.modePreference?.includes("warm"))) return 0.16;

  switch (mode) {
    case "personal":
      return Math.abs(replacementLength - originalLength) <= 6 ? 0.09 : 0.05;
    case "simple":
      return replacementLength < originalLength ? 0.12 : -0.02;
    case "shorten":
      return replacementLength <= originalLength ? 0.14 : -0.04;
    case "expand":
      return replacementLength >= originalLength + 4 ? 0.18 : replacementLength > originalLength ? 0.08 : -0.04;
    case "warm":
    case "warmth":
      return 0.04;
    case "formal":
      return replacementLength >= originalLength ? 0.12 : 0;
    case "fluency":
      return Math.abs(replacementLength - originalLength) <= 3 ? 0.08 : 0;
    case "creative":
      return replacementLength >= originalLength ? 0.06 : 0.02;
    case "standard":
    default:
      return 0.05;
  }
}

function labelBonus(mode: RewriteMode, label?: string): number {
  if (!label) return 0;

  const normalized = label.toLowerCase();
  if (isWarmthMode(mode) && (normalized.includes("warm") || normalized.includes("friendly") || normalized.includes("casual") || normalized.includes("natural") || normalized.includes("soft"))) {
    return 0.16;
  }
  if (normalized.includes("natural")) return mode === "fluency" ? 0.14 : 0.1;
  if (normalized.includes("clear") || normalized.includes("balanced")) return 0.08;
  if (normalized === "context") return 0.06;
  if (normalized === "thesaurus") return 0.015;
  if (normalized === "related") return -0.04;
  if (normalized.includes("precise")) return 0.06;
  if ((mode === "simple" || mode === "shorten") && normalized.includes("simple")) return 0.1;
  if (mode === "formal" && normalized.includes("formal")) return 0.1;
  if (mode === "fluency" && (normalized.includes("natural") || normalized.includes("soft"))) {
    return 0.08;
  }
  if (mode === "expand" && (normalized.includes("expanded") || normalized.includes("detail") || normalized.includes("phrase"))) return 0.14;
  if (normalized.includes("expanded")) return -0.02;
  return 0;
}

function sourceFitBonus(mode: RewriteMode, option: CandidateOption): number {
  switch (option.source) {
    case "phrase-bank":
      return 0.06;
    case "static-bank":
      return 0.04;
    case "contextual-mlm":
      return mode === "creative" ? 0.03 : 0;
    case "wordnet":
      return mode === "personal" || isWarmthMode(mode) ? 0.1 : 0.03;
    case "thesaurus":
      return mode === "personal" ? 0.015 : 0;
    case "deep-bank":
      return mode === "creative" ? 0.01 : -0.06;
    case "generator":
      return mode === "creative" ? 0.02 : -0.03;
    default:
      return 0;
  }
}

const CONSERVATIVE_LABELS = new Set([
  "balanced",
  "clear",
  "compact",
  "concise",
  "context",
  "direct",
  "friendly",
  "natural",
  "plain",
  "quality",
  "simple",
  "shorter",
  "soft",
  "warm",
]);

const CONSERVATIVE_AMBIGUOUS_REPLACEMENTS = new Set([
  "although",
  "as",
  "bonds",
  "during",
  "folks",
  "follow",
  "if",
  "humans",
  "invited",
  "persons",
  "questioned",
  "sluggish",
  "some",
  "optimal",
  "unlike",
  "whereas",
  "while",
]);

function normalizedLabel(option: CandidateOption): string {
  return option.label?.trim().toLowerCase() ?? "";
}

</**
 * Automatic paragraph output uses a safer candidate set than the inline
 * chooser. Even the aggressive pass stays on the curated, low-risk bank;
 * deeper discovery candidates remain manual-only because they are not safe to
 * combine word-by-word without a language model.
 */
export function isConservativeAutomaticCandidate(
  option: CandidateOption,
  mode: RewriteMode,
): boolean {
  if ((option.risk ?? "low") !== "low") return false;
  if (CONSERVATIVE_AMBIGUOUS_REPLACEMENTS.has(option.replacement.trim().toLowerCase())) return false;
  if (option.source === "deep-bank" || option.source === "wordnet" || option.source === "thesaurus" || option.source === "generator" || option.source === "contextual-mlm") {
    return false;
  }

  const label = normalizedLabel(option);
  if (mode === "personal" || mode === "standard" || mode === "fluency") {
    return CONSERVATIVE_LABELS.has(label) || option.source === "phrase-bank";
  }
  if (isWarmthMode(mode)) {
    return /^(?:warm|natural|soft|friendly|clear|balanced|plain)$/.test(label) || option.source === "phrase-bank";
  }
  if (mode === "formal") {
    return /^(?:formal|precise|clear|balanced|natural|concise)$/.test(label) || option.source === "phrase-bank";
  }
  if (mode === "simple") {
    return /^(?:simple|plain|clear|shorter|compact|concise|natural)$/.test(label) || option.source === "phrase-bank";
  }
  if (mode === "shorten") {
    return /^(?:shorter|compact|simple|plain|clear|concise)$/.test(label) || option.source === "phrase-bank";
  }
  if (mode === "expand") {
    return /^(?:expanded|detail|more detail|phrase|natural|clear|balanced)$/.test(label) || option.source === "phrase-bank";
  }
  return /^(?:natural|warm|soft|clear|balanced|quality|concise|simple)$/.test(label) || option.source === "phrase-bank";
}

/**
 * A wider automatic set for Strong/Deep fallback passes. It still excludes
 * high-risk and discovery-only candidates; the word-level context veto and
 * paragraph quality/meaning gates remain mandatory after selection. This is
 * intentionally less conservative than the normal paragraph policy without
 * turning the static fallback into an unchecked thesaurus.
 */
export function isBroadAutomaticCandidate(
  option: CandidateOption,
  mode: RewriteMode,
): boolean {
  if (isConservativeAutomaticCandidate(option, mode)) return true;
  if ((option.risk ?? "low") !== "low") return false;
  if (CONSERVATIVE_AMBIGUOUS_REPLACEMENTS.has(option.replacement.trim().toLowerCase())) return false;
  if (option.source === "phrase-bank") return true;

  const label = normalizedLabel(option);
  const broadLabels = new Set([
    "formal",
    "more formal",
    "contextual",
    "expanded",
    "shorter",
    "precise",
  ]);
  if (option.source === "static-bank" && broadLabels.has(label)) return true;

  // Deep-bank entries are discovery material rather than a curated
  // paragraph-rewrite vocabulary. Keep them visible to the inline chooser,
  // but do not apply them automatically: its broad list contains role changes
  // such as client -> peer and noun substitutions that are grammatical while
  // still changing the user's claim.
  return false;
}

function articleBeforeSelection(context: RankingContext): "a" | "an" | "the" | null {
  if (typeof context.selectionStart !== "number") return null;

  const before = context.fullText.slice(0, context.selectionStart);
  const match = before.match(/\b(a|an|the)\s+$/i);
  if (!match) return null;
  return match[1].toLowerCase() as "a" | "an" | "the";
}

function articleFitPenalty(option: CandidateOption, context: RankingContext): number {
  const article = articleBeforeSelection(context);
  if (!article) return 0;

  const replacement = option.replacement.trim();
  const normalized = replacement.toLowerCase();
  let penalty = 0;

  if (/^(a|an|the|one|another|someone|somebody)\b/.test(normalized)) {
    penalty += 0.34;
  }

  if (article === "a" || article === "an") {
    const expected = preferredIndefiniteArticle(replacement);
    if (expected && article !== expected) penalty += 0.2;
  }

  if ((article === "a" || article === "an") && detectNounNumber(replacement) === "plural") {
    penalty += 0.26;
  }

  return penalty;
}

function specificityPenalty(option: CandidateOption, context: RankingContext): number {
  const original = context.selectedText.trim().toLowerCase();
  const replacement = option.replacement.trim().toLowerCase();

  if (original === "person" || original === "people") {
    if (
      /\b(child|adult|student|worker|resident|citizen|client|customer|patient|employee|reader|learner|user)\b/.test(
        replacement
      )
    ) {
      return 0.18;
    }
  }

  if (original === "user" || original === "users") {
    if (/\b(writer|writers|learner|learners|operator|operators|reader|readers)\b/.test(replacement)) {
      return 0.18;
    }
  }

  return 0;
}

function selectionLocalRange(context: RankingContext): { start: number; end: number } | null {
  if (
    typeof context.selectionStart !== "number" ||
    typeof context.selectionEnd !== "number" ||
    typeof context.sentenceStart !== "number"
  ) {
    return null;
  }

  return {
    start: Math.max(0, context.selectionStart - context.sentenceStart),
    end: Math.max(0, context.selectionEnd - context.sentenceStart),
  };
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function wordBeforeSelection(context: RankingContext): string | null {
  const range = selectionLocalRange(context);
  if (!range) return null;

  const before = context.sentence.slice(0, range.start);
  const match = before.match(/\b([A-Za-z]+(?:[-'][A-Za-z]+)?)\s*$/);
  return match ? match[1].toLowerCase() : null;
}

function wordsAfterSelection(context: RankingContext, limit = 3): string[] {
  const range = selectionLocalRange(context);
  if (!range) return [];
  return (context.sentence.slice(range.end).match(/[A-Za-z]+(?:[-'][A-Za-z]+)?/g) ?? [])
    .slice(0, limit)
    .map((word) => word.toLowerCase());
}

function wordAfterSelection(context: RankingContext): string | null {
  return wordsAfterSelection(context, 1)[0] ?? null;
}

function replacementBoundaryWords(replacement: string): { first: string | null; last: string | null } {
  const words = replacement.toLowerCase().match(/[a-z]+(?:[-'][a-z]+)*/g) ?? [];
  return { first: words[0] ?? null, last: words[words.length - 1] ?? null };
}

function sentenceDuplicatePenalty(option: CandidateOption, context: RankingContext): number {
  const range = selectionLocalRange(context);
  const replacement = option.replacement.trim().toLowerCase();
  if (!range || replacement.length < 4) return 0;

  const remainingSentence = `${context.sentence.slice(0, range.start)} ${context.sentence.slice(range.end)}`.toLowerCase();
  const words = replacement.match(/[a-z]+(?:[-'][a-z]+)*/g) ?? [];
  if (words.length === 0) return 0;

  const pattern =
    words.length === 1
      ? new RegExp(`\\b${escapeRegExp(words[0])}\\b`)
      : new RegExp(`\\b${escapeRegExp(replacement).replace(/\s+/g, "\\s+")}\\b`);

  return pattern.test(remainingSentence) ? 0.28 : 0;
}

const COMPARISON_LINK_WORDS = new Set(["as", "to", "from", "than"]);
const COMPARISON_LINKS: Record<string, ReadonlySet<string>> = {
  similar: new Set(["to"]),
  same: new Set(["as"]),
  different: new Set(["from", "than", "to"]),
  distinct: new Set(["from"]),
};

function comparisonLinkPenalty(context: RankingContext, replacement: string): number {
  const previous = wordBeforeSelection(context);
  if (!previous) return 0;

  const allowed = COMPARISON_LINKS[previous];
  if (!allowed) return 0;

  const selectedWord = context.selectedText.trim().toLowerCase().match(/^[a-z]+/)?.[0] ?? "";
  const replacementWord = replacement.match(/^[a-z]+/)?.[0] ?? "";

  if (!COMPARISON_LINK_WORDS.has(selectedWord) && !COMPARISON_LINK_WORDS.has(replacementWord)) {
    return 0;
  }

  return allowed.has(replacementWord) ? 0 : 0.24;
}

const SINGULAR_DETERMINERS = new Set(["a", "an", "another", "each", "every", "one", "that", "this"]);
const PLURAL_DETERMINERS = new Set(["both", "few", "many", "multiple", "numerous", "several", "these", "those"]);
const MODAL_AUXILIARIES = new Set(["can", "could", "may", "might", "must", "shall", "should", "will", "would"]);
const BE_AUXILIARIES = new Set(["am", "are", "be", "been", "being", "is", "was", "were"]);
const HAVE_AUXILIARIES = new Set(["had", "has", "have"]);
const PREPOSITIONS = new Set(["about", "at", "by", "for", "from", "in", "into", "of", "on", "through", "to", "with"]);

function morphologyFitPenalty(option: CandidateOption, context: RankingContext): number {
  const partOfSpeech = context.partOfSpeech ?? option.partOfSpeech ?? "unknown";
  const compatibility = morphologyCompatibility(context.selectedText, option.replacement, partOfSpeech);
  return (1 - compatibility) * 0.42;
}

/**
 * Generic surface-slot constraints. These are intentionally about English
 * grammar classes rather than topics or named vocabulary, so one rule covers
 * many domains and unseen words.
 */
function surfaceSlotPenalty(option: CandidateOption, context: RankingContext): number {
  const partOfSpeech = context.partOfSpeech ?? option.partOfSpeech ?? "unknown";
  const previous = wordBeforeSelection(context);
  const following = wordsAfterSelection(context, 2);
  const next = following[0] ?? null;
  const { first, last } = replacementBoundaryWords(option.replacement);
  let penalty = 0;

  if (previous && first === previous) penalty += 0.22;
  if (next && last === next) penalty += 0.22;
  if (next && last && PREPOSITIONS.has(next) && PREPOSITIONS.has(last)) penalty += 0.18;

  if (partOfSpeech === "noun" && previous) {
    const number = detectNounNumber(option.replacement);
    if (SINGULAR_DETERMINERS.has(previous) && number === "plural") penalty += 0.3;
    if (PLURAL_DETERMINERS.has(previous) && number === "singular") penalty += 0.28;
  }

  if (partOfSpeech === "verb" && previous) {
    const sourceForm = detectVerbForm(context.selectedText);
    const replacementForm = detectVerbForm(option.replacement);
    if (MODAL_AUXILIARIES.has(previous) && replacementForm !== "base") penalty += 0.34;
    if (previous === "to" && replacementForm !== "base") penalty += 0.3;
    if (BE_AUXILIARIES.has(previous) && sourceForm === "gerund" && replacementForm !== "gerund") penalty += 0.32;
    if (HAVE_AUXILIARIES.has(previous) && sourceForm === "past" && replacementForm !== "past") penalty += 0.3;
  }

  if (partOfSpeech === "adjective" && next === "than") {
    if (detectAdjectiveDegree(option.replacement) !== "comparative") penalty += 0.28;
  }

  return penalty;
}

function localGrammarPenalty(option: CandidateOption, context: RankingContext): number {
  const replacement = option.replacement.trim().toLowerCase();
  const previous = wordBeforeSelection(context);
  const next = wordAfterSelection(context);
  let penalty = 0;

  if (
    previous &&
    /^(about|of|for|by|with|to|from)$/.test(previous) &&
    /^(as|in|from|through|using|according|on|by|for|at|with)\b/.test(replacement)
  ) {
    penalty += 0.24;
  }

  if (
    next === "of" &&
    /^(see|regard|consider|perceive|interpret|understand|look at|take|read|judge|assess|frame|treat|think)\b/.test(
      replacement
    )
  ) {
    penalty += 0.3;
  }

  if (
    next === "than" &&
    /^(superior|improved|enhanced|refined|upgraded|better developed|better formed)\b/.test(replacement)
  ) {
    penalty += 0.26;
  }

  if (
    previous &&
    /^(feel|feels|felt|feeling)$/.test(previous) &&
    next === "about" &&
    /^(beneficial|constructive|helpful|useful|valuable|worthwhile|effective|advantageous|productive)\b/.test(
      replacement
    )
  ) {
    penalty += 0.22;
  }

  penalty += comparisonLinkPenalty(context, replacement);
  penalty += surfaceSlotPenalty(option, context);

  return penalty;
}

function buildWarnings(option: CandidateOption): string[] {
  const warnings: string[] = [];
  const normalized = option.replacement.toLowerCase();

  if (option.risk === "high") {
    warnings.push(CLAIM_WARNING_MAP[normalized] ?? "High meaning drift risk");
  } else if (option.risk === "medium") {
    warnings.push(CLAIM_WARNING_MAP[normalized] ?? "Moderate meaning drift risk");
  }

  return warnings;
}

export function rankCandidatesByRule(
  options: CandidateOption[],
  context: RankingContext
): RankingResult[] {
  return options
    .map((option) => {
      const grammarScore = grammarCompatibility(context.partOfSpeech ?? "unknown", option.replacement);
      const base = 0.54;
      const score =
        base +
        modeFitBonus(context.mode, option) +
        labelBonus(context.mode, option.label) +
        sourceFitBonus(context.mode, option) +
        (grammarScore - 0.5) * 0.38 -
        morphologyFitPenalty(option, context) -
        riskPenalty(option.risk ?? "low") -
        articleFitPenalty(option, context) -
        specificityPenalty(option, context) -
        sentenceDuplicatePenalty(option, context) -
        localGrammarPenalty(option, context);

      return {
        option,
        score,
        grammarScore,
        risk: option.risk ?? "low",
        warnings: buildWarnings(option),
      };
    })
    .sort((left, right) => {
      if (right.score !== left.score) return right.score - left.score;
      if (left.risk !== right.risk) {
        const order: Record<RiskLevel, number> = { low: 0, medium: 1, high: 2 };
        return order[left.risk] - order[right.risk];
      }
      return left.option.replacement.localeCompare(right.option.replacement);
    });
}

export function pickAutomaticCandidate(
  ranked: RankingResult[],
  mode: RewriteMode,
  seed: string
): CandidateOption | null {
  if (ranked.length === 0) return null;
  void seed;
  void mode;
  return ranked[0].option;
}

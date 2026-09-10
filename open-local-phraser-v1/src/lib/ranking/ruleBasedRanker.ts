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

// These are legitimate dictionary relationships in some contexts, but they
// are too ambiguous for an automatic word-by-word paragraph pass. They stay
// available in the inline chooser where the writer can inspect the sentence.
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

/**
 * Automatic paragraph output needs a smaller, safer candidate set than the
 * inline chooser. Deep clusters are useful for discovery but are not
 * reliable enough to combine word-by-word without a language model.
 */
export function isConservativeAutomaticCandidate(
  option: CandidateOption,
  mode: RewriteMode
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

function articleBeforeSelection(context: RankingContext): "a" | "an" | "the" | null {
  if (typeof context.selectionStart !== "number") return null;

  const before = context.fullText.slice(0, context.selectionStart);
  const match = before.match(/\b(a|an|the)\s+$/i);
  if (!match) return null;
  return match[1].toLowerCase() as "a" | "an" | "the";
}

function startsWithVowelSound(value: string): boolean {
  const normalized = value.trim().toLowerCase();
  if (!normalized) return false;

  // Indefinite articles follow pronunciation, not spelling. Keep this list
  // intentionally small and high-confidence so the rule ranker does not try
  // to infer pronunciation for arbitrary acronyms or names.
  if (/^(?:honest|honor|honour|hour|heir|herb)\b/.test(normalized)) return true;
  if (/^(?:ewe|euro|one|once|uniform|unique|unit|united|university|use|useful|usefully|user|usual)\b/.test(normalized)) {
    return false;
  }

  return /^[aeiou]/.test(normalized);
}

function looksPluralNoun(value: string): boolean {
  const normalized = value.trim().toLowerCase();
  if (normalized.includes(" ")) return false;
  if (/(ss|us|is)$/.test(normalized)) return false;
  return normalized.endsWith("s");
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

  if (article === "a" && startsWithVowelSound(replacement)) {
    penalty += 0.2;
  }

  if (article === "an" && !startsWithVowelSound(replacement)) {
    penalty += 0.2;
  }

  if ((article === "a" || article === "an") && looksPluralNoun(replacement)) {
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

function wordAfterSelection(context: RankingContext): string | null {
  const range = selectionLocalRange(context);
  if (!range) return null;

  const after = context.sentence.slice(range.end);
  const match = after.match(/^\s*([A-Za-z]+(?:[-'][A-Za-z]+)?)/);
  return match ? match[1].toLowerCase() : null;
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

  // Only police the comparison link itself. The old rule penalized every
  // replacement after words such as “same” or “different”, so a harmless
  // noun rewrite like “the same process” -> “the same method” lost 0.24.
  if (!COMPARISON_LINK_WORDS.has(selectedWord) && !COMPARISON_LINK_WORDS.has(replacementWord)) {
    return 0;
  }

  return allowed.has(replacementWord) ? 0 : 0.24;
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

import { grammarCompatibility } from "@/lib/nlp/posTagger";
import type { RewriteMode, RiskLevel } from "@/lib/types";

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

  if (option.modePreference?.includes(mode)) return 0.16;

  switch (mode) {
    case "simple":
      return replacementLength < originalLength ? 0.12 : -0.02;
    case "shorten":
      return replacementLength <= originalLength ? 0.14 : -0.04;
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
  if (normalized.includes("natural")) return mode === "fluency" ? 0.14 : 0.1;
  if (normalized.includes("clear") || normalized.includes("balanced")) return 0.08;
  if (normalized.includes("precise")) return 0.06;
  if ((mode === "simple" || mode === "shorten") && normalized.includes("simple")) return 0.1;
  if (mode === "formal" && normalized.includes("formal")) return 0.1;
  if (mode === "fluency" && (normalized.includes("natural") || normalized.includes("soft"))) {
    return 0.08;
  }
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
    case "deep-bank":
      return mode === "creative" ? 0.01 : -0.06;
    case "generator":
      return mode === "creative" ? 0.02 : -0.03;
    default:
      return 0;
  }
}

function articleBeforeSelection(context: RankingContext): "a" | "an" | "the" | null {
  if (typeof context.selectionStart !== "number") return null;

  const before = context.fullText.slice(0, context.selectionStart);
  const match = before.match(/\b(a|an|the)\s+$/i);
  if (!match) return null;
  return match[1].toLowerCase() as "a" | "an" | "the";
}

function startsWithVowelSound(value: string): boolean {
  return /^[aeiou]/i.test(value.trim());
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

  if (previous && /^(similar|alike|same|different|distinct)$/.test(previous) && replacement !== "since") {
    penalty += 0.24;
  }

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

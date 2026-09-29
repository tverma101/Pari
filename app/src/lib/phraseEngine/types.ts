import type { CandidateOption } from "@/lib/ranking/types";
import type { PartOfSpeech, RiskLevel, RewriteMode } from "@/lib/types";

export interface RewriteSettingsInput {
  mode: RewriteMode;
  strength: number;
  freezeWords: string;
  disableAutomaticRewrites?: boolean;
  /**
   * Paragraph generation uses a stricter automatic policy than the inline
   * word picker. Keep this opt-in so the picker can still expose the wider
   * synonym bank without making the generated draft sound mechanical.
   */
  automaticRewriteStrategy?: "default" | "conservative" | "broad";
  /** Maximum automatic replacements allowed in one sentence. */
  automaticRewriteBudget?: number;
}

export interface RewriteToken {
  id: string;
  text: string;
  originalText: string;
  isWord: boolean;
  isPhrase: boolean;
  alternatives: CandidateOption[];
  selectedAlternativeId: string | null;
  changed: boolean;
  frozen: boolean;
  start: number;
  end: number;
  partOfSpeech: PartOfSpeech;
  source: "text" | "static-bank" | "deep-bank" | "phrase-bank" | "rule" | "wordnet" | "thesaurus" | "contextual-mlm" | "generator";
  label?: string;
  risk: RiskLevel;
  warnings: string[];
  originalStart: number;
  originalEnd: number;
}

export interface RewriteResult {
  tokens: RewriteToken[];
  outputText: string;
  changedCount: number;
  frozenCount: number;
  candidateCount: number;
}

export type ManualChoiceMap = Record<string, string | null>;

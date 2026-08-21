import type { PartOfSpeech, RewriteMode, RiskLevel, StrengthLevel } from "@/lib/types";

export type CandidateSource =
  | "static-bank"
  | "deep-bank"
  | "phrase-bank"
  | "rule"
  | "wordnet"
  | "thesaurus"
  | "contextual-mlm"
  | "generator";

export type RankingProvider = "rule-based" | "embedding";

export type SemanticModelId =
  | "Xenova/paraphrase-mpnet-base-v2"
  | "Xenova/paraphrase-MiniLM-L6-v2"
  | "Xenova/all-mpnet-base-v2"
  | "Xenova/bge-base-en-v1.5"
  | "Xenova/bge-small-en-v1.5"
  | "Xenova/all-MiniLM-L6-v2"
  | "Xenova/all-MiniLM-L12-v2";

export type EntityGuardModelId = "Xenova/bert-base-NER";

export type ModelStatus = "not-loaded" | "downloading" | "loading" | "ready" | "failed";

export type ModelSource = "bundled" | "remote-cache" | "missing";

export type CandidateOption = {
  id: string;
  original: string;
  replacement: string;
  label?: string;
  source: CandidateSource;
  risk?: RiskLevel;
  partOfSpeech?: PartOfSpeech;
  modePreference?: RewriteMode[];
};

export type RankingContext = {
  fullText: string;
  sentence: string;
  selectedText: string;
  mode: RewriteMode;
  strength: StrengthLevel;
  freezeWords: string[];
  partOfSpeech?: PartOfSpeech;
  selectionStart?: number;
  selectionEnd?: number;
  sentenceStart?: number;
};

export type RankingResult = {
  option: CandidateOption;
  score: number;
  semanticScore?: number;
  grammarScore?: number;
  risk: RiskLevel;
  warnings: string[];
};

export type ModelInfo = {
  id: SemanticModelId;
  source: ModelSource;
  status: ModelStatus;
  lastError?: string;
  loadTimeMs?: number;
  vectorDimensions?: number;
};

export type SemanticSelfTestResult = {
  modelId: SemanticModelId;
  passed: boolean;
  vectorDimensions: number;
  loadTimeMs: number;
  similarity12: number;
  similarity13: number;
  source: ModelSource;
  errorMessage?: string;
};

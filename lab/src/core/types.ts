/* ===== Protected Span Types ===== */

export interface ProtectedSpan {
  id: string;
  type: ProtectedSpanType;
  originalText: string;
  placeholder: string;
  startOffset: number;
  endOffset: number;
  checksum: string;
  restored: boolean;
}

export type ProtectedSpanType =
  | "quote"
  | "entity_name"
  | "number"
  | "date"
  | "percentage"
  | "currency"
  | "url"
  | "email"
  | "citation"
  | "course_code"
  | "title"
  | "acronym"
  | "other";

/* ===== Protection Input/Output ===== */

export interface ProtectionResult {
  protectedText: string;
  spans: ProtectedSpan[];
  restoration: RestorationMap;
}

export interface ProtectionInput {
  text: string;
  options?: ProtectionOptions;
}

export interface ProtectionOptions {
  detectQuotes?: boolean;
  detectNames?: boolean;
  detectNumbers?: boolean;
  detectDates?: boolean;
  detectPercentages?: boolean;
  detectCurrencies?: boolean;
  detectUrls?: boolean;
  detectEmails?: boolean;
  detectCitations?: boolean;
  detectCourseCodes?: boolean;
  detectTitles?: boolean;
  detectAcronyms?: boolean;
}

export type RestorationMap = Map<string, ProtectedSpan>;

/* ===== Sentence Types ===== */

export interface SentenceSpan {
  text: string;
  start: number;
  end: number;
  index: number;
}

/* ===== Generation Types ===== */

export type GenerationLane = "conservative" | "natural" | "structure" | "cleanup";

export type ModelId = string;

export interface ModelInfo {
  id: ModelId;
  name: string;
  type: "t5" | "bart" | "flan-t5" | "mlx" | "synonym_bank";
  localPath?: string;
  supportedLanes: GenerationLane[];
  expectedLatency: "fast" | "medium" | "slow";
  ramEstimate: string;
  loaded: boolean;
  loadTime?: number;
}

export interface GenerationSettings {
  model: ModelId;
  lane: GenerationLane;
  numBeams: number;
  numReturnSequences: number;
  doSample: boolean;
  temperature: number;
  topK: number;
  topP: number;
  repetitionPenalty: number;
  maxLength: number;
  minLength: number;
}

export interface Candidate {
  id: string;
  originalSentence: string;
  protectedSentence: string;
  protectedCandidate: string;
  restoredCandidate: string;
  sourceModel: ModelId;
  generationLane: GenerationLane;
  generationSettings: GenerationSettings;
  timingMs: number;
  rejectionReason: string | null;
  accepted: boolean;
  scores: CandidateScores | null;
}

/* ===== Scoring Types ===== */

export interface CandidateScores {
  semanticSimilarity: number;
  nliScore: number;
  naturalness: number;
  grammarScore: number;
  lexicalDifference: number;
  structureDifference: number;
  preferenceBonus: number;
  professorPenalty: number;
  banwordPenalty: number;
  finalScore: number;
  subScores: Record<string, number>;
}

export interface HardRejectionRule {
  name: string;
  check: (candidate: Candidate, original: string, spans: ProtectedSpan[]) => boolean;
  description: string;
}

/* ===== Preference Types ===== */

export interface PreferenceProfile {
  id: string;
  name: string;
  hardBannedWords: string[];
  softDislikedWords: string[];
  preferredReplacements: Record<string, string[]>;
  formalityTarget: number; // 0 = very informal, 1 = neutral, 2 = formal
  lexicalDiversityTarget: number; // 0–1 target
  structureChangeTarget: number; // 0–1 target
  sentenceLengthTarget: "shorter" | "same" | "longer";
  professorPenaltyWeight: number;
}

export interface FeedbackEvent {
  timestamp: string;
  type: FeedbackType;
  originalText: string;
  candidateText: string;
  token?: string;
  replacement?: string;
  metadata?: Record<string, unknown>;
}

export type FeedbackType =
  | "accepted"
  | "rejected"
  | "too_formal"
  | "too_weird"
  | "too_close"
  | "changed_meaning"
  | "too_long"
  | "too_short"
  | "use_this_style_more"
  | "never_use_this_word"
  | "prefer_this_replacement";

/* ===== Alternatives Types ===== */

export interface TokenAlternative {
  text: string;
  type: AlternativeType;
  contextSafe: boolean;
  semanticScore: number;
  naturalnessScore: number;
  professorPenalty: number;
  notes: string;
}

export type AlternativeType =
  | "true_synonym"
  | "near_synonym"
  | "simpler_word"
  | "contextual_replacement"
  | "phrase_rewrite"
  | "not_recommended";

export interface AlternativesResult {
  token: string;
  tokenIndex: number;
  editable: boolean;
  protected: boolean;
  partOfSpeech: string;
  alternatives: TokenAlternative[];
}

/* ===== Core API Types ===== */

export interface RewriteRequest {
  text: string;
  model?: ModelId;
  lane?: GenerationLane;
  numCandidates?: number;
  profileId?: string;
  options?: RewriteOptions;
}

export interface RewriteOptions {
  numCandidatesPerLane?: number;
  profileId?: string;
  generateAlternatives?: boolean;
}

export interface RewriteResult {
  originalText: string;
  protectedText: string;
  restoredText: string;
  sentences: SentenceSpan[];
  candidates: Candidate[];
  acceptedCandidates: Candidate[];
  bestCandidate: Candidate | null;
  timing: RewriteTiming;
  protection: ProtectionResult;
  warnings: string[];
}

export interface RewriteTiming {
  protectionMs: number;
  sentenceSplittingMs: number;
  generationMs: number;
  scoringMs: number;
  totalMs: number;
}

/* ===== Report Types ===== */

export interface ModelBenchmark {
  modelId: ModelId;
  modelName: string;
  coldLoadTimeMs: number;
  warmGenerationTimeMs: number;
  averageSentenceLatencyMs: number;
  averageParagraphLatencyMs: number;
  candidatesPerSecond: number;
  memoryEstimate: string;
  outputRejectionRate: number;
  quotePreservationRate: number;
  entityPreservationRate: number;
  numberPreservationRate: number;
  averageSemanticSimilarity: number;
  averageLexicalDifference: number;
  averageProfessorPenalty: number;
  manualNotes: string;
}

export interface StressTestResult {
  testName: string;
  category: string;
  input: string;
  candidates: Candidate[];
  acceptedCount: number;
  passed: boolean;
  failures: string[];
  warnings: string[];
  timingMs: number;
}

export interface AlternativeTestResult {
  sentence: string;
  tokenTests: AlternativeTokenTest[];
}

export interface AlternativeTokenTest {
  token: string;
  expectedEditable: boolean;
  expectedProtected: boolean;
  expectedAlternativesCount: number;
  actualAlternativesCount: number;
  hasTopAlternatives: boolean;
  passed: boolean;
  failures: string[];
}

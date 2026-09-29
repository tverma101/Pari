/**
 * Local English-quality and meaning judge (Issue #7).
 *
 * The production score is deliberately split into independent signals:
 * - DeBERTa-v3-xsmall NLI provides a learned meaning/contradiction signal.
 * - DistilBERT masked-LM pseudo-perplexity provides a learned fluency signal.
 * - deterministic NLI/clause/protection rails remain hard safety checks.
 *
 * If a learned asset is unavailable, the result says so through
 * `learnedNli`/`learnedFluency` and falls back to bounded rails. It never
 * labels a fallback score as learned confidence.
 */

export type EntailmentLabel = "entail" | "neutral" | "contradict";

export interface EnglishQualityAssessment {
  /** 0..1 — higher is better for candidate ranking. */
  englishQualityScore: number;
  /** 0..1 learned masked-LM fluency when available. */
  fluencyScore: number;
  /** Hard contradiction means the candidate must not pass. */
  entailment: EntailmentLabel;
  /** True when either learned signal actually ran. */
  learned: boolean;
  /** Explicit availability states for evaluator/runtime diagnostics. */
  learnedNli: boolean;
  learnedFluency: boolean;
  /** Short reason suitable for benchmark reports and logs. */
  reason: string;
}

export interface EnglishQualityOptions {
  /** Test/adapter injection for a local NLI implementation. */
  nli?: {
    score: (premise: string, hypothesis: string) => Promise<{
      label: EntailmentLabel;
      score: number;
      reason?: string;
      hardContradiction?: boolean;
    }>;
  } | null;
  /** Legacy test/adapter injection for a perplexity implementation. */
  fluency?: {
    perplexity: (text: string) => Promise<number>;
  } | null;
}

function clamp(value: number, min = 0, max = 1): number {
  return Math.min(max, Math.max(min, value));
}

function structuralFluency(input: string, output: string): { score: number; reason: string } {
  const inputWords = input.split(/\s+/).filter(Boolean).length;
  const outputWords = output.split(/\s+/).filter(Boolean).length;
  const lengthRatio = outputWords / Math.max(1, inputWords);
  let lengthScore = 1;
  if (lengthRatio < 0.6 || lengthRatio > 1.6) lengthScore = 0.6;
  else if (lengthRatio < 0.8 || lengthRatio > 1.35) lengthScore = 0.85;

  const tokens = output.toLowerCase().match(/[a-z]+/g) ?? [];
  const bigrams = new Set<string>();
  for (let index = 0; index < tokens.length - 1; index += 1) {
    bigrams.add(`${tokens[index]} ${tokens[index + 1]}`);
  }
  const distinctBigrams = tokens.length > 1 ? bigrams.size / (tokens.length - 1) : 1;
  const diversityScore = distinctBigrams < 0.5 ? 0.5 : distinctBigrams < 0.7 ? 0.75 : 1;
  return {
    score: 0.6 * lengthScore + 0.4 * diversityScore,
    reason: `structural length=${lengthRatio.toFixed(2)} distinct2=${distinctBigrams.toFixed(2)}`,
  };
}

function canonicalFormatting(text: string): string {
  return text
    .toLowerCase()
    .replace(/[’]/g, "'")
    .replace(/\s+/g, " ")
    .replace(/(\d)\s+(?=[a-z])/g, "$1")
    .replace(/([a-z])\s+(?=\d)/g, "$1")
    .replace(/\s+([.,;:!?])/g, "$1")
    .trim();
}

function entailmentScore(label: EntailmentLabel, confidence: number): number {
  if (label === "contradict") return 0;
  if (label === "entail") return clamp(0.65 + 0.35 * confidence);
  return 0.72;
}

function assessment(
  entailment: EntailmentLabel,
  nliConfidence: number,
  fluencyScore: number,
  learnedNli: boolean,
  learnedFluency: boolean,
  reason: string
): EnglishQualityAssessment {
  const hardContradiction = entailment === "contradict";
  const englishQualityScore = hardContradiction
    ? 0
    : 0.4 * entailmentScore(entailment, nliConfidence) + 0.6 * clamp(fluencyScore);
  return {
    englishQualityScore,
    fluencyScore: clamp(fluencyScore),
    entailment,
    learned: learnedNli || learnedFluency,
    learnedNli,
    learnedFluency,
    reason,
  };
}

/**
 * Run the bundled DeBERTa + masked-LM path. The optional NLI function keeps
 * this boundary easy to exercise with a deterministic test double.
 */
export async function assessEnglishQualityWithOnnx(
  input: string,
  output: string,
  scoreNliBi?: (premise: string, hypothesis: string) => Promise<{
    label: EntailmentLabel;
    score: number;
    reason: string;
    hardContradiction?: boolean;
  }>
): Promise<EnglishQualityAssessment> {
  const trimmed = output.trim();
  if (!trimmed) {
    return assessment("contradict", 1, 0, false, false, "empty output");
  }

  let nliLabel: EntailmentLabel = "neutral";
  let nliConfidence = 0.5;
  let learnedNli = false;
  let hardContradiction = false;
  let nliReason = "nli unavailable";

  try {
    const scorer = scoreNliBi ?? (await import("./onnxNli")).scoreNliBidirectional;
    const result = await scorer(input, trimmed);
    nliLabel = result.label;
    nliConfidence = result.score;
    hardContradiction = result.hardContradiction ?? (result.label === "contradict" && result.score >= 0.6);
    learnedNli = true;
    nliReason = result.reason;
  } catch (error) {
    nliReason = `nli unavailable: ${error instanceof Error ? error.message : String(error)}`;
  }

  // Rails are still authoritative when the learned model is confident in the
  // wrong direction or when the learned asset cannot be loaded.
  try {
    const rail = await (await import("./nliJudge")).createRuleNliJudge().judge(input, trimmed);
    if (rail.label === "contradict") {
      hardContradiction = true;
      nliLabel = "contradict";
      nliConfidence = Math.max(nliConfidence, rail.score);
      nliReason = `${rail.reason}; ${nliReason}`;
    }
  } catch (error) {
    nliReason += `; rails unavailable: ${error instanceof Error ? error.message : String(error)}`;
  }

  const structural = structuralFluency(input, trimmed);
  let fluencyScore = structural.score;
  let fluencyReason = structural.reason;
  let learnedFluency = false;
  try {
    const result = await (await import("./fluencyMlm")).scoreMaskedLmFluency(trimmed);
    fluencyScore = result.score;
    fluencyReason = result.reason;
    learnedFluency = result.tokenCount > 0;
  } catch (error) {
    fluencyReason += `; masked LM unavailable: ${error instanceof Error ? error.message : String(error)}`;
  }

  // A below-threshold learned contradiction is not a hard veto. Keep the
  // result visible in the reason but score it as neutral so only the agreed
  // threshold controls rejection.
  const formattingOnly = canonicalFormatting(input) === canonicalFormatting(trimmed);
  if (formattingOnly && hardContradiction) {
    // DeBERTa can overreact to a tokenization-only edit such as `50mg` ->
    // `50 mg`. Preserve the learned run and its diagnostics, but do not let a
    // formatting-equivalent candidate fail the meaning gate.
    hardContradiction = false;
    nliLabel = "entail";
    nliReason = `format-equivalent override; ${nliReason}`;
  }
  const effectiveLabel = hardContradiction
    ? "contradict"
    : nliLabel === "contradict" ? "neutral" : nliLabel;
  return assessment(
    effectiveLabel,
    nliConfidence,
    fluencyScore,
    learnedNli,
    learnedFluency,
    `nli=${nliReason}; fluency=${fluencyReason}`
  );
}

/**
 * Stable public score entry point. Explicit adapters remain supported for
 * tests and future local models; the default is always the bundled path.
 */
export async function assessEnglishQuality(
  input: string,
  output: string,
  opts: EnglishQualityOptions = {}
): Promise<EnglishQualityAssessment> {
  if (!opts.nli && !opts.fluency) {
    return assessEnglishQualityWithOnnx(input, output);
  }

  const trimmed = output.trim();
  if (!trimmed) return assessment("contradict", 1, 0, false, false, "empty output");

  let entailment: EntailmentLabel = "neutral";
  let nliConfidence = 0.5;
  let learnedNli = false;
  let nliReason = "rule-nli";
  if (opts.nli) {
    try {
      const result = await opts.nli.score(input, trimmed);
      entailment = result.label;
      nliConfidence = result.score;
      learnedNli = true;
      nliReason = result.reason ?? "injected-nli";
    } catch {
      // The deterministic rail below remains the source of truth.
    }
  }

  try {
    const rail = await (await import("./nliJudge")).createRuleNliJudge().judge(input, trimmed);
    if (rail.label === "contradict") {
      entailment = "contradict";
      nliConfidence = Math.max(nliConfidence, rail.score);
      nliReason = `${rail.reason}; ${nliReason}`;
    } else if (!learnedNli) {
      entailment = rail.label;
      nliConfidence = rail.score;
      nliReason = rail.reason;
    }
  } catch {
    // Keep neutral if even the rail cannot initialize.
  }

  const structural = structuralFluency(input, trimmed);
  let fluencyScore = structural.score;
  let fluencyReason = structural.reason;
  let learnedFluency = false;
  if (opts.fluency) {
    try {
      const [inputPerplexity, outputPerplexity] = await Promise.all([
        opts.fluency.perplexity(input),
        opts.fluency.perplexity(trimmed),
      ]);
      const ratio = outputPerplexity / Math.max(1, inputPerplexity);
      fluencyScore = ratio <= 1 ? 1 : ratio <= 1.5 ? 1 - (ratio - 1) : Math.max(0, 1 - ratio);
      learnedFluency = true;
      fluencyReason = `injected-ppl ratio=${ratio.toFixed(2)}`;
    } catch {
      // Keep the structural fallback.
    }
  }

  if (canonicalFormatting(input) === canonicalFormatting(trimmed) && entailment === "contradict") {
    entailment = "entail";
    nliReason = `format-equivalent override; ${nliReason}`;
  }

  return assessment(
    entailment,
    nliConfidence,
    fluencyScore,
    learnedNli,
    learnedFluency,
    `nli=${nliReason}; fluency=${fluencyReason}`
  );
}

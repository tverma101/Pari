/**
 * Learned English-quality / NLI judge interface (Issue #7).
 *
 * Production currently scores "English quality" as Harper high-severity
 * lint delta (grammarGain). That is necessary but not sufficient: two
 * candidates can both have zero Harper errors while one is stilted or
 * clause-fused. The design doc (pari-quality-system.md §1) calls for:
 *   - a small NLI model (DeBERTa-v3-xsmall MNLI / ONNX) for entailment:
 *     output must be entailed-by input, never contradicted.
 *   - a tiny LM perplexity ratio for fluency: PPL(out) <= 1.5*PPL(in).
 *
 * Running those models requires ONNX/MLX binaries that are not yet
 * bundled. This module provides the stable interface now so the
 * production ranker and metrics.mjs can call it; implementations
 * start as bounded fallbacks (Pari-Q + clause check) and are upgraded
 * to ONNX without changing call sites.
 *
 * Contract (mirrors scoreCase's englishQuality split):
 *   - englishQualityScore ∈ [0,1] higher is better
 *   - meaningEntailment: entail | neutral | contradict
 *   - an explanation for why the score was given
 */

export type EntailmentLabel = "entail" | "neutral" | "contradict";

export interface EnglishQualityAssessment {
  /** 0..1 — 1 is fully fluent. 0.5 is neutral fallback when no model loaded. */
  englishQualityScore: number;
  /** Bounded 0..1 fluency component (tiny-LM PPL ratio when available). */
  fluencyScore: number;
  /** NLI-style entailment judgment when available; neutral is the safe fallback. */
  entailment: EntailmentLabel;
  /** Whether a learned model actually ran (vs heuristic fallback). */
  learned: boolean;
  /** Short human-readable reason (for logs / report.mjs). */
  reason: string;
}

export interface EnglishQualityOptions {
  /** Optional pre-loaded NLI pipeline; if absent, uses neutral fallback. */
  nli?: {
    score: (premise: string, hypothesis: string) => Promise<{ label: EntailmentLabel; score: number }>;
  } | null;
  /** Optional PPL scorer; if absent, uses Pari-Q structural proxy. */
  fluency?: {
    perplexity: (text: string) => Promise<number>;
  } | null;
}

/**
 * Score English quality for a (input, output) pair.
 * Safe to call in production — never throws, falls back deterministically.
 */
export async function assessEnglishQuality(
  input: string,
  output: string,
  opts: EnglishQualityOptions = {}
): Promise<EnglishQualityAssessment> {
  const trimmed = output.trim();
  if (!trimmed) {
    return { englishQualityScore: 0, fluencyScore: 0, entailment: "contradict", learned: false, reason: "empty output" };
  }

  // Lazy rule-NLI fallback so production has a real (general) judge even before ONNX is bundled.
  // This is not a neutral 0.5 — it detects negation flips, quantity mismatches, invented numbers,
  // and generic SVO role swaps for unseen verbs. See nliJudge.ts.
  // Avoid top-level import to prevent circular init with nliJudge.
  async function ruleNliJudge(
    premise: string,
    hypothesis: string
  ): Promise<{ label: EntailmentLabel; score: number; reason: string }> {
    const mod = await import("@/lib/scoring/nliJudge");
    return mod.createRuleNliJudge().judge(premise, hypothesis);
  }

  // 1) NLI judgment: prefer wired pipeline, else rule-based general NLI.
  let entailment: EntailmentLabel = "neutral";
  let nliConfidence = 0.55;
  let learnedNli = false;
  let nliReason = "rule-nli";
  if (opts.nli) {
    try {
      const r = await opts.nli.score(input, output);
      entailment = r.label;
      nliConfidence = r.score;
      learnedNli = true;
      nliReason = "onnx-nli";
    } catch {
      // fall through to rule NLI
    }
  }
  if (!learnedNli) {
    try {
      const r = await ruleNliJudge(input, output);
      entailment = r.label;
      nliConfidence = r.score;
      nliReason = r.reason;
    } catch {
      // stay neutral
    }
  }

  // 2) Fluency: prefer tiny-LM PPL, else structural proxy from Harper + sentence shape.
  // The structural proxy is not "learned" but it distinguishes 0-harper clean vs stilted.
  let fluencyScore = 0.5;
  let learnedFlu = false;
  let fluReason = "structural-proxy";
  if (opts.fluency) {
    try {
      const [pIn, pOut] = await Promise.all([opts.fluency.perplexity(input), opts.fluency.perplexity(output)]);
      const ratio = pOut / Math.max(1, pIn);
      fluencyScore = ratio <= 1.0 ? 1 : ratio <= 1.5 ? 1 - (ratio - 1) : Math.max(0, 1 - ratio);
      learnedFlu = true;
      fluReason = "tiny-lm-ppl";
    } catch {
      // fall through
    }
  }
  if (!learnedFlu) {
    // Cheap structural fluency: penalize very long/short rewrites and repeated n-grams.
    // This is heuristic, not learned, but prevents "0 harper errors but unreadable" from scoring 0.5.
    const wordsIn = input.split(/\s+/).filter(Boolean).length;
    const wordsOut = output.split(/\s+/).filter(Boolean).length;
    const lenRatio = wordsOut / Math.max(1, wordsIn);
    let lenScore = 1;
    if (lenRatio < 0.6 || lenRatio > 1.6) lenScore = 0.6;
    else if (lenRatio < 0.8 || lenRatio > 1.35) lenScore = 0.85;
    // distinct-bigram proxy via simple token set
    const toks = output.toLowerCase().match(/[a-z]+/g) ?? [];
    const bigrams = new Set<string>();
    for (let i = 0; i < toks.length - 1; i++) bigrams.add(`${toks[i]} ${toks[i + 1]}`);
    const distinct2 = toks.length > 1 ? bigrams.size / (toks.length - 1) : 1;
    const diversityScore = distinct2 < 0.5 ? 0.5 : distinct2 < 0.7 ? 0.75 : 1;
    fluencyScore = 0.6 * lenScore + 0.4 * diversityScore;
  }

  const learned = learnedNli || learnedFlu;
  const entailScore = entailment === "entail" ? 1 : entailment === "neutral" ? 0.75 : 0;
  const englishQualityScore = entailment === "contradict" ? 0 : 0.5 * entailScore + 0.5 * fluencyScore;
  const reason =
    entailment === "contradict"
      ? `contradiction: ${nliReason} (${nliConfidence.toFixed(2)})`
      : `${nliReason} entail=${entailment}(${nliConfidence.toFixed(2)}) fluency=${fluencyScore.toFixed(2)}[${fluReason}]${learned ? " learned" : " rule"}`;

  return { englishQualityScore, fluencyScore, entailment, learned, reason };
}

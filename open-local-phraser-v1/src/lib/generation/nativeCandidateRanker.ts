/**
 * Best-of-N ranking for whole-paragraph native candidates.
 *
 * Every candidate must pass the same hard gates as a single draft
 * (protected content, rewrite quality, no new high-severity grammar issues).
 * Among survivors, candidates are ranked primarily by the learned English
 * quality score (masked-LM fluency + NLI) with semantic similarity as a
 * floor/tie-break — per Issue #7
 * the previous MiniLM-first sort could certify malformed English like ro-04.
 * When nothing passes, the caller falls back to single-draft behavior.
 */
import { analyzeHarperGrammar } from "@/lib/nlp/harper";
import {
  validateProtectedContent,
  type ProtectedSpan,
} from "@/lib/safety/protectedContent";
import { validateRewriteQuality } from "@/lib/generation/rewriteQuality";
import { assessEnglishQuality } from "@/lib/scoring/englishQuality";
import type { RewriteMode } from "@/lib/types";

export interface RankedNativeCandidate {
  text: string;
  temperature?: number;
  semanticScore: number;
  grammarGain: number;
  strengthFitScore: number;
  englishQualityScore: number;
  learnedNli: boolean;
  learnedFluency: boolean;
  englishQualityReason: string;
  safe: boolean;
}

function compareRankedCandidates(left: RankedNativeCandidate, right: RankedNativeCandidate): number {
  if (left.safe !== right.safe) return left.safe ? -1 : 1;
  // Issue #7: English quality is primary; similarity is a hard floor (see above).
  // Among similarly good safe candidates, strength fit prevents the high
  // slider from selecting a barely changed draft simply because it is a few
  // hundredths ahead on fluency. Quality still wins by a meaningful margin.
  if (Math.abs(right.englishQualityScore - left.englishQualityScore) > 0.035) {
    return right.englishQualityScore - left.englishQualityScore;
  }
  if (Math.abs(right.strengthFitScore - left.strengthFitScore) > 0.06) {
    return right.strengthFitScore - left.strengthFitScore;
  }
  if (Math.abs(right.englishQualityScore - left.englishQualityScore) > 0.01) {
    return right.englishQualityScore - left.englishQualityScore;
  }
  if (Math.abs(right.grammarGain - left.grammarGain) > 0.01) {
    return right.grammarGain - left.grammarGain;
  }
  if (Math.abs(right.semanticScore - left.semanticScore) > 0.01) {
    return right.semanticScore - left.semanticScore;
  }
  return (left.temperature ?? 0) - (right.temperature ?? 0);
}

/** Pure ordering boundary used by production and the ranker regression QA. */
export function sortRankedNativeCandidates(candidates: RankedNativeCandidate[]): RankedNativeCandidate[] {
  return [...candidates].sort(compareRankedCandidates);
}

function tokensOf(text: string): number {
  return Math.max(1, (text.match(/[A-Za-z0-9']+/g) ?? []).length);
}

function normalizedWords(text: string): string[] {
  return (text.toLowerCase().match(/[a-z0-9]+(?:['-][a-z0-9]+)*/g) ?? []);
}

function lexicalChangeRate(originalText: string, candidateText: string): number {
  const originalWords = normalizedWords(originalText);
  const candidateWords = normalizedWords(candidateText);
  const width = Math.max(originalWords.length, candidateWords.length, 1);
  const compared = Math.min(originalWords.length, candidateWords.length);
  let changed = Math.abs(originalWords.length - candidateWords.length);

  for (let index = 0; index < compared; index += 1) {
    if (originalWords[index] !== candidateWords[index]) changed += 1;
  }

  return Math.min(1, changed / width);
}

function targetChangeRate(strength: number): number {
  const normalized = Math.max(0, Math.min(100, strength)) / 100;
  // Aim for restrained lexical difference even at Deep: structure and phrase
  // framing provide additional variety without encouraging word dumping.
  return 0.035 + normalized * 0.22;
}

function strengthFitScore(originalText: string, candidateText: string, strength: number): number {
  const distance = Math.abs(lexicalChangeRate(originalText, candidateText) - targetChangeRate(strength));
  return Math.max(0, 1 - distance / 0.2);
}

async function highSeverityIssueCount(text: string): Promise<number> {
  const issues = await analyzeHarperGrammar(text);
  return issues.filter((issue) => issue.severity === "high").length;
}

export async function rankNativeCandidates(
  candidates: Array<{ text: string; temperature?: number }>,
  options: {
    originalText: string;
    protectedSpans: ProtectedSpan[];
    mode: RewriteMode;
    /** Requested slider strength, used only to rank similarly safe drafts. */
    strength?: number;
    structuralRepair: boolean;
    finalizeDraft: (nativeText: string, originalText: string, protectedSpans: ProtectedSpan[], mode: RewriteMode, warmthPolish: boolean) => string;
    warmthPolish: boolean;
  }
): Promise<RankedNativeCandidate[]> {
  // Lazy-load the embedding stack: it uses import.meta (browser/orchestrator
  // only) and must not break plain-Node callers, which get grammar-only ranking.
  let cosine: (a: number[], b: number[]) => number;
  let vectors: number[][];
  let semanticAvailable = false;
  try {
    const [{ getEmbeddingExtractor }, { cosineSimilarity }] = await Promise.all([
      import("@/lib/ranking/modelManager"),
      import("@/lib/ranking/similarity"),
    ]);
    const extractor = await getEmbeddingExtractor("Xenova/all-MiniLM-L6-v2", {
      allowRemoteFallback: false,
    });
    const texts = [options.originalText, ...candidates.map((candidate) => candidate.text)];
    const embeddings = await extractor(texts, { pooling: "mean", normalize: true });
    const values = Array.from(embeddings.data);
    const dims = embeddings.dims ?? [];
    const width = dims[dims.length - 1] ?? (Math.floor(values.length / texts.length) || 1);
    vectors = Array.from({ length: texts.length }, (_, index) =>
      values.slice(index * width, (index + 1) * width)
    );
    cosine = cosineSimilarity;
    semanticAvailable = vectors.length === texts.length && vectors.every((vector) => vector.length > 0);
  } catch {
    vectors = [];
    cosine = () => 0.5; // neutral semantic score; semantic floor is WAIVED when embeddings unavailable
  }
  const originalVector = vectors[0] ?? [];
  // Match the frozen evaluation policy: ordinary paraphrases need a strong
  // semantic match, while genuinely broken/fragmentary prose gets a looser
  // floor because reconstruction can move embeddings substantially.
  const semanticFloor = options.structuralRepair ? 0.55 : 0.72;

  const inputIssues = await highSeverityIssueCount(options.originalText);
  const inputRate = inputIssues / tokensOf(options.originalText);

  const ranked = await Promise.all(
    candidates.map(async (candidate, index) => {
      const repairedText = options.finalizeDraft(
        candidate.text,
        options.originalText,
        options.protectedSpans,
        options.mode,
        options.warmthPolish,
      );
      const validation = validateProtectedContent(options.originalText, repairedText, options.protectedSpans);
      const quality = validateRewriteQuality(options.originalText, repairedText, options.protectedSpans, {
        allowStructuralRepair: options.structuralRepair,
      });

      const outIssues = quality.safe ? await highSeverityIssueCount(repairedText) : Number.POSITIVE_INFINITY;
      const outRate = outIssues / tokensOf(repairedText);
      const semanticScore = cosine(originalVector, vectors[index + 1] ?? []);
      const semanticSafe = !semanticAvailable || semanticScore >= semanticFloor;
      const englishQuality = await assessEnglishQuality(options.originalText, repairedText);
      // Learned judge can veto: contradict => not safe, even if Harper is clean.
      const nliOk = englishQuality.entailment !== "contradict";

      return {
        text: repairedText,
        temperature: candidate.temperature,
        semanticScore,
        grammarGain: (inputRate - outRate) * 100,
        strengthFitScore: strengthFitScore(options.originalText, repairedText, options.strength ?? 56),
        englishQualityScore: englishQuality.englishQualityScore,
        learnedNli: englishQuality.learnedNli,
        learnedFluency: englishQuality.learnedFluency,
        englishQualityReason: englishQuality.reason,
        safe:
          validation.safe &&
          quality.safe &&
          semanticSafe &&
          nliOk &&
          repairedText !== options.originalText &&
          outRate <= inputRate + 0.005,
      };
    })
  );

  return sortRankedNativeCandidates(ranked);
}

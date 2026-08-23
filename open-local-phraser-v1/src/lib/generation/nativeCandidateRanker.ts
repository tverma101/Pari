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
  englishQualityScore: number;
  learnedNli: boolean;
  learnedFluency: boolean;
  englishQualityReason: string;
  safe: boolean;
}

function compareRankedCandidates(left: RankedNativeCandidate, right: RankedNativeCandidate): number {
  if (left.safe !== right.safe) return left.safe ? -1 : 1;
  // Issue #7: English quality is primary; similarity is a hard floor (see above).
  // Among safe candidates, prefer higher learned English quality, then grammarGain, then similarity.
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
    structuralRepair: boolean;
    finalizeDraft: (nativeText: string, originalText: string, protectedSpans: ProtectedSpan[], mode: RewriteMode, warmthPolish: boolean) => string;
    warmthPolish: boolean;
  }
): Promise<RankedNativeCandidate[]> {
  // Lazy-load the embedding stack: it uses import.meta (browser/orchestrator
  // only) and must not break plain-Node callers, which get grammar-only ranking.
  let cosine: (a: number[], b: number[]) => number;
  let vectors: number[][];
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
  } catch {
    vectors = [];
    cosine = () => 0.5; // neutral semantic score; semantic floor is WAIVED when embeddings unavailable
  }
  const originalVector = vectors[0] ?? [];

  const inputIssues = await highSeverityIssueCount(options.originalText);
  const inputRate = inputIssues / tokensOf(options.originalText);

  // Embedding failure must NOT make every candidate unsafe — otherwise an
  // unavailable model bricks the product. The 0.55 floor is hard only when
  // embeddings actually loaded; when they didn't, grammarGain + clause + NLI
  // still gate safety and ordering falls to English quality.
  const hasEmbeddings = vectors.length > 0 && originalVector.length > 0;
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
      const semanticFloorOk = !hasEmbeddings || semanticScore >= 0.55;
      const englishQuality = await assessEnglishQuality(options.originalText, repairedText);
      // Learned judge can veto: contradict => not safe, even if Harper is clean.
      const nliOk = englishQuality.entailment !== "contradict";

      return {
        text: repairedText,
        temperature: candidate.temperature,
        semanticScore,
        grammarGain: (inputRate - outRate) * 100,
        englishQualityScore: englishQuality.englishQualityScore,
        learnedNli: englishQuality.learnedNli,
        learnedFluency: englishQuality.learnedFluency,
        englishQualityReason: englishQuality.reason,
        safe: validation.safe && quality.safe && semanticFloorOk && nliOk && repairedText !== options.originalText && outRate <= inputRate + 0.005,
      };
    })
  );

  return sortRankedNativeCandidates(ranked);
}

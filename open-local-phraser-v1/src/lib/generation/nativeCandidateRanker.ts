/**
 * Best-of-N ranking for whole-paragraph native candidates.
 *
 * Every candidate must pass the same hard gates as a single draft
 * (protected content, rewrite quality, no new high-severity grammar issues).
 * Among survivors, survivors are ranked primarily by English quality
 * (grammarGain) with semantic similarity as a floor/tie-break — per Issue #7
 * the previous MiniLM-first sort could certify malformed English like ro-04.
 * When nothing passes, the caller falls back to single-draft behavior.
 */
import { analyzeHarperGrammar } from "@/lib/nlp/harper";
import {
  validateProtectedContent,
  type ProtectedSpan,
} from "@/lib/safety/protectedContent";
import { validateRewriteQuality } from "@/lib/generation/rewriteQuality";
import type { RewriteMode } from "@/lib/types";

export interface RankedNativeCandidate {
  text: string;
  temperature?: number;
  semanticScore: number;
  grammarGain: number;
  safe: boolean;
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
  let semanticAvailable = false;
  try {
    const [{ getEmbeddingExtractor }, { cosineSimilarity }] = await Promise.all([
      import("@/lib/ranking/modelManager"),
      import("@/lib/ranking/similarity"),
    ]);
    const extractor = await getEmbeddingExtractor("Xenova/all-MiniLM-L6-v2", {
      allowRemoteFallback: true,
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
    cosine = () => 0.5; // neutral semantic score; ordering falls to grammar gain
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

      return {
        text: repairedText,
        temperature: candidate.temperature,
        semanticScore,
        grammarGain: (inputRate - outRate) * 100,
        safe:
          validation.safe &&
          quality.safe &&
          semanticSafe &&
          repairedText !== options.originalText &&
          outRate <= inputRate + 0.005,
      };
    })
  );

  return ranked.sort((left, right) => {
    if (left.safe !== right.safe) return left.safe ? -1 : 1;
    // English quality is primary after the hard semantic floor. When semantic
    // embeddings are unavailable, grammar-only ordering remains the fallback.
    const leftLowSim = semanticAvailable && left.semanticScore < semanticFloor;
    const rightLowSim = semanticAvailable && right.semanticScore < semanticFloor;
    if (leftLowSim !== rightLowSim) return leftLowSim ? 1 : -1;
    if (Math.abs(right.grammarGain - left.grammarGain) > 0.01) {
      return right.grammarGain - left.grammarGain;
    }
    if (semanticAvailable && Math.abs(right.semanticScore - left.semanticScore) > 0.01) {
      return right.semanticScore - left.semanticScore;
    }
    return (left.temperature ?? 0) - (right.temperature ?? 0);
  });
}

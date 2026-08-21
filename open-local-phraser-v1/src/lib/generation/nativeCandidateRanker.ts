/**
 * Best-of-N ranking for whole-paragraph native candidates.
 *
 * Every candidate must pass the same hard gates as a single draft
 * (protected content, rewrite quality, no new high-severity grammar issues).
 * Passing candidates are ranked by MiniLM similarity to the original plus a
 * small grammar-gain bonus; ties prefer the lower temperature. When nothing
 * passes, the caller falls back to its existing single-draft behavior.
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
  } catch {
    vectors = [];
    cosine = () => 0.5; // neutral semantic score; ordering falls to grammar gain
  }
  const originalVector = vectors[0] ?? [];

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

      return {
        text: repairedText,
        temperature: candidate.temperature,
        semanticScore: cosine(originalVector, vectors[index + 1] ?? []),
        grammarGain: (inputRate - outRate) * 100,
        safe: validation.safe && quality.safe && repairedText !== options.originalText && outRate <= inputRate + 0.005,
      };
    })
  );

  return ranked.sort((left, right) => {
    if (left.safe !== right.safe) return left.safe ? -1 : 1;
    if (Math.abs(right.semanticScore - left.semanticScore) > 0.001) {
      return right.semanticScore - left.semanticScore;
    }
    if (Math.abs(right.grammarGain - left.grammarGain) > 0.01) {
      return right.grammarGain - left.grammarGain;
    }
    return (left.temperature ?? 0) - (right.temperature ?? 0);
  });
}

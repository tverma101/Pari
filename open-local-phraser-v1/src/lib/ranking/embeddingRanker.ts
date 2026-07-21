import { getEmbeddingExtractor } from "./modelManager";
import { getRankingModelIds } from "./modelRegistry";
import { rankCandidatesByRule } from "./ruleBasedRanker";
import { cosineSimilarity } from "./similarity";
import type { CandidateOption, RankingContext, RankingResult, SemanticModelId } from "./types";

type FeatureExtractorOutput = {
  data: Float32Array | number[];
  dims?: number[];
  size?: number;
};

function replaceSelection(context: RankingContext, replacement: string): string {
  const { sentence, selectedText, selectionStart, selectionEnd, sentenceStart } = context;

  if (
    typeof selectionStart === "number" &&
    typeof selectionEnd === "number" &&
    typeof sentenceStart === "number"
  ) {
    const localStart = Math.max(0, selectionStart - sentenceStart);
    const localEnd = Math.max(localStart, selectionEnd - sentenceStart);
    return sentence.slice(0, localStart) + replacement + sentence.slice(localEnd);
  }

  const firstIndex = sentence.indexOf(selectedText);
  if (firstIndex === -1) return sentence;
  return sentence.slice(0, firstIndex) + replacement + sentence.slice(firstIndex + selectedText.length);
}

function toVectors(output: FeatureExtractorOutput, count: number): number[][] {
  const values = Array.from(output.data);
  const dims = output.dims ?? [];
  const width = dims[dims.length - 1] ?? (Math.floor(values.length / count) || 1);

  const vectors: number[][] = [];
  for (let index = 0; index < count; index += 1) {
    const start = index * width;
    vectors.push(values.slice(start, start + width));
  }
  return vectors;
}

export async function ensureEmbeddingModel(modelId: SemanticModelId): Promise<void> {
  await getEmbeddingExtractor(modelId);
}

export async function rankCandidatesByEmbedding(
  options: CandidateOption[],
  context: RankingContext,
  modelId: SemanticModelId
): Promise<RankingResult[]> {
  if (options.length === 0) return [];

  const baseRanked = rankCandidatesByRule(options, context);
  const extractor = await getEmbeddingExtractor(modelId, { allowRemoteFallback: true });
  const candidateSentences = baseRanked.map((result) => replaceSelection(context, result.option.replacement));
  const embeddings = await extractor([context.sentence, ...candidateSentences], {
    pooling: "mean",
    normalize: true,
  });

  const vectors = toVectors(embeddings, candidateSentences.length + 1);
  const originalVector = vectors[0] ?? [];

  return baseRanked
    .map((result, index) => {
      const semanticScore = cosineSimilarity(originalVector, vectors[index + 1] ?? []);
      const score = result.score * 0.45 + semanticScore * 0.55;
      return {
        ...result,
        score,
        semanticScore,
      };
    })
    .sort((left, right) => right.score - left.score);
}

export async function rankCandidatesByEmbeddingEnsemble(
  options: CandidateOption[],
  context: RankingContext
): Promise<RankingResult[]> {
  if (options.length === 0) return [];

  const modelIds = getRankingModelIds();
  const baseRanked = rankCandidatesByRule(options, context);
  const candidateSentences = baseRanked.map((result) => replaceSelection(context, result.option.replacement));
  const semanticTotals = new Array(baseRanked.length).fill(0) as number[];
  let completedModels = 0;

  for (const modelId of modelIds) {
    const extractor = await getEmbeddingExtractor(modelId, { allowRemoteFallback: false });
    const embeddings = await extractor([context.sentence, ...candidateSentences], {
      pooling: "mean",
      normalize: true,
    });

    const vectors = toVectors(embeddings, candidateSentences.length + 1);
    const originalVector = vectors[0] ?? [];

    baseRanked.forEach((_, index) => {
      semanticTotals[index] += cosineSimilarity(originalVector, vectors[index + 1] ?? []);
    });
    completedModels += 1;
  }

  return baseRanked
    .map((result, index) => {
      const semanticScore =
        completedModels > 0 ? semanticTotals[index] / completedModels : result.semanticScore ?? 0;
      const score = result.score * 0.35 + semanticScore * 0.65;
      return {
        ...result,
        score,
        semanticScore,
        warnings: completedModels > 1
          ? [...result.warnings, `${completedModels}-model rank`]
          : result.warnings,
      };
    })
    .sort((left, right) => right.score - left.score);
}

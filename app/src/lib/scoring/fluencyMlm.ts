/**
 * Local learned fluency signal for Issue #7.
 *
 * DistilBERT is already bundled for contextual suggestions. We reuse that
 * masked-language model to calculate a bounded pseudo-perplexity: mask a
 * sample of the candidate's wordpiece tokens, ask the model to recover each
 * original token, and average the log probabilities. This is a naturalness
 * signal, not a replacement for Harper, clause rails, or NLI.
 */
import { configureLocalTransformers } from "./localTransformers";

export const FLUENCY_MODEL_ID = "Xenova/distilbert-base-uncased" as const;

export interface FluencyResult {
  score: number;
  averageLogProbability: number;
  pseudoPerplexity: number;
  tokenCount: number;
  reason: string;
}

const MAX_TOKENS_TO_SCORE = 12;
const INFERENCE_BATCH_SIZE = 8;

let artifactsPromise: Promise<{ tok: any; mdl: any }> | null = null;
let artifactsError: unknown = null;

async function getArtifacts(): Promise<{ tok: any; mdl: any }> {
  if (artifactsPromise) return artifactsPromise;
  if (artifactsError) throw artifactsError;

  const load = (async () => {
    const tf: any = await import("@huggingface/transformers");
    await configureLocalTransformers(tf);
    const tok = await tf.AutoTokenizer.from_pretrained(FLUENCY_MODEL_ID, { local_files_only: true });
    const mdl = await tf.AutoModelForMaskedLM.from_pretrained(FLUENCY_MODEL_ID, {
      dtype: "q8",
      local_files_only: true,
    });
    return { tok, mdl };
  })();

  artifactsPromise = load.catch((error) => {
    artifactsError = error;
    throw error;
  });
  return artifactsPromise;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function selectedTokenPositions(tok: any, inputIds: number[]): Array<{ index: number; id: number }> {
  const specialIds = new Set([
    tok.pad_token_id,
    tok.mask_token_id,
    tok.sep_token_id,
    tok.cls_token_id,
    tok.unk_token_id,
  ].filter((id): id is number => Number.isInteger(id)));
  const positions = inputIds
    .map((id, index) => ({
      index,
      id,
      piece: String(tok.decode([id], { skip_special_tokens: false })),
    }))
    .filter(({ id, piece }) => !specialIds.has(id) && /[a-z]/i.test(piece) && !piece.startsWith("["))
    .map(({ index, id }) => ({ index, id }));

  if (positions.length <= MAX_TOKENS_TO_SCORE) return positions;
  const stride = positions.length / MAX_TOKENS_TO_SCORE;
  return Array.from({ length: MAX_TOKENS_TO_SCORE }, (_, index) => positions[Math.floor(index * stride)]);
}

function makeBatchTensor(tf: any, values: bigint[], batchSize: number, sequenceLength: number): any {
  return new tf.Tensor(
    "int64",
    BigInt64Array.from(values),
    [batchSize, sequenceLength]
  );
}

async function scoreBatch(
  tf: any,
  mdl: any,
  originalIds: bigint[],
  attention: bigint[],
  sequenceLength: number,
  maskTokenId: number,
  positions: Array<{ index: number; id: number }>
): Promise<number[]> {
  const batchSize = positions.length;
  const maskedIds: bigint[] = [];
  const batchedAttention: bigint[] = [];

  for (const position of positions) {
    for (let index = 0; index < sequenceLength; index += 1) {
      maskedIds.push(index === position.index ? BigInt(maskTokenId) : originalIds[index]);
      batchedAttention.push(attention[index]);
    }
  }

  const output = await mdl({
    input_ids: makeBatchTensor(tf, maskedIds, batchSize, sequenceLength),
    attention_mask: makeBatchTensor(tf, batchedAttention, batchSize, sequenceLength),
  });
  const logits = output.logits;
  const values = logits.data as Float32Array | number[];
  const vocabularySize = logits.dims[2] as number;
  const logProbabilities: number[] = [];

  for (let batchIndex = 0; batchIndex < batchSize; batchIndex += 1) {
    const position = positions[batchIndex];
    const offset = (batchIndex * sequenceLength + position.index) * vocabularySize;
    let maxLogit = Number.NEGATIVE_INFINITY;
    for (let tokenIndex = 0; tokenIndex < vocabularySize; tokenIndex += 1) {
      maxLogit = Math.max(maxLogit, values[offset + tokenIndex]);
    }

    let normalizer = 0;
    for (let tokenIndex = 0; tokenIndex < vocabularySize; tokenIndex += 1) {
      normalizer += Math.exp(values[offset + tokenIndex] - maxLogit);
    }
    logProbabilities.push(
      values[offset + position.id] - maxLogit - Math.log(normalizer)
    );
  }

  return logProbabilities;
}

export async function scoreMaskedLmFluency(text: string): Promise<FluencyResult> {
  const trimmed = text.trim();
  if (!trimmed) {
    return {
      score: 0,
      averageLogProbability: Number.NEGATIVE_INFINITY,
      pseudoPerplexity: Number.POSITIVE_INFINITY,
      tokenCount: 0,
      reason: "empty text",
    };
  }

  const { tok, mdl } = await getArtifacts();
  const tf: any = await import("@huggingface/transformers");
  const inputs: any = tok(trimmed, {
    padding: true,
    truncation: true,
    max_length: 128,
  });
  const originalIds = (inputs.input_ids.tolist()[0] as Array<number | bigint>).map((value) => BigInt(value));
  const attention = Array.from(inputs.attention_mask.data as ArrayLike<number | bigint>);
  const sequenceLength = originalIds.length;
  const positions = selectedTokenPositions(tok, originalIds.map(Number));
  if (positions.length === 0) {
    return {
      score: 0.5,
      averageLogProbability: 0,
      pseudoPerplexity: 1,
      tokenCount: 0,
      reason: `${FLUENCY_MODEL_ID} found no scorable tokens`,
    };
  }

  const attentionIds = attention.map((value) => BigInt(Number(value)));
  const logProbabilities: number[] = [];
  for (let start = 0; start < positions.length; start += INFERENCE_BATCH_SIZE) {
    logProbabilities.push(...await scoreBatch(
      tf,
      mdl,
      originalIds,
      attentionIds,
      sequenceLength,
      Number(tok.mask_token_id),
      positions.slice(start, start + INFERENCE_BATCH_SIZE)
    ));
  }

  const finite = logProbabilities.filter(Number.isFinite);
  const averageLogProbability = finite.length > 0
    ? finite.reduce((sum, value) => sum + value, 0) / finite.length
    : Number.NEGATIVE_INFINITY;
  const pseudoPerplexity = Number.isFinite(averageLogProbability)
    ? Math.exp(-averageLogProbability)
    : Number.POSITIVE_INFINITY;
  // DistilBERT log probabilities are not calibrated as a 0..1 quality score.
  // This stable bounded mapping is used only for ranking candidates relative
  // to one another; the raw pseudo-perplexity remains in the reason string.
  const score = Number.isFinite(averageLogProbability)
    ? clamp((averageLogProbability + 8) / 8, 0, 1)
    : 0;

  return {
    score,
    averageLogProbability,
    pseudoPerplexity,
    tokenCount: finite.length,
    reason: `${FLUENCY_MODEL_ID} masked-lm pseudo-ppl=${pseudoPerplexity.toFixed(2)} tokens=${finite.length}`,
  };
}

export function resetFluencyForTests(): void {
  artifactsPromise = null;
  artifactsError = null;
}

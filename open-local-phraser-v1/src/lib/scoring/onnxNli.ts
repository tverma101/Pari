/**
 * Bundled ONNX NLI — DeBERTa-v3-xsmall local-only (Issue #7).
 * Bidirectional contradiction: either direction at or above the threshold
 * hard-fails. A lower-confidence contradiction is reported but is not treated
 * as a hard veto; the deterministic safety rails still apply.
 */
import type { EntailmentLabel } from "./englishQuality";
import { configureLocalTransformers } from "./localTransformers";

export const NLI_MODEL_ID = "Xenova/nli-deberta-v3-xsmall" as const;
export const NLI_CONTRADICTION_THRESHOLD = 0.6;

export interface NliResult {
  label: EntailmentLabel;
  score: number;
  probs: [number, number, number]; // [contradiction, entailment, neutral]
  hardContradiction: boolean;
  reason: string;
}

let artifactsPromise: Promise<{ tok: any; mdl: any }> | null = null;
let artifactsError: unknown = null;

async function getArtifacts(): Promise<{ tok: any; mdl: any }> {
  if (artifactsPromise) return artifactsPromise;
  if (artifactsError) throw artifactsError;

  const load = (async () => {
    const tf: any = await import("@huggingface/transformers");
    await configureLocalTransformers(tf);

    const tok = await tf.AutoTokenizer.from_pretrained(NLI_MODEL_ID, { local_files_only: true });
    const mdl = await tf.AutoModelForSequenceClassification.from_pretrained(NLI_MODEL_ID, {
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

function labelForIndex(model: any, index: number): { label: EntailmentLabel; raw: string } {
  const configured = String(model.config?.id2label?.[String(index)] ?? "").toLowerCase();
  const raw = configured || (["contradiction", "entailment", "neutral"][index] ?? "neutral");
  const label: EntailmentLabel = raw.includes("contradict")
    ? "contradict"
    : raw.includes("entail")
      ? "entail"
      : "neutral";
  return { label, raw };
}

function softmax(logits: number[]): number[] {
  const m = Math.max(...logits);
  const exps = logits.map((x) => Math.exp(x - m));
  const s = exps.reduce((a, b) => a + b, 0);
  return exps.map((x) => x / s);
}

export async function scoreNli(premise: string, hypothesis: string): Promise<NliResult> {
  const { tok, mdl } = await getArtifacts();
  const inputs: any = await tok(premise, {
    text_pair: hypothesis,
    padding: true,
    truncation: true,
  });
  const out: any = await mdl(inputs);
  const logits = Array.from(out.logits.data as Float32Array | number[]) as number[];
  const probs = softmax(logits);
  let best = 0;
  for (let i = 1; i < probs.length; i += 1) {
    if (probs[i] > probs[best]) best = i;
  }

  const { label, raw } = labelForIndex(mdl, best);
  const score = probs[best] ?? 0;
  return {
    label,
    score,
    probs: [probs[0] ?? 0, probs[1] ?? 0, probs[2] ?? 0],
    hardContradiction: label === "contradict" && score >= NLI_CONTRADICTION_THRESHOLD,
    reason: `deberta label=${raw} id=${best} score=${score.toFixed(3)}`,
  };
}

export async function scoreNliBidirectional(
  premise: string,
  hypothesis: string,
  threshold = NLI_CONTRADICTION_THRESHOLD
): Promise<NliResult> {
  const [fwd, rev] = await Promise.all([
    scoreNli(premise, hypothesis),
    scoreNli(hypothesis, premise),
  ]);

  if (fwd.label === "contradict" && fwd.score >= threshold) {
    return {
      ...fwd,
      hardContradiction: true,
      reason: `bidir source-to-candidate ${fwd.reason}`,
    };
  }
  if (rev.label === "contradict" && rev.score >= threshold) {
    return {
      ...rev,
      hardContradiction: true,
      reason: `bidir candidate-to-source ${rev.reason}`,
    };
  }

  return {
    ...fwd,
    hardContradiction: false,
    reason: `bidir source-to-candidate ${fwd.reason}; reverse ${rev.reason}`,
  };
}

export function resetNliForTests(): void {
  artifactsPromise = null;
  artifactsError = null;
}

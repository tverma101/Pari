import { spawnSync } from "child_process";
import * as path from "path";
import { fileURLToPath } from "url";

export interface PythonResult {
  success: boolean;
  data: Record<string, unknown>;
  rawStdout: string;
  timingMs: number;
  error?: string;
}

export interface ParaphraseOutput {
  candidates: string[];
  model: string;
  device: string;
  loadTimeMs: number;
  generationTimeMs: number;
  lane: string;
  settings: Record<string, unknown>;
}

export interface ParaphraseBatchOutput {
  model: string;
  device: string;
  loadTimeMs: number;
  results: Array<{
    input: string;
    candidates: string[];
    time_ms: number;
    lane: string;
  }>;
}

export interface EmbeddingOutput {
  model: string;
  loadTimeMs: number;
  similarity?: number;
  embeddings?: number[][];
  computeTimeMs?: number;
  results?: Array<{ text1: string; text2: string; similarity: number; time_ms: number }>;
}

export interface NLIOutput {
  model: string;
  scores: {
    entailment?: number;
    contradiction?: number;
    neutral?: number;
    label?: string;
    score?: number;
  };
}

export interface FillMaskOutput {
  model: string;
  predictions: Array<{
    token: string;
    score: number;
    sequence: string;
  }>;
  computeTimeMs: number;
}

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PYTHON_DIR = path.resolve(__dirname, "../../python");

function runPython(script: string, args: string[]): PythonResult {
  const start = performance.now();
  const scriptPath = path.join(PYTHON_DIR, script);

  try {
    const result = spawnSync("python3", [scriptPath, ...args], {
      encoding: "utf-8",
      timeout: 120_000,
      maxBuffer: 10 * 1024 * 1024,
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
    });

    const timingMs = performance.now() - start;

    if (result.status !== 0) {
      const stderr = result.stderr?.trim() ?? "";
      const error = stderr || `Exit code ${result.status}`;
      return { success: false, data: {}, rawStdout: result.stdout ?? "", timingMs, error };
    }

    const stdout = result.stdout?.trim() ?? "";
    if (!stdout) {
      return { success: false, data: {}, rawStdout: "", timingMs, error: "No output from Python script" };
    }

    const data = JSON.parse(stdout);
    return { success: true, data, rawStdout: stdout, timingMs };
  } catch (err: unknown) {
    const timingMs = performance.now() - start;
    const error = err instanceof Error ? err.message : String(err);
    return { success: false, data: {}, rawStdout: "", timingMs, error };
  }
}

/**
 * Run a T5/BART paraphrase model on a single sentence.
 */
export function paraphrase(
  sentence: string,
  options: {
    model?: string;
    lane?: string;
    numBeams?: number;
    numSequences?: number;
    doSample?: boolean;
    temperature?: number;
    device?: string;
  } = {}
): PythonResult {
  const model = options.model ?? "humarin/chatgpt_paraphraser_on_T5_base";
  const lane = options.lane ?? "natural";

  const args = [
    "--model", model,
    "--input", sentence,
    "--lane", lane,
    "--json",
  ];

  if (options.numBeams !== undefined) args.push("--num-beams", String(options.numBeams));
  if (options.numSequences !== undefined) args.push("--num-sequences", String(options.numSequences));
  if (options.doSample) args.push("--do-sample");
  if (options.temperature !== undefined) args.push("--temperature", String(options.temperature));
  if (options.device) args.push("--device", options.device);

  return runPython("paraphrase_model.py", args);
}

/**
 * Run paraphrase model on multiple sentences.
 */
export function paraphraseBatch(
  sentences: string[],
  options: {
    model?: string;
    lane?: string;
    device?: string;
  } = {}
): PythonResult {
  const model = options.model ?? "humarin/chatgpt_paraphraser_on_T5_base";
  const lane = options.lane ?? "natural";

  const args = [
    "--model", model,
    "--batch-input", JSON.stringify(sentences),
    "--lane", lane,
    "--json",
    "--warmup",
  ];
  if (options.device) args.push("--device", options.device);

  return runPython("paraphrase_model.py", args);
}

/**
 * Compute embedding similarity between two texts.
 */
export function embeddingSimilarity(
  text1: string,
  text2: string,
  model = "all-MiniLM-L6-v2"
): PythonResult {
  const args = [
    "--model", model,
    "--similarity", text1, text2,
    "--json",
  ];
  return runPython("embedding_model.py", args);
}

/**
 * Encode sentences to embeddings.
 */
export function encodeSentences(
  sentences: string[],
  model = "all-MiniLM-L6-v2"
): PythonResult {
  const args = [
    "--model", model,
    "--sentences", JSON.stringify(sentences),
    "--json",
  ];
  return runPython("embedding_model.py", args);
}

/**
 * Check NLI between premise and hypothesis.
 */
export function nliCheck(
  premise: string,
  hypothesis: string,
  model = "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli"
): PythonResult {
  const args = [
    "--model", model,
    "--premise", premise,
    "--hypothesis", hypothesis,
    "--json",
  ];
  return runPython("nli_model.py", args);
}

/**
 * Get fill-mask predictions for a sentence.
 */
export function fillMask(
  sentence: string,
  options: {
    model?: string;
    mask?: string;
    topK?: number;
  } = {}
): PythonResult {
  const model = options.model ?? "bert-base-uncased";
  const mask = options.mask ?? "[MASK]";

  const args = [
    "--model", model,
    "--sentence", sentence,
    "--mask", mask,
    "--top-k", String(options.topK ?? 20),
    "--json",
  ];
  return runPython("fill_mask_model.py", args);
}

/**
 * Benchmark a paraphrase model.
 */
export function benchmarkParaphraseModel(
  model = "humarin/chatgpt_paraphraser_on_T5_base"
): PythonResult {
  return runPython("paraphrase_model.py", ["--model", model, "--benchmark", "--json"]);
}

/**
 * Benchmark an embedding model.
 */
export function benchmarkEmbeddingModel(
  model = "all-MiniLM-L6-v2"
): PythonResult {
  return runPython("embedding_model.py", ["--model", model, "--benchmark", "--json"]);
}

/**
 * Benchmark NLI model.
 */
export function benchmarkNLIModel(
  model = "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli"
): PythonResult {
  return runPython("nli_model.py", ["--model", model, "--benchmark", "--json"]);
}

/**
 * Download a model to local cache.
 */
export function downloadModel(
  model = "humarin/chatgpt_paraphraser_on_T5_base"
): PythonResult {
  return runPython("paraphrase_model.py", ["--model", model, "--download-only", "--json"]);
}

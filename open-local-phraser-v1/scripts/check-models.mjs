import fs from "fs/promises";
import { createReadStream } from "fs";
import crypto from "crypto";
import path from "path";
import { fileURLToPath } from "url";

import { env, pipeline } from "@huggingface/transformers";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT_DIR = path.resolve(__dirname, "..");

const DEFAULT_DTYPE = "q8";
const MODEL_ROOT = path.join(ROOT_DIR, "public", "models");
const MEMORY_CEILING_MB = 6 * 1024;
const FILES_ONLY = process.argv.includes("--files-only");
const NATIVE_GENERATIVE_MODEL = {
  id: "mlx-community/Qwen3.5-4B-MLX-4bit",
  task: "mlx-generation",
  storage: "native-models",
  localPath: "native-models/Qwen/Qwen3.5-4B-MLX-4bit",
  role: "paragraph-generation",
};

function getModelDtype(model) {
  if (model.storage === "native-models") return "mlx-4bit";
  return model.task === "text2text-generation" ? "fp32" : DEFAULT_DTYPE;
}

function getRequiredFiles(model) {
  if (model.storage === "native-models") {
    return [
      "README.md",
      "chat_template.jinja",
      "config.json",
      "model.safetensors",
      "model.safetensors.index.json",
      "tokenizer.json",
      "tokenizer_config.json",
      "vocab.json",
    ];
  }

  if (model.task === "text2text-generation") {
    return [
      "config.json",
      "generation_config.json",
      "tokenizer.json",
      "tokenizer_config.json",
      "onnx/encoder_model.onnx",
      "onnx/decoder_model_merged.onnx",
    ];
  }

  return [
    "config.json",
    "onnx/model_quantized.onnx",
    "tokenizer.json",
    "tokenizer_config.json",
  ];
}

const MODELS = [
  {
    id: "Xenova/paraphrase-mpnet-base-v2",
    task: "feature-extraction",
    expectedDimensions: 768,
  },
  {
    id: "Xenova/paraphrase-MiniLM-L6-v2",
    task: "feature-extraction",
    expectedDimensions: 384,
  },
  {
    id: "Xenova/all-mpnet-base-v2",
    task: "feature-extraction",
    expectedDimensions: 768,
  },
  {
    id: "Xenova/bge-base-en-v1.5",
    task: "feature-extraction",
    expectedDimensions: 768,
  },
  {
    id: "Xenova/bge-small-en-v1.5",
    task: "feature-extraction",
    expectedDimensions: 384,
  },
  {
    id: "Xenova/all-MiniLM-L6-v2",
    task: "feature-extraction",
    expectedDimensions: 384,
  },
  {
    id: "Xenova/all-MiniLM-L12-v2",
    task: "feature-extraction",
    expectedDimensions: 384,
  },
  {
    id: "Xenova/bert-base-NER",
    task: "token-classification",
  },
  {
    id: "Xenova/distilbert-base-uncased",
    task: "fill-mask",
    maskedText: "Writers can [MASK] their sentences without changing the meaning.",
    expectedTokens: ["change", "modify", "alter", "rewrite", "revise"],
  },
  {
    id: "Xenova/distilroberta-base",
    task: "fill-mask",
    maskedText: "Writers can <mask> their sentences without changing the meaning.",
  },
  NATIVE_GENERATIVE_MODEL,
];

const TEST_SENTENCES = [
  "This shows how perception affects communication.",
  "This demonstrates how perception influences communication.",
  "The refrigerator is making a loud noise.",
];

const BATCH_SENTENCES = [
  "Clear writing helps readers understand complex material.",
  "Precise wording helps audiences understand difficult material.",
  "The package arrived near the front door.",
  "Students can revise sentences without losing their original meaning.",
  "Writers can improve phrasing while preserving the original idea.",
  "The museum closes at five on Sunday.",
  "Local tools should avoid sending private drafts to remote services.",
  "Offline applications should keep private drafts on the device.",
];

function log(message) {
  console.log(`[models:check] ${message}`);
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function rssMb() {
  return process.memoryUsage().rss / 1024 / 1024;
}

function modelDir(model) {
  return model.storage === "native-models"
    ? path.join(ROOT_DIR, model.localPath)
    : path.join(MODEL_ROOT, model.id);
}

function modelManifest(model) {
  return path.join(modelDir(model), "manifest.json");
}

async function sha256File(absolutePath) {
  const hash = crypto.createHash("sha256");
  for await (const chunk of createReadStream(absolutePath)) {
    hash.update(chunk);
  }
  return hash.digest("hex");
}

function cosineSimilarity(left, right) {
  if (left.length === 0 || left.length !== right.length) {
    return 0;
  }

  let dot = 0;
  let leftNorm = 0;
  let rightNorm = 0;

  for (let index = 0; index < left.length; index += 1) {
    const leftValue = left[index];
    const rightValue = right[index];

    dot += leftValue * rightValue;
    leftNorm += leftValue * leftValue;
    rightNorm += rightValue * rightValue;
  }

  if (leftNorm === 0 || rightNorm === 0) {
    return 0;
  }

  return dot / Math.sqrt(leftNorm * rightNorm);
}

function toVectors(output, count) {
  const values = Array.from(output.data);
  const dims = output.dims ?? [];
  const width = dims[dims.length - 1] ?? Math.floor(values.length / count || 0);
  const vectors = [];

  for (let index = 0; index < count; index += 1) {
    const start = index * width;
    vectors.push(values.slice(start, start + width));
  }

  return { vectors, width };
}

async function readManifest(model) {
  try {
    const raw = await fs.readFile(modelManifest(model), "utf8");
    return JSON.parse(raw);
  } catch {
    throw new Error(
      `Missing ${path.relative(ROOT_DIR, modelManifest(model))}. Run npm run models:download first.`
    );
  }
}

async function verifyBundledFiles(model) {
  const manifest = await readManifest(model);
  if (manifest.modelId !== model.id || manifest.dtype !== getModelDtype(model) || manifest.task !== model.task) {
    throw new Error(`Unexpected manifest for ${model.id}.`);
  }

  const manifestFiles = Array.isArray(manifest.files) ? manifest.files : [];
  if (!manifest.sha256 || typeof manifest.sha256 !== "object") {
    throw new Error(`Missing integrity hashes for ${model.id}. Run npm run models:download.`);
  }
  const required = new Set([...getRequiredFiles(model), ...manifestFiles]);
  const stats = [];

  for (const relativePath of required) {
    const absolutePath = path.join(modelDir(model), relativePath);
    let stat;
    try {
      stat = await fs.stat(absolutePath);
    } catch {
      throw new Error(`Missing required bundled file for ${model.id}: ${relativePath}`);
    }
    if (!stat.isFile() || stat.size <= 0) {
      throw new Error(`${relativePath} is empty or not a file`);
    }
    const expectedHash = manifest.sha256[relativePath];
    if (typeof expectedHash !== "string") {
      throw new Error(`${relativePath} has no integrity hash in the manifest`);
    }
    const actualHash = await sha256File(absolutePath);
    if (actualHash !== expectedHash) {
      throw new Error(`${relativePath} failed SHA-256 verification`);
    }
    stats.push({ relativePath, size: stat.size });
  }

  log(`${model.id}: manifest verified (${stats.length} files)`);
  for (const entry of stats.sort((left, right) => left.relativePath.localeCompare(right.relativePath))) {
    log(`${model.id}: file ${entry.relativePath}: ${formatBytes(entry.size)}`);
  }
}

async function checkFeatureExtractionModel(model) {
  const startedAt = performance.now();
  const extractor = await pipeline(model.task, model.id, {
    dtype: getModelDtype(model),
    local_files_only: true,
  });
  const loadTimeMs = Math.round(performance.now() - startedAt);

  try {
    const embeddings = await extractor(TEST_SENTENCES, {
      pooling: "mean",
      normalize: true,
    });

    const { vectors, width } = toVectors(embeddings, TEST_SENTENCES.length);
    const related = cosineSimilarity(vectors[0] ?? [], vectors[1] ?? []);
    const unrelated = cosineSimilarity(vectors[0] ?? [], vectors[2] ?? []);
    const margin = related - unrelated;

    const batchStartedAt = performance.now();
    const batchEmbeddings = await extractor(BATCH_SENTENCES, {
      pooling: "mean",
      normalize: true,
    });
    const batch = toVectors(batchEmbeddings, BATCH_SENTENCES.length);
    const batchMs = Math.round(performance.now() - batchStartedAt);

    log(`${model.id}: ready`);
    log(`${model.id}: vector length ${width}`);
    log(`${model.id}: load time ${loadTimeMs} ms`);
    log(`${model.id}: semantic rank margin ${margin.toFixed(6)}`);
    log(`${model.id}: batch ${BATCH_SENTENCES.length} sentences, ${batch.width} dims, ${batchMs} ms`);

    if (model.expectedDimensions && width !== model.expectedDimensions) {
      throw new Error(`${model.id} returned ${width} dimensions, expected ${model.expectedDimensions}.`);
    }

    if (!(related > unrelated)) {
      throw new Error(`${model.id} semantic sanity check failed.`);
    }
  } finally {
    if (typeof extractor.dispose === "function") {
      await extractor.dispose();
    }
  }
}

async function checkTokenClassificationModel(model) {
  const startedAt = performance.now();
  const classifier = await pipeline(model.task, model.id, {
    dtype: getModelDtype(model),
    local_files_only: true,
  });
  const loadTimeMs = Math.round(performance.now() - startedAt);

  try {
    let entities;
    try {
      entities = await classifier("OpenAI released Codex in San Francisco.", {
        aggregation_strategy: "simple",
      });
    } catch {
      entities = await classifier("OpenAI released Codex in San Francisco.");
    }

    const words = entities
      .map((entity) => entity.word)
      .filter(Boolean)
      .join(", ");

    log(`${model.id}: ready`);
    log(`${model.id}: load time ${loadTimeMs} ms`);
    log(`${model.id}: entities ${words || "<none>"}`);

    if (!Array.isArray(entities) || entities.length === 0) {
      throw new Error(`${model.id} did not return entities for the guard sentence.`);
    }
  } finally {
    if (typeof classifier.dispose === "function") {
      await classifier.dispose();
    }
  }
}

async function checkText2TextModel(model) {
  const startedAt = performance.now();
  const generator = await pipeline(model.task, model.id, {
    dtype: getModelDtype(model),
    local_files_only: true,
  });
  const loadTimeMs = Math.round(performance.now() - startedAt);

  try {
    const output = await generator(model.prompt, {
      max_new_tokens: 64,
      num_beams: 4,
    });

    const first = Array.isArray(output) ? output[0] : output;
    const generated = first?.generated_text?.trim() ?? "";

    log(`${model.id}: ready`);
    log(`${model.id}: load time ${loadTimeMs} ms`);
    log(`${model.id}: generated ${generated || "<empty>"}`);

    if (!generated) {
      throw new Error(`${model.id} returned an empty text2text result.`);
    }

    if (
      model.expectedFragment &&
      !generated.toLowerCase().includes(model.expectedFragment.toLowerCase())
    ) {
      throw new Error(`${model.id} output missed expected fragment "${model.expectedFragment}".`);
    }
  } finally {
    if (typeof generator.dispose === "function") {
      await generator.dispose();
    }
  }
}

async function checkFillMaskModel(model) {
  const startedAt = performance.now();
  const unmasker = await pipeline(model.task, model.id, {
    dtype: getModelDtype(model),
    local_files_only: true,
  });
  const loadTimeMs = Math.round(performance.now() - startedAt);

  try {
    const output = await unmasker(model.maskedText, { top_k: 5 });
    const suggestions = (Array.isArray(output) ? output : [output])
      .map((entry) => entry.token_str?.trim())
      .filter(Boolean);

    log(`${model.id}: ready`);
    log(`${model.id}: load time ${loadTimeMs} ms`);
    log(`${model.id}: suggestions ${suggestions.join(", ") || "<none>"}`);

    if (
      Array.isArray(model.expectedTokens) &&
      !suggestions.some((item) =>
        model.expectedTokens.some((expected) => item.toLowerCase() === expected.toLowerCase())
      )
    ) {
      throw new Error(`${model.id} did not suggest any expected paraphrase token.`);
    }
  } finally {
    if (typeof unmasker.dispose === "function") {
      await unmasker.dispose();
    }
  }
}

async function main() {
  env.allowLocalModels = true;
  env.allowRemoteModels = false;
  env.localModelPath = `${MODEL_ROOT}${path.sep}`;

  const rssBefore = rssMb();

  for (const model of MODELS) {
    await verifyBundledFiles(model);
  }

  if (FILES_ONLY) {
    log(`ready: ${MODELS.length} local model bundles passed file verification`);
    return;
  }

  for (const model of MODELS) {
    if (model.storage === "native-models") {
      log(`${model.id}: MLX checkpoint ready for the native paraphrase worker`);
    } else if (model.task === "feature-extraction") {
      await checkFeatureExtractionModel(model);
    } else if (model.task === "token-classification") {
      await checkTokenClassificationModel(model);
    } else if (model.task === "text2text-generation") {
      await checkText2TextModel(model);
    } else if (model.task === "fill-mask") {
      await checkFillMaskModel(model);
    }

    const currentRss = rssMb();
    log(`${model.id}: rss now ${currentRss.toFixed(1)} MB`);
    if (currentRss >= MEMORY_CEILING_MB) {
      throw new Error(`Model memory exceeded ${MEMORY_CEILING_MB} MB RSS.`);
    }
  }

  const rssAfter = rssMb();
  log(`memory rss: ${rssAfter.toFixed(1)} MB (delta ${(rssAfter - rssBefore).toFixed(1)} MB)`);
  log(`memory budget: PASS (< ${MEMORY_CEILING_MB} MB)`);
  log(`ready: ${MODELS.length} local models passed`);
}

main().catch((error) => {
  console.error(`[models:check] ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
});

import fs from "fs/promises";
import path from "path";
import { fileURLToPath } from "url";

import { ModelRegistry } from "@huggingface/transformers";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT_DIR = path.resolve(__dirname, "..");

const DEFAULT_DTYPE = "q8";

function getModelDtype(model) {
  return model.task === "text2text-generation" ? "fp32" : DEFAULT_DTYPE;
}

function getMandatoryFiles(model) {
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

function getOptionalFiles(model) {
  if (model.task === "text2text-generation") {
    return ["special_tokens_map.json", "spiece.model"];
  }

  if (model.id.includes("roberta")) {
    return ["special_tokens_map.json", "merges.txt", "vocab.json"];
  }

  return ["special_tokens_map.json", "vocab.txt"];
}

function getKnownFiles(model) {
  return [...getMandatoryFiles(model), ...getOptionalFiles(model)];
}

function getLegacyFiles(model) {
  if (model.task !== "text2text-generation") {
    return [];
  }

  return [
    "onnx/encoder_model_quantized.onnx",
    "onnx/decoder_model_merged_quantized.onnx",
  ];
}

const MODELS = [
  {
    id: "Xenova/paraphrase-mpnet-base-v2",
    task: "feature-extraction",
    role: "paraphrase-fit",
  },
  {
    id: "Xenova/paraphrase-MiniLM-L6-v2",
    task: "feature-extraction",
    role: "paraphrase-fit",
  },
  {
    id: "Xenova/all-mpnet-base-v2",
    task: "feature-extraction",
    role: "semantic-meaning",
  },
  {
    id: "Xenova/bge-base-en-v1.5",
    task: "feature-extraction",
    role: "retrieval-meaning",
  },
  {
    id: "Xenova/bge-small-en-v1.5",
    task: "feature-extraction",
    role: "retrieval-meaning",
  },
  {
    id: "Xenova/all-MiniLM-L6-v2",
    task: "feature-extraction",
    role: "semantic-meaning",
  },
  {
    id: "Xenova/all-MiniLM-L12-v2",
    task: "feature-extraction",
    role: "secondary-meaning",
  },
  {
    id: "Xenova/bert-base-NER",
    task: "token-classification",
    role: "entity-guard",
  },
  {
    id: "Xenova/distilbert-base-uncased",
    task: "fill-mask",
    role: "mask-suggestions",
  },
  {
    id: "Xenova/distilroberta-base",
    task: "fill-mask",
    role: "mask-suggestions",
  },
];

const force = process.argv.includes("--force");

function log(message) {
  console.log(`[models:download] ${message}`);
}

function encodeModelPath(relativePath) {
  return relativePath
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
}

function modelRoot(model) {
  return path.join(ROOT_DIR, "public", "models", model.id);
}

function manifestPath(model) {
  return path.join(modelRoot(model), "manifest.json");
}

function createModelUrl(model, relativePath) {
  return `https://huggingface.co/${model.id}/resolve/main/${encodeModelPath(relativePath)}?download=1`;
}

async function fetchModelTree(model) {
  const response = await fetch(`https://huggingface.co/api/models/${model.id}/tree/main?recursive=1`);

  if (!response.ok) {
    throw new Error(`Failed to inspect ${model.id} repo tree: HTTP ${response.status}`);
  }

  return response.json();
}

async function resolveDownloadFiles(model) {
  const dtype = getModelDtype(model);
  const [pipelineFiles, repoTree] = await Promise.all([
    ModelRegistry.get_pipeline_files(model.task, model.id, { dtype }),
    fetchModelTree(model),
  ]);

  const availablePaths = new Set(
    repoTree.filter((entry) => entry.type === "file").map((entry) => entry.path)
  );

  const requiredFiles = pipelineFiles.filter((relativePath) => availablePaths.has(relativePath));
  const missingRequired = pipelineFiles.filter((relativePath) => !availablePaths.has(relativePath));

  if (missingRequired.length > 0) {
    throw new Error(
      `${model.id} is missing required files for ${dtype}: ${missingRequired.join(", ")}`
    );
  }

  const optionalFiles = getOptionalFiles(model).filter((relativePath) => availablePaths.has(relativePath));
  return [...new Set([...requiredFiles, ...optionalFiles])];
}

async function ensureDirectory(targetPath) {
  await fs.mkdir(path.dirname(targetPath), { recursive: true });
}

async function fileExists(model, relativePath) {
  return fs
    .access(path.join(modelRoot(model), relativePath))
    .then(() => true)
    .catch(() => false);
}

async function readExistingManifest(model) {
  try {
    const raw = await fs.readFile(manifestPath(model), "utf8");
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed.files)) return null;
    return parsed;
  } catch {
    return null;
  }
}

async function allFilesExist(model, relativePaths) {
  const checks = await Promise.all(relativePaths.map((relativePath) => fileExists(model, relativePath)));
  return checks.every(Boolean);
}

async function resolveExistingLocalFiles(model) {
  const manifest = await readExistingManifest(model);

  if (
    manifest &&
    manifest.modelId === model.id &&
    manifest.task === model.task &&
    manifest.dtype === getModelDtype(model) &&
    await allFilesExist(model, manifest.files) &&
    await allFilesExist(model, getMandatoryFiles(model))
  ) {
    return {
      files: manifest.files,
      manifestExists: true,
      downloadedAt: manifest.downloadedAt,
    };
  }

  if (!await allFilesExist(model, getMandatoryFiles(model))) {
    return null;
  }

  const files = [];
  for (const relativePath of getKnownFiles(model)) {
    if (await fileExists(model, relativePath)) {
      files.push(relativePath);
    }
  }

  return {
    files,
    manifestExists: false,
    downloadedAt: manifest?.downloadedAt,
  };
}

async function downloadFile(model, relativePath) {
  const outputPath = path.join(modelRoot(model), relativePath);
  const alreadyExists = await fileExists(model, relativePath);

  if (alreadyExists && !force) {
    log(`${model.id}: skip ${relativePath}`);
    return;
  }

  await ensureDirectory(outputPath);
  const response = await fetch(createModelUrl(model, relativePath));

  if (!response.ok) {
    throw new Error(`Failed to download ${model.id}/${relativePath}: HTTP ${response.status}`);
  }

  const buffer = Buffer.from(await response.arrayBuffer());
  await fs.writeFile(outputPath, buffer);
  log(`${model.id}: downloaded ${relativePath} (${buffer.length.toLocaleString()} bytes)`);
}

async function verifyFiles(model, relativePaths) {
  const missing = [];

  for (const relativePath of relativePaths) {
    if (!await fileExists(model, relativePath)) {
      missing.push(relativePath);
    }
  }

  if (missing.length > 0) {
    throw new Error(`Missing required files for ${model.id}: ${missing.join(", ")}`);
  }
}

async function pruneLegacyFiles(model, keepFiles) {
  const keepSet = new Set(keepFiles);

  for (const relativePath of getLegacyFiles(model)) {
    if (keepSet.has(relativePath)) continue;

    const absolutePath = path.join(modelRoot(model), relativePath);
    try {
      await fs.rm(absolutePath, { force: true });
      log(`${model.id}: removed legacy ${relativePath}`);
    } catch {
      // Legacy cleanup is best-effort.
    }
  }
}

async function writeManifest(model, files, downloadedAt = new Date().toISOString()) {
  const manifest = {
    modelId: model.id,
    task: model.task,
    role: model.role,
    dtype: getModelDtype(model),
    downloadedAt,
    files,
  };

  await fs.mkdir(modelRoot(model), { recursive: true });
  await fs.writeFile(manifestPath(model), `${JSON.stringify(manifest, null, 2)}\n`);
  log(`${model.id}: wrote manifest ${path.relative(ROOT_DIR, manifestPath(model))}`);
}

async function ensureModel(model) {
  if (!force) {
    const existing = await resolveExistingLocalFiles(model);
    if (existing) {
      log(`${model.id}: using existing bundled files; pass --force to refresh`);

      if (!existing.manifestExists) {
        await writeManifest(model, existing.files, existing.downloadedAt);
      }

      log(`${model.id}: ready (${existing.files.length} files)`);
      return;
    }
  }

  log(`${model.id}: resolving files (${model.task}, ${getModelDtype(model)})`);
  const files = await resolveDownloadFiles(model);
  for (const relativePath of files) {
    await downloadFile(model, relativePath);
  }

  await verifyFiles(model, files);
  await pruneLegacyFiles(model, files);
  await writeManifest(model, files);
  log(`${model.id}: ready (${files.length} files)`);
}

async function main() {
  for (const model of MODELS) {
    await ensureModel(model);
  }
  log(`ready: ${MODELS.length} local models bundled`);
}

main().catch((error) => {
  console.error(`[models:download] ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
});

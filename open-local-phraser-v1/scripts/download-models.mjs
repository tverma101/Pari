import fs from "fs/promises";
import { createReadStream, readFileSync, existsSync } from "fs";
import crypto from "crypto";
import os from "os";
import path from "path";
import { fileURLToPath } from "url";

import { ModelRegistry } from "@huggingface/transformers";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT_DIR = path.resolve(__dirname, "..");

const DEFAULT_DTYPE = "q8";
const NATIVE_ONLY = process.argv.includes("--native-only");
const INSTALL_NATIVE = process.argv.includes("--install-native");
function resolveNativeGenerativeModel() {
  // Config drives the default; env overrides it. This retires Qwen as a baked-in default.
  let cfg = null;
  try {
    cfg = JSON.parse(readFileSync(path.join(ROOT_DIR, "native-models/config.json"), "utf8"));
  } catch {}
  const envId = process.env.PARI_NATIVE_MODEL_ID?.trim();
  const envPath = process.env.PARI_NATIVE_MODEL_PATH?.trim();
  const id = envId || cfg?.nativeModel?.id || "mlx-community/Qwen3.5-4B-MLX-4bit";
  const localPath = envPath
    ? (envPath.startsWith("~/") ? path.join(os.homedir(), envPath.slice(2)) : envPath)
    : (cfg?.nativeModel?.localPath || "native-models/Qwen/Qwen3.5-4B-MLX-4bit");
  const requiredFiles = cfg?.nativeModel?.requiredFiles || [
    "README.md",
    "chat_template.jinja",
    "config.json",
    "model.safetensors",
    "model.safetensors.index.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
  ];
  return {
    id,
    task: "mlx-generation",
    role: "paragraph-generation",
    storage: "native-models",
    localPath,
    requiredFiles,
  };
}
const NATIVE_GENERATIVE_MODEL = resolveNativeGenerativeModel();
  requiredFiles: [
    "README.md",
    "chat_template.jinja",
    "config.json",
    "model.safetensors",
    "model.safetensors.index.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
  ],
};

function getModelDtype(model) {
  if (model.storage === "native-models") return "mlx-4bit";
  return model.task === "text2text-generation" ? "fp32" : DEFAULT_DTYPE;
}

function getMandatoryFiles(model) {
  if (model.storage === "native-models") return model.requiredFiles;

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
  if (model.storage === "native-models") return [];

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
  NATIVE_GENERATIVE_MODEL,
];

const force = process.argv.includes("--force");

if (INSTALL_NATIVE && !NATIVE_ONLY) {
  throw new Error("--install-native is only supported with --native-only so browser models remain in the checkout.");
}

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
  if (model.storage === "native-models") {
    if (INSTALL_NATIVE) {
      const configuredPath = process.env.PARI_NATIVE_MODEL_PATH?.trim();
      if (configuredPath) return path.resolve((configuredPath.startsWith("~") ? path.join(os.homedir(), configuredPath.slice(2)) : configuredPath));
      return path.join(
        os.homedir(),
        "Library",
        "Application Support",
        "Open Local Phraser",
        "Models",
        model.localPath,
      );
    }
    return path.join(ROOT_DIR, model.localPath);
  }
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
  if (model.storage === "native-models") {
    const repoTree = await fetchModelTree(model);
    const availablePaths = new Set(
      repoTree.filter((entry) => entry.type === "file").map((entry) => entry.path)
    );
    const missingRequired = getMandatoryFiles(model).filter((relativePath) => !availablePaths.has(relativePath));
    if (missingRequired.length > 0) {
      throw new Error(`${model.id} is missing required files: ${missingRequired.join(", ")}`);
    }
    return getMandatoryFiles(model);
  }

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

async function sha256File(absolutePath) {
  const hash = crypto.createHash("sha256");
  for await (const chunk of createReadStream(absolutePath)) {
    hash.update(chunk);
  }
  return hash.digest("hex");
}

async function fileHashes(model, relativePaths) {
  const entries = await Promise.all(
    relativePaths.map(async (relativePath) => [
      relativePath,
      await sha256File(path.join(modelRoot(model), relativePath)),
    ])
  );
  return Object.fromEntries(entries);
}

async function manifestHashesMatch(model, manifest) {
  if (!manifest || !manifest.sha256 || typeof manifest.sha256 !== "object") return false;

  const manifestFiles = Array.isArray(manifest.files) ? manifest.files : [];
  const expectedFiles = [...new Set([...getMandatoryFiles(model), ...manifestFiles])];
  if (!expectedFiles.every((relativePath) => typeof manifest.sha256[relativePath] === "string")) {
    return false;
  }

  const hashes = await fileHashes(model, expectedFiles);
  return expectedFiles.every((relativePath) => hashes[relativePath] === manifest.sha256[relativePath]);
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
      manifest,
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
    manifest: null,
    downloadedAt: manifest?.downloadedAt,
  };
}

async function downloadFile(model, relativePath, replace = false) {
  const outputPath = path.join(modelRoot(model), relativePath);
  const alreadyExists = await fileExists(model, relativePath);

  if (alreadyExists && !force && !replace) {
    log(`${model.id}: skip ${relativePath}`);
    return;
  }

  await ensureDirectory(outputPath);
  const response = await fetch(createModelUrl(model, relativePath));

  if (!response.ok) {
    throw new Error(`Failed to download ${model.id}/${relativePath}: HTTP ${response.status}`);
  }

  const temporaryPath = `${outputPath}.part-${process.pid}-${Math.random().toString(36).slice(2)}`;
  let downloadedBytes = 0;
  try {
    const handle = await fs.open(temporaryPath, "w");
    try {
      if (!response.body) throw new Error("The model response did not contain a body.");
      const reader = response.body.getReader();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        if (!value) continue;
        const chunk = Buffer.from(value);
        await handle.write(chunk);
        downloadedBytes += chunk.length;
        if (downloadedBytes > 0 && downloadedBytes % (100 * 1024 * 1024) < chunk.length) {
          log(`${model.id}: ${relativePath} ${(downloadedBytes / 1024 / 1024).toFixed(0)} MB downloaded`);
        }
      }
    } finally {
      await handle.close();
    }
    await fs.rename(temporaryPath, outputPath);
  } finally {
    await fs.rm(temporaryPath, { force: true });
  }
  log(`${model.id}: downloaded ${relativePath} (${downloadedBytes.toLocaleString()} bytes)`);
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
  if (model.storage === "native-models") return;

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
  const sha256 = await fileHashes(model, files);
  const manifest = {
    modelId: model.id,
    task: model.task,
    role: model.role,
    ...(model.storage ? { storage: model.storage, localPath: model.localPath } : {}),
    dtype: getModelDtype(model),
    downloadedAt,
    files,
    sha256,
  };

  await fs.mkdir(modelRoot(model), { recursive: true });
  await fs.writeFile(manifestPath(model), `${JSON.stringify(manifest, null, 2)}\n`);
  log(`${model.id}: wrote manifest ${path.relative(ROOT_DIR, manifestPath(model))}`);
}

async function ensureModel(model) {
  let refreshExistingFiles = false;
  if (!force) {
    const existing = await resolveExistingLocalFiles(model);
    if (existing) {
      const hashesMatch = await manifestHashesMatch(model, existing.manifest);
      if (hashesMatch) {
        log(`${model.id}: using existing verified bundled files; pass --force to refresh`);
        return;
      }

      if (existing.manifest) {
        log(`${model.id}: manifest hash check failed; refreshing bundled files`);
        refreshExistingFiles = true;
      } else {
        log(`${model.id}: adding integrity hashes to the existing bundled files`);
        await writeManifest(model, existing.files, existing.downloadedAt);
        return;
      }
    }
  }

  log(`${model.id}: resolving files (${model.task}, ${getModelDtype(model)})`);
  const files = await resolveDownloadFiles(model);
  for (const relativePath of files) {
    await downloadFile(model, relativePath, Boolean(force) || refreshExistingFiles);
  }

  await verifyFiles(model, files);
  await pruneLegacyFiles(model, files);
  await writeManifest(model, files);
  log(`${model.id}: ready (${files.length} files)`);
}

async function main() {
  const selectedModels = NATIVE_ONLY ? [NATIVE_GENERATIVE_MODEL] : MODELS;
  const results = await Promise.allSettled(selectedModels.map((model) => ensureModel(model)));
  const failures = results
    .map((result, index) => result.status === "rejected" ? `${selectedModels[index].id}: ${result.reason instanceof Error ? result.reason.message : String(result.reason)}` : null)
    .filter(Boolean);
  if (failures.length > 0) throw new Error(failures.join("\n"));
  log(NATIVE_ONLY && INSTALL_NATIVE
    ? `ready: ${selectedModels.length} native model installed outside the app bundle`
    : `ready: ${selectedModels.length} local models downloaded`);
}

main().catch((error) => {
  console.error(`[models:download] ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
});

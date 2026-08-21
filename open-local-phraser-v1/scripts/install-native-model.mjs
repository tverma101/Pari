import fs from "fs/promises";
import { createReadStream } from "fs";
import crypto from "crypto";
import os from "os";
import path from "path";
import { fileURLToPath } from "url";

const ROOT_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const MODEL_ID = "Qwen/Qwen3-4B-MLX-4bit";
const MODEL_RELATIVE_PATH = "native-models/Qwen/Qwen3-4B-MLX-4bit";
const SOURCE_DIR = path.join(ROOT_DIR, MODEL_RELATIVE_PATH);
const configuredTarget = process.env.PARI_NATIVE_MODEL_PATH?.trim();
const TARGET_DIR = configuredTarget
  ? path.resolve(configuredTarget.startsWith("~") ? path.join(os.homedir(), configuredTarget.slice(2)) : configuredTarget)
  : path.join(os.homedir(), "Library", "Application Support", "Open Local Phraser", "Models", MODEL_RELATIVE_PATH);

function log(message) {
  console.log(`[models:install] ${message}`);
}

async function sha256File(absolutePath) {
  const hash = crypto.createHash("sha256");
  for await (const chunk of createReadStream(absolutePath)) hash.update(chunk);
  return hash.digest("hex");
}

async function readManifest(directory) {
  const manifest = JSON.parse(await fs.readFile(path.join(directory, "manifest.json"), "utf8"));
  if (manifest.modelId !== MODEL_ID || !Array.isArray(manifest.files) || !manifest.sha256) {
    throw new Error(`The native model manifest at ${directory} is not a verified ${MODEL_ID} manifest.`);
  }
  return manifest;
}

async function verify(directory) {
  const manifest = await readManifest(directory);
  for (const relativePath of manifest.files) {
    const absolutePath = path.join(directory, relativePath);
    const stat = await fs.stat(absolutePath);
    if (!stat.isFile() || stat.size <= 0) throw new Error(`Missing or empty native model file: ${relativePath}`);
    const expected = manifest.sha256[relativePath];
    if (typeof expected !== "string" || await sha256File(absolutePath) !== expected) {
      throw new Error(`SHA-256 verification failed for native model file: ${relativePath}`);
    }
  }
  return manifest;
}

async function main() {
  const sourceManifest = await verify(SOURCE_DIR);
  if (path.resolve(SOURCE_DIR) !== path.resolve(TARGET_DIR)) {
    await fs.mkdir(path.dirname(TARGET_DIR), { recursive: true });
    const temporaryTarget = `${TARGET_DIR}.install-${process.pid}`;
    await fs.rm(temporaryTarget, { recursive: true, force: true });
    log(`copying ${MODEL_ID} outside the app bundle`);
    await fs.cp(SOURCE_DIR, temporaryTarget, { recursive: true, force: true });
    await verify(temporaryTarget);
    await fs.cp(temporaryTarget, TARGET_DIR, { recursive: true, force: true });
    await fs.rm(temporaryTarget, { recursive: true, force: true });
  }
  await verify(TARGET_DIR);
  log(`ready at ${TARGET_DIR}`);
  log(`verified ${sourceManifest.files.length} files; Pari can connect to it on the next generation`);
}

main().catch((error) => {
  console.error(`[models:install] ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
});

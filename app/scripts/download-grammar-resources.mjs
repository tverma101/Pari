import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT_DIR = path.resolve(__dirname, "..");
const RESOURCE_DIR = path.join(ROOT_DIR, "research", "grammar-sources");
const force = process.argv.includes("--force");

const RESOURCES = [
  {
    id: "harper",
    version: "v2.7.0",
    archiveUrl: "https://github.com/Automattic/harper/archive/refs/tags/v2.7.0.tar.gz",
    license: "Apache-2.0",
    intendedUse: "Offline English grammar linting and WebAssembly integration research",
    expectedFile: "LICENSE",
  },
  {
    id: "languagetool",
    version: "v6.8",
    archiveUrl: "https://github.com/languagetool-org/languagetool/archive/refs/tags/v6.8.tar.gz",
    license: "LGPL-2.1-or-later",
    intendedUse: "English grammar-rule coverage and rule-authoring research",
    expectedFile: "COPYING.txt",
  },
  {
    id: "gector",
    version: "master",
    commit: "3d41d2841512d2690cffce1b5ac6795fe9a0a5dd",
    archiveUrl: "https://github.com/grammarly/gector/archive/3d41d2841512d2690cffce1b5ac6795fe9a0a5dd.tar.gz",
    license: "Apache-2.0",
    intendedUse: "Edit-tagging grammar correction and local model conversion research",
    expectedFile: "LICENSE",
  },
  {
    id: "ud-english-ewt",
    version: "r2.9",
    commit: "c491d62a7a0447946ac85b11308083ea61328ece",
    archiveUrl: "https://github.com/UniversalDependencies/UD_English-EWT/archive/refs/tags/r2.9.tar.gz",
    license: "CC BY-SA 4.0",
    intendedUse: "Held-out English grammar and dependency-flow evaluation",
    expectedFile: "README.md",
  },
];

function log(message) {
  console.log(`[research:grammar:download] ${message}`);
}

async function exists(target) {
  try {
    await fs.access(target);
    return true;
  } catch {
    return false;
  }
}

function run(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd: ROOT_DIR, stdio: ["ignore", "pipe", "pipe"], ...options });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) resolve({ stdout, stderr });
      else reject(new Error(`${command} ${args.join(" ")} exited with ${code}: ${stderr || stdout}`));
    });
  });
}

async function downloadToFile(url, outputPath) {
  const response = await fetch(url, { redirect: "follow" });
  if (!response.ok) throw new Error(`HTTP ${response.status} while downloading ${url}`);
  const buffer = Buffer.from(await response.arrayBuffer());
  await fs.writeFile(outputPath, buffer);
  return buffer;
}

async function sha256(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

async function downloadResource(resource) {
  const targetDir = path.join(RESOURCE_DIR, resource.id);
  const metadataPath = path.join(targetDir, "resource.json");
  if (!force && await exists(metadataPath) && await exists(path.join(targetDir, resource.expectedFile))) {
    log(`${resource.id}: already present; use --force to refresh`);
    return;
  }

  const workDir = path.join(RESOURCE_DIR, `.work-${resource.id}`);
  const archivePath = path.join(workDir, `${resource.id}.tar.gz`);
  await fs.rm(workDir, { recursive: true, force: true });
  await fs.mkdir(workDir, { recursive: true });
  await fs.mkdir(RESOURCE_DIR, { recursive: true });

  log(`${resource.id}: downloading ${resource.version}`);
  const archive = await downloadToFile(resource.archiveUrl, archivePath);
  const archiveSha256 = await sha256(archive);
  await run("tar", ["-xzf", archivePath, "-C", workDir]);

  const entries = (await fs.readdir(workDir)).filter((entry) => entry !== path.basename(archivePath));
  if (entries.length !== 1) throw new Error(`${resource.id}: expected one extracted source directory, found ${entries.join(", ")}`);
  const extractedDir = path.join(workDir, entries[0]);
  if (!await exists(path.join(extractedDir, resource.expectedFile))) {
    throw new Error(`${resource.id}: extracted snapshot is missing ${resource.expectedFile}`);
  }

  await fs.rm(targetDir, { recursive: true, force: true });
  await fs.rename(extractedDir, targetDir);
  const metadata = {
    id: resource.id,
    version: resource.version,
    commit: resource.commit ?? null,
    sourceUrl: resource.archiveUrl,
    license: resource.license,
    intendedUse: resource.intendedUse,
    downloadedAt: new Date().toISOString(),
    archiveSha256,
    expectedFile: resource.expectedFile,
  };
  await fs.writeFile(metadataPath, `${JSON.stringify(metadata, null, 2)}\n`);
  await fs.rm(workDir, { recursive: true, force: true });
  log(`${resource.id}: ready (${archiveSha256.slice(0, 12)}…)`);
}

await Promise.all(RESOURCES.map(downloadResource));
log(`completed ${RESOURCES.length} pinned resources in parallel`);

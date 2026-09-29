import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT_DIR = path.resolve(__dirname, "..");
const RESOURCE_DIR = path.join(ROOT_DIR, "research", "grammar-sources");

const RESOURCE_IDS = ["harper", "languagetool", "gector", "ud-english-ewt"];

async function readJSON(filePath) {
  return JSON.parse(await fs.readFile(filePath, "utf8"));
}

for (const id of RESOURCE_IDS) {
  const resourceDir = path.join(RESOURCE_DIR, id);
  const metadata = await readJSON(path.join(resourceDir, "resource.json"));
  const expectedFile = path.join(resourceDir, metadata.expectedFile);
  const stat = await fs.stat(expectedFile);
  if (!stat.isFile() || stat.size === 0) throw new Error(`${id}: ${metadata.expectedFile} is missing or empty`);
  if (!metadata.sourceUrl || !metadata.license || !metadata.downloadedAt || !metadata.archiveSha256) {
    throw new Error(`${id}: resource.json is missing provenance or license metadata`);
  }
  console.log(`[research:grammar:check] ${id}: ${metadata.version} ${metadata.license} ready`);
}

console.log(`[research:grammar:check] ${RESOURCE_IDS.length} pinned resources PASS`);

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const APP_BINARY = path.join(ROOT_DIR, "release", "Pari.app", "Contents", "MacOS", "OpenLocalPhraserV2");
const NATIVE_MODEL_DIR = path.join(ROOT_DIR, "native-models", "Qwen", "Qwen3.5-4B-MLX-4bit");
const BACKEND_TIMEOUT_MS = 30_000;
const HEADLESS_TIMEOUT_MS = 180_000;

function waitForReady(child) {
  return new Promise((resolve, reject) => {
    let output = "";
    const timer = setTimeout(() => reject(new Error(`Timed out waiting for the style backend: ${output}`)), BACKEND_TIMEOUT_MS);
    const consume = (chunk) => {
      output += chunk.toString();
      const match = output.match(/agent style backend ready http:\/\/127\.0\.0\.1:(\d+)/);
      if (!match) return;
      clearTimeout(timer);
      resolve({ port: Number(match[1]), output });
    };
    child.stdout.on("data", consume);
    child.stderr.on("data", consume);
    child.once("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.once("exit", (code, signal) => {
      if (code !== null) {
        clearTimeout(timer);
        reject(new Error(`Style backend exited before ready: code=${code} signal=${signal} output=${output}`));
      }
    });
  });
}

function waitForExit(child, timeoutMs) {
  return new Promise((resolve, reject) => {
    let output = "";
    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      reject(new Error(`Timed out waiting for installed custom-mode smoke test: ${output}`));
    }, timeoutMs);
    const consume = (chunk) => {
      output += chunk.toString();
    };
    child.stdout.on("data", consume);
    child.stderr.on("data", consume);
    child.once("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.once("exit", (code, signal) => {
      clearTimeout(timer);
      resolve({ code, signal, output });
    });
  });
}

async function main() {
  const backend = spawn(APP_BINARY, ["--agent-style-backend", "--idle-timeout-seconds", "120"], {
    cwd: ROOT_DIR,
    stdio: ["ignore", "pipe", "pipe"],
  });
  let baseURL;
  let createdID;
  let headless;
  const styleName = `QA Warm Direct ${process.pid}`;

  try {
    const ready = await waitForReady(backend);
    baseURL = `http://127.0.0.1:${ready.port}`;

    async function request(route, options = {}) {
      const response = await fetch(`${baseURL}${route}`, {
        ...options,
        headers: {
          ...(options.body ? { "content-type": "application/json" } : {}),
          ...(options.headers ?? {}),
        },
      });
      const payload = response.status === 204 ? null : await response.json();
      return { response, payload };
    }

    const created = await request("/v1/styles", {
      method: "POST",
      body: JSON.stringify({
        name: styleName,
        description: "A saved agent-built mode for warmer, direct prose.",
        instructions: "Keep the meaning intact. Use plain English, direct verbs, and a noticeably warmer human tone without sounding childish.",
        baseMode: "personal",
        strength: 64,
        tweaks: {
          strengthOffset: 8,
          warmthPolish: true,
          preserveSentenceCount: true,
        },
      }),
    });
    assert.equal(created.response.status, 201);
    assert.equal(created.payload.ok, true);
    createdID = created.payload.style.id;
    assert.equal(created.payload.style.name, styleName);
    assert.equal(created.payload.style.tweaks.warmthPolish, true);
    assert.equal(created.payload.style.tweaks.strengthOffset, 8);

    headless = spawn(APP_BINARY, ["--headless", "--headless-custom-style"], {
      cwd: ROOT_DIR,
      env: {
        ...process.env,
        PARI_HEADLESS_CUSTOM_STYLE_NAME: styleName,
        // The packaged app intentionally contains no Qwen checkpoint. This
        // proves the same installed app can connect to a separately installed
        // model without changing the package contents.
        PARI_NATIVE_MODEL_PATH: NATIVE_MODEL_DIR,
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    const smoke = await waitForExit(headless, HEADLESS_TIMEOUT_MS);
    assert.equal(smoke.code, 0, `installed custom-mode smoke test failed: ${smoke.output}`);
    assert.match(smoke.output, /headless PASS/);
    assert.match(smoke.output, new RegExp(`activeMode=${styleName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`));
    assert.match(smoke.output, /generator=native-mlx/);
    console.log("installed saved custom mode, external native generator, shared engine, and UI selection PASS");
  } finally {
    if (headless?.exitCode === null) {
      headless.kill("SIGTERM");
    }
    if (baseURL && createdID && backend.exitCode === null) {
      await fetch(`${baseURL}/v1/styles/${createdID}`, { method: "DELETE" }).catch(() => {});
    }
    if (baseURL && backend.exitCode === null) {
      await fetch(`${baseURL}/v1/shutdown`, { method: "POST" }).catch(() => {});
    }
    if (backend.exitCode === null) {
      backend.kill("SIGTERM");
    }
  }
}

main().catch((error) => {
  console.error(error.stack ?? error);
  process.exitCode = 1;
});

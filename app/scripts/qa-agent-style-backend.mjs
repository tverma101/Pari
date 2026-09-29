import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const APP_BINARY = path.join(ROOT_DIR, "release", "Pari.app", "Contents", "MacOS", "OpenLocalPhraserV2");
const TIMEOUT_MS = 12_000;

const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

function waitForReady(child) {
  return new Promise((resolve, reject) => {
    let output = "";
    const timer = setTimeout(() => reject(new Error(`Timed out waiting for the style backend: ${output}`)), TIMEOUT_MS);
    const consume = (chunk) => {
      output += chunk.toString();
      const match = output.match(/agent style backend ready http:\/\/127\.0\.0\.1:(\d+)/);
      if (!match) return;
      clearTimeout(timer);
      resolve({ port: Number(match[1]), output });
    };
    child.stdout.on("data", consume);
    child.stderr.on("data", (chunk) => {
      output += chunk.toString();
    });
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

function waitForExit(child) {
  return new Promise((resolve) => {
    if (child.exitCode !== null || child.signalCode !== null) {
      resolve({ code: child.exitCode, signal: child.signalCode });
      return;
    }
    child.once("exit", (code, signal) => resolve({ code, signal }));
  });
}

async function main() {
  const child = spawn(APP_BINARY, ["--agent-style-backend", "--idle-timeout-seconds", "2"], {
    cwd: ROOT_DIR,
    stdio: ["ignore", "pipe", "pipe"],
  });
  let baseURL;
  let createdID;

  try {
    const ready = await waitForReady(child);
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

    let result = await request("/health");
    assert.equal(result.response.status, 200);
    assert.equal(result.payload.ok, true);
    assert.equal(result.payload.service, "pari-agent-style-backend");
    assert.equal(result.payload.idleTimeoutSeconds, 2);

    const uniqueName = `QA style ${process.pid}`;
    result = await request("/v1/styles", {
      method: "POST",
      body: JSON.stringify({
        name: uniqueName,
        description: "A concise, human style for the local agent.",
        instructions: "Use direct verbs, preserve the writer's meaning, and make requests feel considerate.",
        baseMode: "warmth",
        strength: 72,
        tweaks: {
          strengthOffset: 6,
          warmthPolish: true,
          preserveSentenceCount: true,
        },
      }),
    });
    assert.equal(result.response.status, 201);
    assert.equal(result.payload.ok, true);
    createdID = result.payload.style.id;
    assert.match(createdID, /^[0-9a-f-]{36}$/);
    assert.equal(result.payload.style.baseMode, "warmth");
    assert.equal(result.payload.style.strength, 72);
    assert.equal(result.payload.style.tweaks.strengthOffset, 6);
    assert.equal(result.payload.style.tweaks.warmthPolish, true);
    assert.equal(result.payload.style.tweaks.preserveSentenceCount, true);

    result = await request(`/v1/styles/${createdID}`, {
      method: "PATCH",
      body: JSON.stringify({ instructions: "Use plain English, keep the meaning intact, and sound noticeably warmer." }),
    });
    assert.equal(result.response.status, 200);
    assert.equal(result.payload.style.name, uniqueName);
    assert.equal(result.payload.style.instructions, "Use plain English, keep the meaning intact, and sound noticeably warmer.");

    result = await request("/v1/styles");
    assert.equal(result.response.status, 200);
    assert.equal(result.payload.styles.some((style) => style.id === createdID), true);

    result = await request(`/v1/styles/${createdID}`, { method: "DELETE" });
    assert.equal(result.response.status, 200);
    assert.equal(result.payload.deletedId, createdID);
    createdID = undefined;

    const exit = await Promise.race([
      waitForExit(child),
      wait(TIMEOUT_MS).then(() => null),
    ]);
    assert.ok(exit, "headless style backend did not auto-shut down after inactivity");
    assert.equal(exit.code, 0);
    console.log("agent-style-backend lifecycle, CRUD, persistence boundary, and idle shutdown PASS");
  } finally {
    if (baseURL && createdID && child.exitCode === null) {
      await fetch(`${baseURL}/v1/styles/${createdID}`, { method: "DELETE" }).catch(() => {});
    }
    if (child.exitCode === null) {
      child.kill("SIGTERM");
      await waitForExit(child);
    }
  }
}

main().catch((error) => {
  console.error(error.stack ?? error);
  process.exitCode = 1;
});

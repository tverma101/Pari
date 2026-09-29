#!/usr/bin/env node
// Minimal local paraphrase API over the FreeLLMAPI router (127.0.0.1:31415).
// Node stdlib only: no dependencies, no Pari engine code, no gates.
//
// Env:
//   PARI_FREELLM_API_KEY      required for /paraphrase (router key, never logged)
//   PARI_FREELLM_BASE_URL     default http://127.0.0.1:31415/v1
//   PARI_PARAPHRASE_MODEL     default model id (default llama-3.3-70b-fp8-fast)
//   PARI_PARAPHRASE_PORT      default 31416
//   PARI_PARAPHRASE_TOKEN     optional; when set, requests must present it as bearer/x-api-key
//   PARI_PARAPHRASE_TIMEOUT_MS  router call timeout, 5000..300000 (default 120000)

import http from "node:http";

const HOST = "127.0.0.1";
const PORT = clampInt(process.env.PARI_PARAPHRASE_PORT, 1, 65535, 31416);
const ROUTER_BASE = (process.env.PARI_FREELLM_BASE_URL || "http://127.0.0.1:31415/v1").replace(/\/+$/, "");
const ROUTER_KEY = process.env.PARI_FREELLM_API_KEY || "";
const DEFAULT_MODEL = process.env.PARI_PARAPHRASE_MODEL || "llama-3.3-70b-fp8-fast";
const AUTH_TOKEN = process.env.PARI_PARAPHRASE_TOKEN || "";
const ROUTER_TIMEOUT_MS = clampInt(process.env.PARI_PARAPHRASE_TIMEOUT_MS, 5000, 300000, 120000);

const MAX_BODY_BYTES = 256 * 1024;
const MAX_TEXT_CHARS = 20000;
const MAX_INSTRUCTION_CHARS = 2000;
const STRENGTHS = new Set(["light", "balanced", "strong"]);

function clampInt(raw, min, max, fallback) {
  const n = Number.parseInt(raw, 10);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

function sendJson(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
  });
  res.end(body);
}

function readBody(req, res) {
  return new Promise((resolve) => {
    const chunks = [];
    let size = 0;
    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        sendJson(res, 413, { ok: false, error: "request_too_large", detail: `Body exceeds ${MAX_BODY_BYTES} bytes` });
        req.destroy();
        resolve(null);
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}"));
      } catch {
        sendJson(res, 400, { ok: false, error: "invalid_json", detail: "Body must be valid JSON" });
        resolve(null);
      }
    });
    req.on("error", () => resolve(null));
  });
}

function authorized(req) {
  if (!AUTH_TOKEN) return true;
  const header = req.headers.authorization || "";
  const bearer = header.startsWith("Bearer ") ? header.slice(7) : "";
  const xkey = req.headers["x-api-key"] || "";
  return bearer === AUTH_TOKEN || xkey === AUTH_TOKEN;
}

const STRENGTH_LINES = {
  light: "Make the smallest wording changes that improve flow and grammar; stay close to the original phrasing.",
  balanced: "Rewrite the sentences so they read clearly and naturally while keeping the original structure recognizable.",
  strong: "Substantially rephrase sentence structure and word choice into a fresh, natural paragraph, while preserving every fact and the writer's intent.",
};

function buildInstruction({ text, strength, instructions }) {
  const lines = [
    "Rewrite the text below as a careful, highly capable English editor.",
    "",
    "Rules:",
    "- Return only the rewritten paragraph. No title, preface, bullets, explanation, or quotation marks.",
    "- This is paraphrasing, not summarizing: preserve every fact, number, name, link, date, measurement, quoted phrase, negation, and modality (must/may/could), and keep the writer's point of view.",
    "- Keep the same number of sentences unless the source is genuinely broken; if it is, rebuild it into complete grammatical sentences without inventing information.",
    "- Do not change quantity scope or strength: never turn \"most\" into \"many\", \"some\" into \"few\", or \"all\" into \"many\".",
    "- Improve flow, cohesion, punctuation, and natural English wording.",
    STRENGTH_LINES[strength],
  ];
  if (instructions) lines.push(`Additional editor guidance: ${instructions}`);
  lines.push("", "Original paragraph:", text, "", "Rewritten paragraph:");
  return lines.join("\n");
}

function cleanOutput(raw) {
  let text = String(raw);
  text = text.replace(/<think>[\s\S]*?<\/think>/gi, "").trim();
  const fence = text.match(/^```[a-zA-Z0-9_-]*\n([\s\S]*?)\n```$/);
  if (fence) text = fence[1];
  text = text.replace(/^(?:rewritten paragraph|paraphrase|output|rewrite)\s*:\s*/i, "").trim();
  const quoted = text.match(/^"([\s\S]*)"$/);
  if (quoted) text = quoted[1];
  return text.trim();
}

async function routerCall(path, { method = "GET", body, timeoutMs = ROUTER_TIMEOUT_MS } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (ROUTER_KEY) headers.Authorization = `Bearer ${ROUTER_KEY}`;
  const response = await fetch(ROUTER_BASE + path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(timeoutMs),
  });
  const full = (await response.text()).slice(0, 8_000_000);
  let json = null;
  try {
    json = JSON.parse(full);
  } catch {
    // non-JSON error body is surfaced as text below
  }
  return { status: response.status, ok: response.ok, json, text: full.slice(0, 4000) };
}

function routerError(res, err) {
  if (err && (err.name === "TimeoutError" || err.name === "AbortError")) {
    sendJson(res, 504, { ok: false, error: "router_timeout", detail: `FreeLLMAPI did not respond within ${ROUTER_TIMEOUT_MS} ms` });
    return;
  }
  sendJson(res, 502, { ok: false, error: "router_unreachable", detail: `FreeLLMAPI not reachable at ${ROUTER_BASE}: ${err && err.message ? err.message : err}` });
}

async function handleHealth(res) {
  try {
    const result = await routerCall("/models", { timeoutMs: 2500 });
    const count = result.json && Array.isArray(result.json.data) ? result.json.data.length : null;
    sendJson(res, 200, {
      ok: true,
      service: "pari-paraphrase-api",
      router: { base_url: ROUTER_BASE, reachable: true, models: count },
      default_model: DEFAULT_MODEL,
      auth_required: Boolean(AUTH_TOKEN),
    });
  } catch {
    sendJson(res, 200, {
      ok: true,
      service: "pari-paraphrase-api",
      router: { base_url: ROUTER_BASE, reachable: false },
      default_model: DEFAULT_MODEL,
      auth_required: Boolean(AUTH_TOKEN),
    });
  }
}

async function handleModels(res) {
  try {
    const result = await routerCall("/models");
    if (!result.ok) {
      sendJson(res, 502, { ok: false, error: "router_error", status: result.status, detail: result.text.slice(0, 500) });
      return;
    }
    const data = Array.isArray(result.json && result.json.data) ? result.json.data : [];
    sendJson(res, 200, { ok: true, count: data.length, models: data.map((m) => m && m.id).filter(Boolean) });
  } catch (err) {
    routerError(res, err);
  }
}

async function handleParaphrase(req, res) {
  if (!ROUTER_KEY) {
    sendJson(res, 503, { ok: false, error: "missing_api_key", detail: "Set PARI_FREELLM_API_KEY in the environment before starting the server" });
    return;
  }
  const body = await readBody(req, res);
  if (body === null) return;

  const text = typeof body.text === "string" ? body.text.trim() : "";
  if (!text) {
    sendJson(res, 400, { ok: false, error: "invalid_request", detail: "`text` must be a non-empty string" });
    return;
  }
  if (text.length > MAX_TEXT_CHARS) {
    sendJson(res, 400, { ok: false, error: "invalid_request", detail: `\`text\` exceeds ${MAX_TEXT_CHARS} characters` });
    return;
  }
  const strength = body.strength === undefined ? "balanced" : body.strength;
  if (!STRENGTHS.has(strength)) {
    sendJson(res, 400, { ok: false, error: "invalid_request", detail: "`strength` must be one of light, balanced, strong" });
    return;
  }
  const instructions = typeof body.instructions === "string" ? body.instructions.trim().slice(0, MAX_INSTRUCTION_CHARS) : "";
  const model = typeof body.model === "string" && body.model.trim() ? body.model.trim().slice(0, 200) : DEFAULT_MODEL;
  const maxTokens = clampInt(body.max_tokens, 96, 1024, 512);

  const started = Date.now();
  let result;
  try {
    result = await routerCall("/chat/completions", {
      method: "POST",
      body: {
        model,
        messages: [{ role: "user", content: buildInstruction({ text, strength, instructions }) }],
        max_tokens: maxTokens,
        temperature: 0.0,
        stream: false,
      },
    });
  } catch (err) {
    routerError(res, err);
    return;
  }

  if (!result.ok) {
    sendJson(res, 502, { ok: false, error: "router_error", status: result.status, model, detail: result.text.slice(0, 500) });
    return;
  }
  const choice = result.json && result.json.choices && result.json.choices[0];
  const raw = choice && choice.message && typeof choice.message.content === "string" ? choice.message.content : "";
  if (!raw.trim()) {
    sendJson(res, 502, { ok: false, error: "empty_response", model, detail: "Router returned no message content" });
    return;
  }
  sendJson(res, 200, {
    ok: true,
    text: cleanOutput(raw),
    model,
    served_model: typeof result.json.model === "string" ? result.json.model : model,
    finish_reason: choice.finish_reason || null,
    usage: result.json.usage || {},
    duration_ms: Date.now() - started,
  });
}

const server = http.createServer((req, res) => {
  const started = Date.now();
  const path = (req.url || "/").split("?")[0];
  res.on("finish", () => {
    console.log(`${req.method} ${path} ${res.statusCode} ${Date.now() - started}ms`);
  });

  if (!authorized(req)) {
    sendJson(res, 401, { ok: false, error: "unauthorized", detail: "Missing or invalid bearer token" });
    return;
  }
  if (req.method === "GET" && path === "/health") {
    handleHealth(res);
    return;
  }
  if (req.method === "GET" && path === "/models") {
    handleModels(res);
    return;
  }
  if (req.method === "POST" && path === "/paraphrase") {
    handleParaphrase(req, res);
    return;
  }
  if (path === "/health" || path === "/models" || path === "/paraphrase") {
    sendJson(res, 405, { ok: false, error: "method_not_allowed" });
    return;
  }
  sendJson(res, 404, { ok: false, error: "not_found" });
});

server.listen(PORT, HOST, () => {
  console.log(`pari-paraphrase-api listening on http://${HOST}:${PORT} (router: ${ROUTER_BASE}, default model: ${DEFAULT_MODEL})`);
});

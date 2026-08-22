#!/usr/bin/env node
/**
 * QuillBot chunker — works around the tiny free-tier char limit (~125 words / ~600 chars).
 *
 * Each corpus `input` is split into sentence chunks that fit the limit, so you can
 * paste one chunk at a time into QuillBot (Fluency / Standard) and stitch results
 * back under the same `id`. This is a
 * manual-paste helper that writes captures-compatible JSONL.
 *
 * Usage:
 *   node scripts/quillbot-chunker.mjs --corpus benchmarks/quillbot/corpus.frozen.json --out /tmp/quillbot-chunks.jsonl
 *   # then paste each chunk, collect outputs, and assemble:
 *   node scripts/quillbot-chunker.mjs --assemble /tmp/quillbot-chunks.jsonl --responses /tmp/my-pastes.jsonl --out benchmarks/quillbot/captures/quillbot-fluency.jsonl
 *
 * For quick single-file export (one chunk per line):
 *   node scripts/quillbot-chunker.mjs --export-chunks benchmarks/quillbot/corpus.frozen.json --limit 600
 */
import fs from "fs";
import path from "path";

const args = process.argv.slice(2);
const argVal = (f) => { const i = args.indexOf(f); return i >= 0 ? args[i+1] : undefined; };

function splitIntoChunks(text, limit) {
  const sentences = text.match(/[^.!?]+[.!?]+|[^.!?]+$/g) ?? [text];
  const chunks = [];
  let cur = "";
  for (const s of sentences) {
    const cand = cur ? `${cur} ${s.trim()}` : s.trim();
    if (cand.length > limit && cur) { chunks.push(cur); cur = s.trim(); }
    else cur = cand;
  }
  if (cur) chunks.push(cur);
  // hard split if single sentence still too long
  const out = [];
  for (const c of chunks) {
    if (c.length <= limit) out.push(c);
    else {
      for (let i=0;i<c.length;i+=limit) out.push(c.slice(i, i+limit));
    }
  }
  return out;
}

if (argVal("--export-chunks")) {
  const corpusPath = argVal("--export-chunks");
  const limit = parseInt(argVal("--limit") ?? "600", 10);
  const corpus = JSON.parse(fs.readFileSync(corpusPath, "utf8"));
  for (const cas of corpus.cases) {
    const chunks = splitIntoChunks(cas.input, limit);
    chunks.forEach((ch, idx) => {
      const label = chunks.length > 1 ? `${cas.id}#${idx+1}/${chunks.length}` : cas.id;
      console.log(`[${label}] (${ch.length} chars)`);
      console.log(ch);
      console.log("---");
    });
  }
} else if (argVal("--corpus")) {
  const corpusPath = argVal("--corpus");
  const outPath = argVal("--out") ?? "/tmp/quillbot-chunks.jsonl";
  const limit = parseInt(argVal("--limit") ?? "600", 10);
  const corpus = JSON.parse(fs.readFileSync(corpusPath, "utf8"));
  const lines = [];
  for (const cas of corpus.cases) {
    const chunks = splitIntoChunks(cas.input, limit);
    chunks.forEach((ch, idx) => lines.push(JSON.stringify({ id: cas.id, chunkIndex: idx, chunkCount: chunks.length, input: ch })));
  }
  fs.writeFileSync(outPath, lines.join("\n")+"\n");
  console.log(`Wrote ${lines.length} chunks (${corpus.cases.length} cases) -> ${outPath}`);
  console.log(`Paste each chunk into QuillBot, collect outputs into a JSONL of {id, chunkIndex, output} then run --assemble`);
} else if (argVal("--assemble")) {
  const chunksPath = argVal("--assemble");
  const responsesPath = argVal("--responses");
  const outPath = argVal("--out") ?? "benchmarks/quillbot/captures/quillbot-fluency.jsonl";
  if (!responsesPath) { console.error("Need --responses <path>"); process.exit(1); }
  const responses = new Map();
  for (const line of fs.readFileSync(responsesPath, "utf8").split("\n").filter(Boolean)) {
    const r = JSON.parse(line);
    const key = `${r.id}#${r.chunkIndex}`;
    responses.set(key, r.output ?? r.text ?? "");
  }
  // group by id
  const byId = new Map();
  for (const line of fs.readFileSync(chunksPath, "utf8").split("\n").filter(Boolean)) {
    const c = JSON.parse(line);
    if (!byId.has(c.id)) byId.set(c.id, []);
    byId.get(c.id).push(c);
  }
  const out = [];
  for (const [id, chunks] of byId) {
    chunks.sort((a,b)=>a.chunkIndex-b.chunkIndex);
    const parts = chunks.map(c => responses.get(`${id}#${c.chunkIndex}`) ?? "");
    const missing = parts.some(p=>!p);
    if (missing) console.warn(`[warn] ${id}: missing chunk response, skipping`);
    out.push(JSON.stringify({ id, output: parts.join(" ").replace(/\s+/g," ").trim() }));
  }
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, out.join("\n")+"\n");
  console.log(`Assembled ${out.length} cases -> ${outPath}`);
} else {
  console.log("Usage: see header comment. Flags: --export-chunks <corpus> | --corpus <path> --out <path> | --assemble <chunks> --responses <path> --out <path>");
}

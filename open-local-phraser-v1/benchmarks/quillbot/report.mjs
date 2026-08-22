#!/usr/bin/env node
/**
 * Pairwise report for the frozen QuillBot held-out corpus.
 *
 * Scores each captures/<engine>.jsonl via benchmarks/eval/metrics.mjs:scoreCase
 * and prints overall + by-category tables. Captures are manual/exports stitched via scripts/quillbot-chunker.mjs.
 *
 * Usage:
 *   node benchmarks/quillbot/report.mjs
 *   node benchmarks/quillbot/report.mjs --corpus benchmarks/quillbot/corpus.frozen.json --captures benchmarks/quillbot/captures
 *   node benchmarks/quillbot/report.mjs --out benchmarks/quillbot/report.json
 *
 * Capture format: JSONL lines {id, output} (extra fields ignored). One file per engine:
 *   pari.jsonl, quillbot-fluency.jsonl, quillbot-standard.jsonl, qwen35-4b.jsonl, ling3-tiny-4bit.jsonl, ...
 */
import fs from "fs";
import path from "path";
import { scoreCase } from "../eval/metrics.mjs";

const ROOT = path.resolve(new URL("../..", import.meta.url).pathname);
const args = process.argv.slice(2);
const argVal = (f) => { const i = args.indexOf(f); return i >= 0 ? args[i+1] : undefined; };

const corpusPath = path.resolve(ROOT, argVal("--corpus") ?? "benchmarks/quillbot/corpus.frozen.json");
const capturesDir = path.resolve(ROOT, argVal("--captures") ?? "benchmarks/quillbot/captures");
const outPath = argVal("--out") ? path.resolve(ROOT, argVal("--out")) : null;

if (!fs.existsSync(corpusPath)) {
  console.error(`Missing corpus: ${corpusPath}`);
  process.exit(1);
}
const corpus = JSON.parse(fs.readFileSync(corpusPath, "utf8")).cases;
const byId = new Map(corpus.map(c => [c.id, c]));

function loadCaptures() {
  if (!fs.existsSync(capturesDir)) return [];
  const files = fs.readdirSync(capturesDir).filter(f => f.endsWith(".jsonl"));
  const engines = [];
  for (const f of files) {
    const p = path.join(capturesDir, f);
    const map = new Map();
    for (const line of fs.readFileSync(p, "utf8").split("\n").filter(Boolean)) {
      try {
        const row = JSON.parse(line);
        const id = row.id?.trim();
        const out = (row.output ?? row.text ?? "").trim();
        if (id) map.set(id, out);
      } catch {}
    }
    engines.push({ name: f.replace(/\.jsonl$/, ""), file: f, path: p, map });
  }
  return engines.sort((a,b)=>a.name.localeCompare(b.name));
}

async function scoreEngine(engine) {
  const results = [];
  for (const cas of corpus) {
    const out = (engine.map.get(cas.id) ?? "").trim();
    if (!out) { results.push({ id: cas.id, category: cas.category, passed: false, empty: true, failedChecks: ["empty-output"], meaningSafe: false, englishQuality: false }); continue; }
    const s = await scoreCase(cas, out);
    s.output = out;
    results.push(s);
  }
  const total = results.length;
  const passed = results.filter(r=>r.passed).length;
  const meaningFail = results.filter(r=>!r.meaningSafe).length;
  const englishFail = results.filter(r=>!r.englishQuality).length;
  const guardFail = results.filter(r=> r.failedChecks?.some(c=>["anchorSafe","negationSafe","noNewErrors","meaningFloor","clauseWellFormed","rolePreserved"].includes(c))).length;
  const empty = results.filter(r=>r.empty).length;
  const byCategory = {};
  for (const r of results) {
    const cat = r.category;
    byCategory[cat] ??= { total: 0, passed: 0, meaningFail: 0, englishFail: 0 };
    byCategory[cat].total++;
    if (r.passed) byCategory[cat].passed++;
    if (!r.meaningSafe) byCategory[cat].meaningFail++;
    if (!r.englishQuality) byCategory[cat].englishFail++;
  }
  return { engine: engine.name, file: engine.file, total, passed, passRate: total? passed/total:0, meaningFail, englishFail, guardFail, empty, byCategory, results };
}

function fmtPct(n,d){ return `${((n/d)*100).toFixed(1)}%`; }

function pairwiseTable(engines, scored) {
  // Pairwise win/tie/loss on `passed` only. With a learned pairwise judge this
  // would be blind preference; the automatic gate is a conservative proxy.
  const names = scored.map(s=>s.engine);
  const passById = new Map(scored.map(s=>[s.engine, new Map(s.results.map(r=>[r.id, r.passed]))]));
  const rows = [];
  for (let i=0;i<names.length;i++) for(let j=i+1;j<names.length;j++) {
    const a = names[i], b = names[j];
    const ma = passById.get(a), mb = passById.get(b);
    let aWin=0,bWin=0,tie=0;
    for (const cas of corpus) {
      const pa = ma.get(cas.id) ?? false, pb = mb.get(cas.id) ?? false;
      if (pa && !pb) aWin++; else if (!pa && pb) bWin++; else tie++;
    }
    rows.push({ pair: `${a} vs ${b}`, aWin, bWin, tie });
  }
  return rows;
}

async function main(){
  const engines = loadCaptures();
  console.log(`\n=== QuillBot held-out report ===`);
  console.log(`corpus: ${path.relative(ROOT, corpusPath)} cases=${corpus.length}`);
  console.log(`captures: ${path.relative(ROOT, capturesDir)} engines=${engines.map(e=>e.name).join(", ") || "(none — see README / quillbot-chunker.mjs)"}`);

  if (engines.length===0) {
    console.log(`\nNo captures found. To populate:\n  1) node benchmarks/eval/run-eval.mjs --corpus benchmarks/quillbot/corpus.frozen.json   # Pari local-safe-engine (no --outputs)\n     # or: python benchmarks/llm-shootout/run_model.py <model_dir> benchmarks/quillbot/captures/qwen35-4b.jsonl --corpus benchmarks/quillbot/corpus.frozen.json\n     #     python benchmarks/llm-shootout/run_openai_compatible.py --model ling-3.0-tiny-4bit --out benchmarks/quillbot/captures/ling3-tiny-4bit.jsonl --corpus benchmarks/quillbot/corpus.frozen.json\n  2) QuillBot (manual, ~600 chars/125 words per paste):\n     node scripts/quillbot-chunker.mjs --corpus benchmarks/quillbot/corpus.frozen.json --out /tmp/quillbot-chunks.jsonl\n     # paste each chunk into QuillBot Fluency/Standard, collect {id, chunkIndex, output} as JSONL, then:\n     node scripts/quillbot-chunker.mjs --assemble /tmp/quillbot-chunks.jsonl --responses /tmp/my-pastes.jsonl --out benchmarks/quillbot/captures/quillbot-fluency.jsonl\n  3) node benchmarks/quillbot/report.mjs\n`);
    if (outPath) fs.writeFileSync(outPath, JSON.stringify({ corpus: path.relative(ROOT, corpusPath), cases: corpus.length, engines: [], note: "no captures" }, null, 2));
    return;
  }

  const scored = [];
  for (const e of engines) {
    const s = await scoreEngine(e);
    scored.push(s);
    console.log(`\n--- ${s.engine} (${s.file}) ---`);
    console.log(`OVERALL  ${s.passed}/${s.total} ${fmtPct(s.passed,s.total)}  meaningFail=${s.meaningFail} englishFail=${s.englishFail} guardFail=${s.guardFail} empty=${s.empty}`);
    const cats = Object.keys(s.byCategory).sort();
    for (const c of cats) {
      const b = s.byCategory[c];
      console.log(`  ${c.padEnd(26)} ${String(b.passed).padStart(3)}/${b.total} ${fmtPct(b.passed,b.total).padStart(6)}  meaningFail=${String(b.meaningFail).padStart(2)} englishFail=${String(b.englishFail).padStart(2)}`);
    }
    // hard-tail summary
    const hardTail = ["broken_grammar","run_on","word_salad","vague"];
    const htTotal = hardTail.reduce((n,c)=> n + (s.byCategory[c]?.total ?? 0), 0);
    const htPass = hardTail.reduce((n,c)=> n + (s.byCategory[c]?.passed ?? 0), 0);
    if (htTotal) console.log(`  hard-tail (broken/vague/run_on/salad) ${htPass}/${htTotal} ${fmtPct(htPass,htTotal)}`);
  }

  if (scored.length >= 2) {
    console.log(`\n--- Pairwise PASS win/tie/loss (automatic gate proxy; blind human preference is the product metric) ---`);
    for (const r of pairwiseTable(engines, scored)) {
      const [a,b] = r.pair.split(" vs ");
      console.log(`${r.pair.padEnd(44)} ${a} win ${String(r.aWin).padStart(3)}  tie ${String(r.tie).padStart(3)}  ${b} win ${String(r.bWin).padStart(3)}`);
    }
  }

  // Invention trap note: automatic judge cannot reliably detect hallucinated
  // specifics (e.g. "soon" -> "by Friday"); report those cases for human review.
  const ambIds = new Set(corpus.filter(c=>c.category==="ambiguity_invention_trap").map(c=>c.id));
  if (ambIds.size) {
    console.log(`\n--- Ambiguity invention trap (${ambIds.size} cases — human-judged: output must not invent specifics like "soon" -> "by Friday") ---`);
    for (const s of scored) {
      const fails = s.results.filter(r=> ambIds.has(r.id) && !r.passed).length;
      console.log(`  ${s.engine}: PASS ${s.results.filter(r=> ambIds.has(r.id) && r.passed).length}/${ambIds.size}  review queue=${fails}`);
    }
  }

  if (outPath) {
    const payload = { generatedAt: new Date().toISOString(), corpus: path.relative(ROOT, corpusPath), cases: corpus.length, engines: scored.map(s=>({ engine:s.engine, file:s.file, total:s.total, passed:s.passed, passRate:s.passRate, meaningFail:s.meaningFail, englishFail:s.englishFail, byCategory:s.byCategory })), pairwise: pairwiseTable(engines, scored) };
    fs.mkdirSync(path.dirname(outPath), { recursive:true });
    fs.writeFileSync(outPath, JSON.stringify(payload, null, 2));
    console.log(`\nsaved -> ${outPath}`);
  }
}

await main();

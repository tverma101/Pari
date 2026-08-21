import fs from "fs";
import path from "path";
import { spawn } from "child_process";

const ROOT_DIR = path.resolve(new URL("..", import.meta.url).pathname);
const MODEL_DIR = path.join(ROOT_DIR, "native-models", "Qwen", "Qwen3.5-4B-MLX-4bit");
const WORKER = path.join(ROOT_DIR, "native-runtime", "paraphrase_worker.py");
const PYTHON = [
  "/opt/homebrew/bin/python3",
  "/usr/local/bin/python3",
  "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3",
  "/usr/bin/python3",
].find((candidate) => fs.existsSync(candidate));

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function sentenceCount(text) {
  return Math.max(1, text.trim().split(/[.!?]+(?:\s|$)/).filter((part) => part.trim()).length);
}

function wordCount(text) {
  return text.match(/[A-Za-z]+(?:[-'][A-Za-z]+)*/g)?.length ?? 0;
}

function runWorker(request) {
  return new Promise((resolve, reject) => {
    if (!PYTHON) {
      reject(new Error("No supported local Python 3 runtime was found."));
      return;
    }

    const child = spawn(PYTHON, [WORKER], { cwd: ROOT_DIR, stdio: ["pipe", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    const timeout = setTimeout(() => {
      child.kill("SIGTERM");
      reject(new Error("Native model QA timed out after 180 seconds."));
    }, 180_000);

    child.stdout.on("data", (chunk) => { stdout += chunk.toString(); });
    child.stderr.on("data", (chunk) => { stderr += chunk.toString(); });
    child.on("error", (error) => {
      clearTimeout(timeout);
      reject(error);
    });
    child.on("close", (code) => {
      clearTimeout(timeout);
      const lines = stdout.trim().split(/\r?\n/).reverse();
      const response = lines.map((line) => {
        try { return JSON.parse(line); } catch { return null; }
      }).find(Boolean);
      if (!response || code !== 0 || response.ok !== true) {
        reject(new Error(response?.error || stderr.trim() || `Native worker exited with code ${code}.`));
        return;
      }
      resolve(response);
    });
    child.stdin.end(JSON.stringify(request));
  });
}

assert(fs.existsSync(path.join(MODEL_DIR, "model.safetensors")), "Bundled native model weights are missing.");
assert(fs.existsSync(WORKER), "Bundled native paraphrase worker is missing.");

const fixtures = [
  {
    name: "personal-flow",
    mode: "personal",
    text: "My ADHD makes it difficult for me to sustain attention for long periods, stay focused when there are distractions, organize tasks and assignments, and remember information or instructions. I can also have difficulty listening continuously during lectures and completing work that requires sustained mental effort. These symptoms can affect my test performance, note-taking, time management, and ability to keep up with longer assignments.",
    protectedSpans: ["can", "can"],
    sameSentenceCount: true,
    styleContext: {
      approvedExamples: [
        {
          originalText: "The editor is useful.",
          finalText: "The editor is helpful.",
        },
      ],
      preferredReplacements: [
        { original: "useful", replacement: "helpful", count: 2 },
      ],
      avoidedPhrases: ["utilize"],
      preferredContractions: ["can't"],
      sentencePreference: "similar",
    },
  },
  {
    name: "warmth-register",
    mode: "warmth",
    text: "The system assists individuals and utilizes a rigid process. The problem is obvious. It cannot help.",
    protectedSpans: [],
    sameSentenceCount: true,
  },
  {
    name: "broken-prose",
    mode: "personal",
    text: "they is ready. writing hard. need help",
    protectedSpans: [],
    sameSentenceCount: false,
  },
  {
    name: "grammar-cascade",
    mode: "personal",
    text: "they is ready. the editor can explains the change. She wrote an useful summary. Between you and I, need help. send update. They could of written a lot more better.",
    protectedSpans: [],
    sameSentenceCount: false,
  },
  {
    name: "quantifier-boundaries",
    mode: "personal",
    text: "A number of students is ready. The number of students are waiting. One of the writers are here. There is two drafts. The system is local, users can keep private drafts.",
    protectedSpans: [],
    sameSentenceCount: false,
  },
  {
    name: "parallel-series",
    mode: "personal",
    text: "The team likes reading, writing, and revise. The editor enjoys reviewing, organizing, and explain.",
    protectedSpans: [],
    sameSentenceCount: true,
  },
  {
    name: "nuclear-meeting-notes",
    mode: "personal",
    text: "meeting tomorrow with the client, who is upset due to the delay. need to explain clearly without blaming. send update before noon",
    protectedSpans: [],
    sameSentenceCount: false,
  },
  {
    name: "nuclear-warmth-notes",
    mode: "warmth",
    text: "Deadline missed. Team performance unacceptable. Fix immediately. No excuses.",
    protectedSpans: [],
    sameSentenceCount: false,
  },
  {
    name: "protected-facts",
    mode: "warmth",
    text: "Dr. Jane Smith emailed support@example.com on 2026-08-10. The total is $42.50. Visit https://example.com.",
    protectedSpans: ["Jane Smith", "support@example.com", "2026-08-10", "$42.50", "https://example.com"],
    sameSentenceCount: true,
  },
  {
    name: "meaning-guardrails",
    mode: "personal",
    text: "Not all users approved the plan. The model may fail. Only students reviewed the draft.",
    protectedSpans: ["Not", "may"],
    sameSentenceCount: true,
  },
  {
    name: "direct-english-filler",
    mode: "personal",
    text: "It is important to note that there are a number of issues due to the fact that the plan changed.",
    protectedSpans: [],
    sameSentenceCount: true,
  },
  {
    name: "bookish-negation",
    mode: "personal",
    text: "It is not the case that the method is useless. There is no indication that the team agrees.",
    protectedSpans: ["not", "no"],
    sameSentenceCount: true,
  },
];

for (const fixture of fixtures) {
  const started = Date.now();
  const response = await runWorker({
    model_path: MODEL_DIR,
    original_text: fixture.text,
    protected_spans: fixture.protectedSpans,
    mode: fixture.mode,
    strength: fixture.mode === "warmth" ? 56 : 60,
    temperature: 0,
    max_tokens: 512,
    ...(fixture.styleContext ? { style_context: fixture.styleContext } : {}),
  });
  const output = String(response.text || "").trim();
  assert(output && output !== fixture.text, `${fixture.name}: model did not rewrite the input.`);
  assert(!/<think>|<analysis>|^\s*(?:rewritten paragraph|paraphrase):/i.test(output), `${fixture.name}: worker leaked control text.`);
  assert(!/\b([A-Za-z]+)\s+\1\b/i.test(output), `${fixture.name}: output repeated an adjacent word: ${output}`);
  assert(/[.!?]$/.test(output), `${fixture.name}: output did not end with sentence punctuation: ${output}`);
  if (fixture.sameSentenceCount) {
    assert(sentenceCount(output) === sentenceCount(fixture.text), `${fixture.name}: sentence count changed unexpectedly.`);
  }
  for (const span of fixture.protectedSpans) {
    assert(output.includes(span), `${fixture.name}: protected span was changed or dropped: ${span}`);
  }
  if (fixture.name === "warmth-register") {
    assert(!/\butili[sz]e(?:s|d)?\b|\bindividuals\b|\bassist(?:s|ed)?\b/i.test(output), `${fixture.name}: robotic register remained: ${output}`);
  }
  if (fixture.name === "broken-prose") {
    assert(!/\bthey\s+is\b/i.test(output), `${fixture.name}: agreement error remained: ${output}`);
  }
  if (fixture.name === "grammar-cascade") {
    assert(!/\bthey\s+is\b|\bcan\s+explains\b|\ban\s+useful\b|\bbetween\s+you\s+and\s+I\b|\bsend\s+update\b|\bcould\s+of\b|\balot\b|\bmore\s+better\b/i.test(output), `${fixture.name}: a grammar cascade remained: ${output}`);
    assert(/\b(?:a useful summary|the useful summary)\b/i.test(output), `${fixture.name}: article repair was not visible: ${output}`);
    assert(/\b(?:an update|the update)\b/i.test(output), `${fixture.name}: note repair was not visible: ${output}`);
    assert(!/,\s+(?:the|a|an)\s+[A-Za-z'-]+\s+(?:is|are|was|were|has|have|does|do)\b/i.test(output), `${fixture.name}: determiner-led comma splice remained: ${output}`);
  }
  if (fixture.name === "quantifier-boundaries") {
    assert(!/\ba number of\s+students\s+is\b|\bthe number of\s+students\s+are\b|\bone of the writers\s+are\b|\bthere is two\b|,\s+users\s+can\b/i.test(output), `${fixture.name}: quantifier or sentence-boundary error remained: ${output}`);
  }
  if (fixture.name === "parallel-series") {
    assert(!/\b(?:likes?|enjoys?|keeps?|starts?|stops?|avoids?|finishes?|continues?|prefers?)\s+[A-Za-z]+ing,\s+[A-Za-z]+ing,\s+and\s+(?:read|write|revise|review|organize|explain)\b/i.test(output), `${fixture.name}: mixed parallel verb series remained: ${output}`);
  }
  if (fixture.name === "nuclear-meeting-notes") {
    assert(!/^Need\s+to\s+/i.test(output), `${fixture.name}: subjectless note fragment remained: ${output}`);
    assert(!/^Send\s+update\b/i.test(output), `${fixture.name}: article-less note fragment remained: ${output}`);
  }
  if (fixture.name === "nuclear-warmth-notes") {
    assert(!/\b(?:fix\s+immediately|no\s+excuses|unacceptable)\b/i.test(output), `${fixture.name}: cold or cynical wording remained: ${output}`);
    assert(!/,\s+and\s+No\b/.test(output), `${fixture.name}: a protected negation was joined to the previous sentence: ${output}`);
    assert(/\b(?:please|next step|as soon as possible|needs attention)|let's focus/i.test(output), `${fixture.name}: warmth was not noticeable: ${output}`);
  }
  if (fixture.name === "meaning-guardrails") {
    assert(/\bNot\b/i.test(output) && /\bmay\b/i.test(output), `${fixture.name}: protected meaning markers changed: ${output}`);
    assert(!/\b(?:all|some)\s+users\s+approved\b/i.test(output) || /\bNot\b/i.test(output), `${fixture.name}: quantifier drifted: ${output}`);
  }
  if (fixture.name === "direct-english-filler") {
    assert(!/\bit is important to note\b|\bthere are a number of\b|\bdue to the fact that\b/i.test(output), `${fixture.name}: academic filler remained: ${output}`);
  }
  if (fixture.name === "bookish-negation") {
    assert(/\bnot\b/i.test(output) && /\bno\b/i.test(output), `${fixture.name}: negative meaning markers changed: ${output}`);
    assert(!/\bit is not the case that\b|\bthere is no indication that\b/i.test(output), `${fixture.name}: bookish negation remained: ${output}`);
  }
  console.log(`[qa:native-model] ${fixture.name} words=${wordCount(output)} sentences=${sentenceCount(output)} ms=${Date.now() - started}`);
}

console.log("[qa:native-model] PASS");

import fs from "fs";
import path from "path";
import vm from "vm";
import { createRequire } from "module";

import ts from "typescript";

const ROOT_DIR = path.resolve(new URL("..", import.meta.url).pathname);
const nodeRequire = createRequire(import.meta.url);
const moduleCache = new Map();

function resolveFile(basePath) {
  const candidates = [
    basePath,
    `${basePath}.ts`,
    `${basePath}.tsx`,
    `${basePath}.js`,
    path.join(basePath, "index.ts"),
    path.join(basePath, "index.tsx"),
  ];

  for (const candidate of candidates) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) {
      return candidate;
    }
  }

  throw new Error(`Cannot resolve ${basePath}`);
}

function resolveModule(specifier, fromFile) {
  if (specifier.startsWith("@/")) {
    return resolveFile(path.join(ROOT_DIR, "src", specifier.slice(2)));
  }

  if (specifier.startsWith(".")) {
    return resolveFile(path.resolve(path.dirname(fromFile), specifier));
  }

  return null;
}

function loadTsModule(filePath) {
  const absolutePath = resolveFile(filePath);
  if (moduleCache.has(absolutePath)) {
    return moduleCache.get(absolutePath).exports;
  }

  const source = fs.readFileSync(absolutePath, "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: {
      esModuleInterop: true,
      jsx: ts.JsxEmit.ReactJSX,
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: absolutePath,
  }).outputText;

  const module = { exports: {} };
  moduleCache.set(absolutePath, module);

  const localRequire = (specifier) => {
    const resolved = resolveModule(specifier, absolutePath);
    return resolved ? loadTsModule(resolved) : nodeRequire(specifier);
  };
  const wrapper = `(function(exports, require, module, __filename, __dirname) {\n${output}\n})`;
  const compiled = vm.runInThisContext(wrapper, { filename: absolutePath });
  compiled(module.exports, localRequire, module, absolutePath, path.dirname(absolutePath));

  return module.exports;
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

const { getSynonymEntry, buildCandidateOptions } = loadTsModule(
  path.join(ROOT_DIR, "src/lib/phraseEngine/synonymBank.ts")
);
const { rewriteText } = loadTsModule(path.join(ROOT_DIR, "src/lib/phraseEngine/rewriteText.ts"));

const targetTerms = [
  "narcissism",
  "high self-esteem",
  "self-esteem",
  "high",
  "because",
  "narcissism includes",
  "entitlement",
  "and",
  "person",
  "themselves",
  "good",
  "different from",
  "different",
  "difficult",
  "superiority",
  "sense of superiority and entitlement",
  "easier to read",
  "work with",
  "better",
  "narcissistic",
  "may",
  "need",
  "similar",
  "view",
  "tool",
  "show",
  "slow",
  "useful",
  "improve",
  "give",
  "problem",
  "quickly",
  "yourself",
  "but",
];

const countRows = targetTerms.map((term) => {
  const entry = getSynonymEntry(term);
  assert(entry, `Missing synonym entry for "${term}"`);
  const options = buildCandidateOptions(term, entry);
  assert(options.length >= 39, `"${term}" has ${options.length} options; expected 39-40`);
  assert(options.length <= 40, `"${term}" has ${options.length} options; expected max 40`);
  return { term, choices: options.length };
});

const rejectedPatterns = [
  { pattern: /\bA being\b/i, reason: "article + replacement noun mismatch" },
  { pattern: /\bA human\b/i, reason: "unnecessary auto-rewrite of person" },
  { pattern: /beneficial about/i, reason: "bad adjective/preposition collocation" },
  { pattern: /consider of/i, reason: "bad verb/preposition collocation" },
  { pattern: /similar (?:as|considering that|seeing that)/i, reason: "awkward causal connector after similar" },
  { pattern: /deservingness\s+(?:along with|and)\s+deservingness/i, reason: "duplicate noun replacement" },
  { pattern: /can need/i, reason: "modal auto-rewrite changed may need unnaturally" },
  { pattern: /along with make/i, reason: "connector before verb phrase became ungrammatical" },
  { pattern: /more capable words/i, reason: "better words became an unnatural collocation" },
  { pattern: /clearer than everyone else/i, reason: "better-than comparison became unnatural" },
  { pattern: /clause easier to examine/i, reason: "readability phrase became unnatural" },
  { pattern: /make a clause/i, reason: "already-natural sentence wording became less natural" },
  { pattern: /as soon as teachers/i, reason: "when became overly specific in education context" },
  { pattern: /useful device/i, reason: "already-natural tool wording changed to device" },
  { pattern: /arduous ideas/i, reason: "difficult ideas became too formal" },
  { pattern: /feels gradual/i, reason: "slow app phrasing became unnatural" },
  { pattern: /demonstrate progress/i, reason: "show progress became too formal" },
  { pattern: /beneficial suggestions/i, reason: "useful suggestions became too formal" },
  { pattern: /can better energy/i, reason: "improve energy became ungrammatical" },
  { pattern: /changes promptly/i, reason: "quickly became response-timing adverb in science context" },
  { pattern: /deliver the customer/i, reason: "give the customer became unnatural" },
  { pattern: /beneficial option/i, reason: "useful option became too formal" },
];

const paragraphSamples = [
  {
    name: "psychology contrast",
    text:
      "Narcissism is different from high self-esteem because narcissism includes entitlement and deservingness. A person with high self-esteem can feel good about themselves without thinking they are better than everyone else. A narcissistic person may need attention, admiration, along with special treatment. They are similar because both involve having a positive view of yourself, but narcissism takes it too far.",
    required: [
      { pattern: /(?:a sense of being owed|entitlement)/i, reason: "entitlement keeps a natural noun phrase" },
      { pattern: /about themselves/i, reason: "reflexive pronoun phrase stays grammatical" },
      { pattern: /A person with/i, reason: "already-natural person phrasing is preserved" },
    ],
  },
  {
    name: "education support",
    text:
      "Students can improve their writing when teachers give clear feedback. A useful tool can help a student find better words, understand difficult ideas, and make a sentence easier to read.",
    required: [
      { pattern: /Students|Pupils|Learners/i, reason: "education subject remains present" },
      { pattern: /writing|wording|prose|draft/i, reason: "writing topic remains present" },
    ],
  },
  {
    name: "workplace productivity",
    text:
      "A company may use simple local software to make work more efficient. People in busy workplaces need fast suggestions, but the tool should still keep the original meaning clear.",
    required: [
      { pattern: /company|business|firm|organization/i, reason: "business subject remains present" },
      { pattern: /meaning|idea|sense/i, reason: "meaning-preservation topic remains present" },
    ],
  },
  {
    name: "local privacy",
    text:
      "Local writing tools are important because private drafts should stay on the device. Fast offline models can suggest better phrasing without sending personal text to a remote server.",
    required: [
      { pattern: /local|on-device|offline|device/i, reason: "local-first topic remains present" },
      { pattern: /private|personal|remote|server/i, reason: "privacy topic remains present" },
    ],
  },
  {
    name: "technical troubleshooting",
    text:
      "When a local app feels slow, the interface should show progress clearly and avoid blocking the user. Background indexing can prepare useful suggestions while the person continues editing.",
    required: [
      { pattern: /slow|sluggish|delayed|unresponsive|progress/i, reason: "performance topic remains present" },
      { pattern: /background|indexing|suggestions|editing/i, reason: "background suggestion flow remains present" },
    ],
  },
  {
    name: "health wellness",
    text:
      "A person with strong habits may feel better when they sleep well, eat balanced meals, and take short walks. Small changes can improve energy without making the advice sound extreme.",
    required: [
      { pattern: /habits|sleep|meals|walks|energy/i, reason: "health routine topic remains present" },
      { pattern: /advice|guidance|recommendation|extreme/i, reason: "advice-strength topic remains present" },
    ],
  },
  {
    name: "science explanation",
    text:
      "Water temperature changes quickly because heat moves from warmer areas to cooler areas. A simple explanation can help readers understand the idea without losing the scientific meaning.",
    required: [
      { pattern: /water|temperature|heat|warmer|cooler/i, reason: "science topic remains present" },
      { pattern: /meaning|idea|explanation|understand/i, reason: "explanation topic remains present" },
    ],
  },
  {
    name: "customer support",
    text:
      "A clear response should acknowledge the problem, explain the next step, and give the customer a useful option. The message needs to sound calm, direct, and respectful.",
    required: [
      { pattern: /response|message|customer|problem/i, reason: "support topic remains present" },
      { pattern: /calm|direct|respectful|clear/i, reason: "tone topic remains present" },
    ],
  },
];

const rewrites = paragraphSamples.map((sample) => {
  const rewrite = rewriteText(sample.text, {
    freezeWords: "",
    mode: "standard",
    strength: 56,
  });
  const output = rewrite.outputText;

  assert(output.trim().length > 0, `${sample.name}: empty output`);
  assert(!/\b(undefined|null|NaN)\b/i.test(output), `${sample.name}: leaked invalid value: ${output}`);
  assert(!/\s{3,}/.test(output), `${sample.name}: excessive whitespace: ${output}`);
  assert(/[.!?]$/.test(output.trim()), `${sample.name}: output lost ending punctuation: ${output}`);
  assert(
    rewrite.tokens.some((token) => token.alternatives.length > 0),
    `${sample.name}: no swappable tokens found`
  );

  for (const { pattern, reason } of rejectedPatterns) {
    assert(!pattern.test(output), `${sample.name}: rejected phrase found (${reason}): ${output}`);
  }

  for (const { pattern, reason } of sample.required) {
    assert(pattern.test(output), `${sample.name}: required signal missing (${reason}): ${output}`);
  }

  return { name: sample.name, output, changed: rewrite.changedCount, swappable: rewrite.candidateCount };
});

const psychologyOutput = rewrites.find((entry) => entry.name === "psychology contrast")?.output ?? "";
assert(
  psychologyOutput.includes("a sense of being owed") || psychologyOutput.includes("entitlement"),
  `Entitlement rewrite lost the natural article: ${psychologyOutput}`
);
assert(
  psychologyOutput.includes("about themselves"),
  `Reflexive pronoun phrase changed unnaturally: ${psychologyOutput}`
);
assert(
  psychologyOutput.includes("A person with"),
  `Person should remain natural in the first sentence: ${psychologyOutput}`
);

let totalChanged = 0;
for (const rewrite of rewrites) {
  totalChanged += rewrite.changed;
}

assert(totalChanged > 0, "No sample paragraph changed during paraphrase QA");

console.log("[qa:paraphrase] synonym counts");
for (const row of countRows) {
  console.log(`[qa:paraphrase] ${row.term}: ${row.choices}`);
}
console.log("[qa:paraphrase] paragraph samples");
for (const rewrite of rewrites) {
  console.log(
    `[qa:paraphrase] ${rewrite.name}: changed=${rewrite.changed}, swappable=${rewrite.swappable}, output=${rewrite.output}`
  );
}
console.log("[qa:paraphrase] PASS");

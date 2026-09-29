import fs from "fs";
import path from "path";
import vm from "vm";
import { createRequire } from "module";

import ts from "typescript";

const ROOT_DIR = path.resolve(new URL("..", import.meta.url).pathname);
const nodeRequire = createRequire(import.meta.url);
const moduleCache = new Map();

function resolveFile(basePath) {
  const candidates = [basePath, `${basePath}.ts`, `${basePath}.tsx`, `${basePath}.js`, `${basePath}.json`];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
  }
  throw new Error(`Cannot resolve ${basePath}`);
}

function resolveModule(specifier, fromFile) {
  if (specifier.startsWith("@/")) return resolveFile(path.join(ROOT_DIR, "src", specifier.slice(2)));
  if (specifier.startsWith(".")) return resolveFile(path.resolve(path.dirname(fromFile), specifier));
  return null;
}

function loadTsModule(filePath) {
  const absolutePath = resolveFile(filePath);
  if (moduleCache.has(absolutePath)) return moduleCache.get(absolutePath).exports;

  if (absolutePath.endsWith(".json")) {
    const module = { exports: JSON.parse(fs.readFileSync(absolutePath, "utf8")) };
    moduleCache.set(absolutePath, module);
    return module.exports;
  }

  const source = fs.readFileSync(absolutePath, "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: {
      esModuleInterop: true,
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: absolutePath,
  }).outputText;
  const module = { exports: {} };
  moduleCache.set(absolutePath, module);
  const localRequire = (specifier) => {
    if (
      absolutePath.endsWith("/rewriteStack/advancedParaphrase.ts") &&
      specifier === "./modelManager"
    ) {
      return {
        generateMaskSuggestions: async () => [],
        warmRewriteAssistantModels: async () => {},
      };
    }
    if (
      absolutePath.endsWith("/ranking/embeddingRanker.ts") &&
      specifier === "./modelManager"
    ) {
      return {
        getEmbeddingExtractor: async () => {
          throw new Error("embedding models are intentionally stubbed by qa:approval");
        },
      };
    }
    const resolved = resolveModule(specifier, absolutePath);
    return resolved ? loadTsModule(resolved) : nodeRequire(specifier);
  };
  const wrapper = `(function(exports, require, module, __filename, __dirname) {\n${output}\n})`;
  const compiled = vm.runInThisContext(wrapper, { filename: absolutePath });
  compiled(module.exports, localRequire, module, absolutePath, path.dirname(absolutePath));
  return module.exports;
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const { buildCandidateOptions, getSynonymEntry } = loadTsModule(path.join(ROOT_DIR, "src/lib/phraseEngine/synonymBank.ts"));
const { rewriteText } = loadTsModule(path.join(ROOT_DIR, "src/lib/phraseEngine/rewriteText.ts"));
const {
  extractProtectedSpans,
  validateProtectedContent,
} = loadTsModule(path.join(ROOT_DIR, "src/lib/safety/protectedContent.ts"));
const {
  createEmptyPreferenceMemory,
  learnFromApproval,
  rankCandidatesByMemory,
  retrieveRelevantExamples,
} = loadTsModule(path.join(ROOT_DIR, "src/lib/personalization/approvalMemory.ts"));
const {
  appendGroupedEdit,
  describeTextEdit,
} = loadTsModule(path.join(ROOT_DIR, "src/lib/personalization/editHistory.ts"));
const { buildNativeStyleContext, finalizeDraft, generateLocalParaphrase, repairQuantityScope, restructureHighStrength } = loadTsModule(path.join(ROOT_DIR, "src/lib/generation/localParaphrase.ts"));
const {
  hasStandaloneNoteFragment,
  looksLikeModelControlEcho,
  looksLikeUnrepairedFragmentaryProse,
  repairBrokenProse,
} = loadTsModule(path.join(ROOT_DIR, "src/lib/generation/brokenProseRepair.ts"));
const {
  generateAdvancedAlternatives,
  MAX_VISIBLE_SYNONYMS,
} = loadTsModule(path.join(ROOT_DIR, "src/lib/rewriteStack/advancedParaphrase.ts"));
const { repairContextualNaturalness, validateRewriteQuality } = loadTsModule(path.join(ROOT_DIR, "src/lib/generation/rewriteQuality.ts"));
const { analyzeGrammar, grammarSafetyIssues } = loadTsModule(path.join(ROOT_DIR, "src/lib/nlp/grammar.ts"));
const { analyzeSentenceFlow, repairSentenceFlow } = loadTsModule(path.join(ROOT_DIR, "src/lib/generation/sentenceFlow.ts"));
const { repairDirectEnglish } = loadTsModule(path.join(ROOT_DIR, "src/lib/generation/directEnglishRepair.ts"));
const { repairEnglishGrammar } = loadTsModule(path.join(ROOT_DIR, "src/lib/generation/englishGrammarRepair.ts"));
const { meaningContractIssues } = loadTsModule(path.join(ROOT_DIR, "src/lib/generation/meaningContract.ts"));
const { loadSettings, normalizeStoredRewriteMode } = loadTsModule(path.join(ROOT_DIR, "src/lib/settings/settingsStore.ts"));
const {
  maximumAutomaticRewrites,
  minimumAutomaticRewrites,
  percentToStrengthLevel,
  strengthBand,
  strengthLabel,
} = loadTsModule(path.join(ROOT_DIR, "src/lib/phraseEngine/rules.ts"));
const { needsStructuralRepair } = loadTsModule(path.join(ROOT_DIR, "src/lib/generation/rewriteQuality.ts"));
const { countSentences, splitSentences } = loadTsModule(path.join(ROOT_DIR, "src/lib/nlp/sentenceSplit.ts"));
const { normalizeCustomStyle, customModeForStyle, effectiveStyleStrength, engineModeForStyle } = loadTsModule(path.join(ROOT_DIR, "src/lib/styles/customStyles.ts"));

const grammarProbes = [
  { text: "They is ready to revise the draft.", id: "subject-verb-agreement" },
  { text: "The editor can explains the change clearly.", id: "modal-verb-agreement" },
  { text: "She wrote an useful summary.", id: "article-mismatch" },
  { text: "Between you and I, the sentence needs work.", id: "pronoun-case" },
  { text: "The writer reviewed the the paragraph.", id: "repeated-word" },
  { text: "I has a draft, and the editor can explaining the change.", id: "subject-verb-agreement" },
  { text: "Between you and he, the decision is private.", id: "pronoun-case" },
  { text: "They could of written a lot more better.", id: "common-grammar-pattern" },
];
for (const probe of grammarProbes) {
  assert(grammarSafetyIssues(probe.text).some((issue) => issue.id === probe.id), `Grammar safety probe missed ${probe.id}`);
  assert(analyzeGrammar(probe.text).some((issue) => issue.id === probe.id), `Grammar diagnostic probe missed ${probe.id}`);
}
assert(validateRewriteQuality("They are ready to revise the draft.", "They is ready to revise the draft.").safe === false, "Quality gate accepted subject-verb disagreement");
assert(validateRewriteQuality("The editor can explain the change clearly.", "The editor can explains the change clearly.").safe === false, "Quality gate accepted a modal verb error");
assert(grammarSafetyIssues("The editor can explaining the change.").some((issue) => issue.id === "modal-verb-agreement"), "Grammar safety probe missed an -ing modal error");
assert(!grammarSafetyIssues("I was frustrated when the deadline changed.").some((issue) => issue.id === "subject-verb-agreement"), "Grammar validator falsely flagged correct first-person past tense");
assert(/You are ready\. You were waiting\./i.test(repairEnglishGrammar("You is ready. You was waiting.")), "Second-person agreement repair failed");

const grammarRepairProbe = repairEnglishGrammar(
  "they is ready. the editor can explains the change. She wrote an useful summary. Between you and I, need help. send update."
);
assert(/They are ready\. The editor can explain the change\. She wrote a useful summary/i.test(grammarRepairProbe), `Agreement/modal/article repair failed: ${grammarRepairProbe}`);
assert(/Between you and me, I need help\. Send an update\./i.test(grammarRepairProbe), `Pronoun/note-fragment repair failed: ${grammarRepairProbe}`);
assert(/They could have written a lot better\./i.test(repairEnglishGrammar("They could of written a lot more better.")), "Common grammar repair failed");
const thereRepairProbe = repairEnglishGrammar("There is several issues. There are a problem.");
assert(/There are several issues\. There is a problem\./i.test(thereRepairProbe), `There-agreement repair failed: ${thereRepairProbe}`);
const broadAgreementProbe = repairEnglishGrammar("The symptoms is serious. The results has changed. The analysis is complete.");
assert(/The symptoms are serious\. The results have changed\. The analysis is complete\./i.test(broadAgreementProbe), `Broad plural agreement repair failed: ${broadAgreementProbe}`);
assert(!validateRewriteQuality("The symptoms are serious.", "The symptoms is serious.").safe, "Quality gate accepted arbitrary plural-noun agreement drift");
const quantifierRepairProbe = repairEnglishGrammar(
  "A number of students is ready. The number of students are waiting. One of the writers are here. There is two drafts."
);
assert(
  /A number of students are ready\. The number of students is waiting\. One of the writers is here\. There are two drafts\./i.test(quantifierRepairProbe),
  `Quantifier agreement repair failed: ${quantifierRepairProbe}`,
);
const boundaryRepairProbe = repairEnglishGrammar(
  "The system is local, users can keep private drafts. Because the tool is local users can review them."
);
assert(
  /The system is local; users can keep private drafts\. Because the tool is local, users can review them\./i.test(boundaryRepairProbe),
  `Sentence-boundary repair failed: ${boundaryRepairProbe}`,
);
const determinerBoundaryProbe = repairEnglishGrammar(
  "The project was not finished, the reasons are unclear, the team says they are waiting."
);
assert(
  /The project was not finished; the reasons are unclear; the team says they are waiting\./i.test(determinerBoundaryProbe),
  `Determiner-led comma-splice repair failed: ${determinerBoundaryProbe}`,
);
for (const probe of [
  "A number of students is ready.",
  "The number of students are waiting.",
  "One of the writers are here.",
  "There is two drafts.",
  "The system is local, users can keep private drafts.",
  "The project was not finished, the reasons are unclear.",
]) {
  assert(grammarSafetyIssues(probe).some((issue) => ["quantifier-agreement", "comma-splice"].includes(issue.id)), `Grammar validator missed quantifier/boundary issue: ${probe}`);
}
assert(
  !validateRewriteQuality("A number of students are ready.", "A number of students is ready.").safe,
  "Quality gate accepted quantifier agreement drift",
);
assert(
  !validateRewriteQuality("The system is local; users can keep private drafts.", "The system is local, users can keep private drafts.").safe,
  "Quality gate accepted a comma splice",
);
assert(
  !validateRewriteQuality("The project was not finished; the reasons are unclear.", "The project was not finished, the reasons are unclear.").safe,
  "Quality gate accepted a determiner-led comma splice",
);
assert(
  !validateRewriteQuality("They is ready.", "They are ready and the symptoms is serious.", [], { allowStructuralRepair: true }).safe,
  "Quality gate accepted an additional agreement issue of an existing class",
);
const citationRepairProbe = repairEnglishGrammar("Granot et al. (2018) argue that video evidence still requires interpretation.");
assert(citationRepairProbe === "Granot et al. (2018) argue that video evidence still requires interpretation.", "Citation punctuation was changed by grammar repair");
const protectedGrammarProbe = repairEnglishGrammar(
  "A user emailed support@example.com. They is ready.",
  extractProtectedSpans("A user emailed support@example.com. They is ready.")
);
assert(protectedGrammarProbe.includes("support@example.com"), "Grammar repair changed a protected email");

const bundledLexicon = JSON.parse(fs.readFileSync(path.join(ROOT_DIR, "src/lib/rewriteStack/wordnetLexicon.json"), "utf8"));
assert(bundledLexicon.entries?.medicine?.noun?.includes("medication"), "Generated WordNet lexicon is missing medicine alternatives");
assert(bundledLexicon.entries?.opportunity?.noun?.includes("chance"), "Generated WordNet lexicon is missing opportunity alternatives");
assert((bundledLexicon.entries?.world?.thesaurus?.length ?? 0) >= 40, "Bundled thesaurus index is missing the world discovery list");

for (const legacyMode of ["standard", "fluency", "warm", "formal", "simple", "creative", "expand", "shorten", "personal"]) {
  assert(normalizeStoredRewriteMode(legacyMode) === "personal", `Legacy mode ${legacyMode} did not migrate to Personal`);
}
assert(normalizeStoredRewriteMode("warmth") === "warmth", "Warmth mode did not remain selectable");
const customStyleProbe = normalizeCustomStyle({
  id: "qa-custom-mode",
  name: "QA Warm Direct",
  description: "A warmer custom mode",
  instructions: "Use plain, direct, considerate English.",
  baseMode: "personal",
  strength: 64,
  tweaks: { strengthOffset: 8, warmthPolish: true, preserveSentenceCount: true },
  createdAt: "2026-08-11T00:00:00Z",
  updatedAt: "2026-08-11T00:00:00Z",
});
assert(customStyleProbe, "Custom style schema rejected a valid agent profile");
assert(customModeForStyle(customStyleProbe) === "custom:qa-custom-mode", "Custom mode id was not stable");
assert(engineModeForStyle(customStyleProbe) === "warmth", "Custom warmth polish did not resolve through the shared Warmth engine");
assert(effectiveStyleStrength(customStyleProbe, 56) === 72, "Custom strength offset was not bounded/applied");
const previousWindow = globalThis.window;
globalThis.window = {
  localStorage: {
    getItem: () => JSON.stringify({ theme: "dark", mode: "warm", strength: 82 }),
  },
};
const migratedSettings = loadSettings();
globalThis.window = previousWindow;
assert(migratedSettings.mode === "personal", "Stored mode did not migrate to Personal");
assert(migratedSettings.strength === 82, "Stored Rewrite amount was not preserved during mode migration");

assert(needsStructuralRepair("they is ready. writing hard. need help"), "Broken prose was not recognized as structural repair input");
assert(hasStandaloneNoteFragment("Because of the deadline situation."), "Standalone causal fragment was not recognized");
assert(needsStructuralRepair("Because of the deadline situation."), "Standalone causal fragment was not marked for structural repair");
const causalFragmentProbe = repairBrokenProse(
  "Because of the deadline situation.",
  "Because of the deadline situation.",
  extractProtectedSpans("Because of the deadline situation."),
);
assert(/^The cause was the deadline situation\.$/i.test(causalFragmentProbe), `Standalone causal fragment was not completed safely: ${causalFragmentProbe}`);
const waitingFragmentProbe = repairBrokenProse(
  "Still waiting on the client.",
  "Still waiting on the client.",
  extractProtectedSpans("Still waiting on the client."),
);
assert(/^I am still waiting on the client\.$/i.test(waitingFragmentProbe), `Standalone waiting fragment was not completed safely: ${waitingFragmentProbe}`);
const honestFragmentProbe = repairBrokenProse(
  "Honestly? Best pizza in town. No contest.",
  "Honestly? Best pizza in town. No contest.",
  extractProtectedSpans("Honestly? Best pizza in town. No contest."),
);
assert(
  /Honestly, this is the best pizza in town, and there is no contest\./i.test(honestFragmentProbe) ||
    /Honestly, this is the best pizza in town\. (?:There is )?No contest\./i.test(honestFragmentProbe),
  `Standalone evaluative fragments were not completed safely: ${honestFragmentProbe}`,
);
const missingFileProbe = repairBrokenProse(
  "No idea where the file went. Probably the shared drive. Maybe.",
  "No idea where the file went. Probably the shared drive. Maybe.",
  extractProtectedSpans("No idea where the file went. Probably the shared drive. Maybe."),
);
assert(
  /I have no idea where the file went; it probably went to the shared drive, maybe\./i.test(missingFileProbe),
  `Missing-file fragments were not completed safely: ${missingFileProbe}`,
);
const pendingStatusProbe = repairBrokenProse(
  "The quarterly implementation review is pending completion status.",
  "The quarterly implementation review is pending completion status.",
  extractProtectedSpans("The quarterly implementation review is pending completion status."),
);
assert(
  /^The completion status of the quarterly implementation review is pending\.$/i.test(pendingStatusProbe),
  `Dense pending-status wording was not normalized safely: ${pendingStatusProbe}`,
);
assert(looksLikeUnrepairedFragmentaryProse("Because of the deadline situation."), "Unrepaired causal fragment was not detected");
assert(
  looksLikeModelControlEcho("The text needs to be corrected. The rewritten paragraph should preserve every fact."),
  "Native control-text echo was not recognized"
);

const directEnglishProbe = repairDirectEnglish(
  "It is important to note that there are a number of issues due to the fact that the plan changed.",
);
assert(!/\bit is important to note\b|\bthere are a number of\b|\bdue to the fact that\b/i.test(directEnglishProbe), `Direct-English filler repair was incomplete: ${directEnglishProbe}`);
const vagueReasonProbe = repairDirectEnglish("The whole thing fell apart because of reasons.");
assert(/fell apart for unspecified reasons\./i.test(vagueReasonProbe), `Vague reason repair was incomplete: ${vagueReasonProbe}`);
const vagueReasonSentenceProbe = finalizeDraft(
  "So basically, the whole thing fell apart because of reasons.",
  "so basically the whole thing fell apart because reasons",
  extractProtectedSpans("so basically the whole thing fell apart because reasons"),
  "personal",
);
assert(/whole thing fell apart for unspecified reasons/i.test(vagueReasonSentenceProbe), `Vague reason finalization dropped the main clause: ${vagueReasonSentenceProbe}`);
const gerundInfinitiveProbe = repairDirectEnglish("The team met for the purpose of making and reviewing the plan.");
assert(/to make and reviewing the plan\./i.test(gerundInfinitiveProbe), `Gerund-to-infinitive repair produced a broken verb: ${gerundInfinitiveProbe}`);
assert(!/\bto\s+mak\b/i.test(gerundInfinitiveProbe), `Gerund-to-infinitive repair left a truncated verb: ${gerundInfinitiveProbe}`);
const bookishNegationProbe = repairDirectEnglish("It is not the case that the method is useless.", extractProtectedSpans("It is not the case that the method is useless."));
assert(/The method is not useless\./i.test(bookishNegationProbe), `Bookish negation was not made direct: ${bookishNegationProbe}`);
const vagueNegationProbe = repairDirectEnglish("There is no indication that the method is useless.", extractProtectedSpans("There is no indication that the method is useless."));
assert(vagueNegationProbe === "There is no indication that the method is useless.", `Vague negation was changed despite uncertain semantics: ${vagueNegationProbe}`);
const nominalizationProbe = repairDirectEnglish(
  "The reason is not because the process was lacking in effectiveness. There is a need for us to make improvements.",
);
assert(/The process's lack of effectiveness is not the reason\. We need to improve\./i.test(nominalizationProbe), `Nominalized reason/need repair was incomplete: ${nominalizationProbe}`);
const noteStreamProbe = repairBrokenProse(
  "meeting tomorrow client upset delay need explain no blame and keep message short",
  "meeting tomorrow client upset delay need explain no blame and keep message short",
  extractProtectedSpans("meeting tomorrow client upset delay need explain no blame and keep message short"),
);
assert(/(?:Tomorrow's meeting|The meeting tomorrow) is with a client who is upset about the delay\./i.test(noteStreamProbe), `Meeting note planner missed the subject/state frame: ${noteStreamProbe}`);
assert(/I need to explain the delay, with no blame, and keep the message short\./i.test(noteStreamProbe), `Meeting note planner produced broken action flow: ${noteStreamProbe}`);
const meaningDrift = meaningContractIssues(
  "Not all users approved the plan. The model may fail. Only students reviewed the draft.",
  "All users approved the plan. The model will fail. Some students reviewed the draft.",
  "personal",
);
for (const id of ["negation-drift", "modality-drift", "quantity-drift"]) {
  assert(meaningDrift.some((issue) => issue.id === id), `Meaning contract missed ${id}`);
}

const naturalQuantifierParaphrase = meaningContractIssues(
  "Most people avoid boredom. Some situations encourage reflection.",
  "Most people avoid boredom. Certain contexts encourage reflection.",
  "personal",
);
assert(
  !naturalQuantifierParaphrase.some((issue) => issue.id === "quantity-drift"),
  "Meaning contract rejected a natural some/certain quantifier paraphrase",
);
const majorityQuantifierParaphrase = meaningContractIssues(
  "Most people avoid boredom.",
  "The majority of people avoid boredom.",
  "personal",
);
assert(
  !majorityQuantifierParaphrase.some((issue) => issue.id === "quantity-drift"),
  "Meaning contract rejected an explicit majority equivalent for most",
);
const weakenedMajorityParaphrase = meaningContractIssues(
  "Most people avoid boredom.",
  "Many people avoid boredom.",
  "personal",
);
assert(
  weakenedMajorityParaphrase.some((issue) => issue.id === "quantity-drift"),
  "Meaning contract accepted most-to-many quantity weakening",
);
const realQuantifierDrift = meaningContractIssues(
  "Most people avoid boredom. Some situations encourage reflection.",
  "Few people avoid boredom. Certain contexts encourage reflection.",
  "personal",
);
assert(realQuantifierDrift.some((issue) => issue.id === "quantity-drift"), "Meaning contract accepted a real quantifier-strength drift");
const screenshotParagraph = "Boredom is usually seen as something negative. Most people try to avoid it by watching videos, scrolling through social media, playing games, or finding something else to do. However, boredom is not always a bad thing. In some situations, being bored can help people think more creatively, understand themselves better, and take a break from constant stimulation.";
const screenshotNativeCandidate = "Boredom is usually viewed as a negative experience. To combat it, most people turn to activities like watching videos, scrolling through social media, playing games, or engaging in other distractions. However, boredom is not always negative. In certain contexts, it can foster creative thinking, help people understand themselves better, and provide a respite from ongoing stimulation.";
const screenshotQuality = validateRewriteQuality(screenshotParagraph, screenshotNativeCandidate);
assert(screenshotQuality.safe, `Screenshot-quality native candidate was rejected: ${screenshotQuality.issues.map((issue) => issue.id).join(", ")}`);
assert(!/\breceive\s+a\s+break\b/i.test(screenshotNativeCandidate), "Screenshot-quality regression kept the weak receive-a-break wording");

const targetTerms = ["narcissism", "because", "person", "different", "useful", "may", "show", "better"];
for (const term of targetTerms) {
  const entry = getSynonymEntry(term);
  assert(entry, `Missing synonym entry for ${term}`);
  const options = buildCandidateOptions(term, entry);
  assert(options.length >= 6, `${term} exposes only ${options.length} choices`);
  assert(options.length <= 40, `${term} exposes ${options.length} choices; expected at most 40`);
}

const choosingOptions = buildCandidateOptions("choosing", getSynonymEntry("choosing"));
assert(choosingOptions.length >= 35, `choosing exposes only ${choosingOptions.length} contextual choices`);
assert(choosingOptions.some((option) => option.replacement.toLowerCase() === "selecting"), "choosing is missing the natural selecting alternative");
assert(choosingOptions.some((option) => option.replacement.toLowerCase() === "deciding"), "choosing is missing the natural deciding alternative");
assert(!choosingOptions.some((option) => /\b(?:favor|offer|suffer|cover)rring\b/i.test(option.replacement)), "choosing suggestions contain malformed -rring inflection");
const opportunitiesOptions = buildCandidateOptions("opportunities", getSynonymEntry("opportunities"));
assert(opportunitiesOptions.length >= 6, `opportunities exposes only ${opportunitiesOptions.length} contextual choices`);
assert(opportunitiesOptions.some((option) => /^(?:chances|possibilities|openings)$/i.test(option.replacement)), "opportunities is missing a natural noun alternative");
assert(!opportunitiesOptions.some((option) => /\b(?:opportunitiess|possibilitys|openingss|chancess|ways forwards|room to grows)\b/i.test(option.replacement)), "opportunities suggestions contain malformed plural inflection");
const choosingResult = rewriteText(
  "While choosing classes, I called my family in India.",
  { mode: "personal", strength: 100, freezeWords: "", disableAutomaticRewrites: false },
  {}
);
const choosingToken = choosingResult.tokens.find((entry) => entry.originalText.toLowerCase() === "choosing");
assert(choosingToken?.text.toLowerCase() === "choosing", "Automatic paragraph rewriting changed choosing unexpectedly");
assert((choosingToken?.alternatives.length ?? 0) >= 35, "Automatic path did not preserve the broad manual choosing suggestions");

const appSource = fs.readFileSync(path.join(ROOT_DIR, "src/App.tsx"), "utf8");
assert(!appSource.includes("Rewrite sentence"), "Inline chooser still exposes the duplicate sentence rewrite action");

const contextualProbeText = "The world of healthcare gives students an opportunity to connect their skills with an editor through a workflow on a server and a wider idea.";
const contextualProbe = rewriteText(
  contextualProbeText,
  { mode: "personal", strength: 56, freezeWords: "", disableAutomaticRewrites: true },
  {}
);
const contextualChoiceCounts = [];
for (const term of ["world", "healthcare", "students", "opportunity", "connect", "skills", "editor", "workflow", "server", "wider"]) {
  const token = contextualProbe.tokens.find((entry) => entry.originalText.toLowerCase() === term);
  assert(token, `Contextual probe did not tokenize ${term}`);
  const alternatives = await generateAdvancedAlternatives(token, contextualProbeText, "personal", "balanced");
  const uniqueAlternatives = new Set(alternatives.map((option) => option.replacement.toLowerCase()));
  assert(uniqueAlternatives.size >= 40, `${term} exposes only ${uniqueAlternatives.size} local contextual choices`);
  assert(!alternatives.some((option) => /\b([A-Za-z]+)\s+\1\b/i.test(option.replacement)), `${term} suggestions contain a repeated word`);
  contextualChoiceCounts.push(`${term}=${uniqueAlternatives.size}`);
}
const worldAlternatives = await generateAdvancedAlternatives(
  contextualProbe.tokens.find((entry) => entry.originalText.toLowerCase() === "world"),
  contextualProbeText,
  "personal",
  "balanced"
);
assert(worldAlternatives.some((option) => option.replacement.toLowerCase() === "cosmos"), "World suggestions lost a precise WordNet synonym");
assert(MAX_VISIBLE_SYNONYMS === 64, `Manual synonym palette cap regressed to ${MAX_VISIBLE_SYNONYMS}`);
assert(worldAlternatives.length > 40, `Advanced local suggestions exposed only ${worldAlternatives.length} options for world`);

const usedOptions = buildCandidateOptions("used", getSynonymEntry("used"));
assert(usedOptions.length >= 10, `used exposes only ${usedOptions.length} contextual choices`);
assert(usedOptions.some((option) => option.replacement.toLowerCase() === "made use of"), "Personal mode is missing a phrase-level used replacement");
const expandedUsed = rewriteText(
  "The team used several communication skills.",
  { mode: "personal", strength: 100, freezeWords: "", disableAutomaticRewrites: false },
  {}
);
assert(expandedUsed.tokens.some((token) => token.originalText.toLowerCase() === "used" && token.alternatives.some((option) => /made use of|put to use|put into practice|made practical use of/i.test(option.replacement))), "Personal mode did not expose phrase expansions for used");
const ordinaryWords = rewriteText(
  "Students connect with communication skills.",
  { mode: "personal", strength: 56, freezeWords: "", disableAutomaticRewrites: true },
  {}
);
for (const term of ["communication", "skills", "students", "connect"]) {
  assert(
    ordinaryWords.tokens.some((token) => token.originalText.toLowerCase() === term && token.alternatives.length >= 4),
    `Normal word ${term} did not expose inline alternatives`
  );
}
const broaderOrdinaryWords = rewriteText(
  "The editor helps writers review models in a workflow on a server.",
  { mode: "personal", strength: 56, freezeWords: "", disableAutomaticRewrites: true },
  {}
);
for (const term of ["editor", "writers", "models", "workflow", "server"]) {
  assert(
    broaderOrdinaryWords.tokens.some((token) => token.originalText.toLowerCase() === term && token.alternatives.length >= 4),
    `Broader ordinary word ${term} did not expose inline alternatives`
  );
}
const personalResult = rewriteText(
  "The tool helps people review their writing.",
  { mode: "personal", strength: 100, freezeWords: "", disableAutomaticRewrites: false },
  {}
);
assert(personalResult.tokens.some((token) => token.alternatives.length >= 4), "Personal mode did not expose human-centered alternatives");
assert(personalResult.outputText !== "The tool helps people review their writing.", "Personal mode did not produce a rewrite");
const warmthResult = rewriteText(
  "The system assists individuals and utilizes a rigid process.",
  { mode: "warmth", strength: 100, freezeWords: "", disableAutomaticRewrites: false },
  {}
);
assert(warmthResult.outputText !== "The system assists individuals and utilizes a rigid process.", "Warmth mode did not produce a rewrite");
const customModeResult = await generateLocalParaphrase({
  originalText: "The system assists individuals and utilizes a rigid process.",
  examples: [],
  memory: createEmptyPreferenceMemory(),
  mode: engineModeForStyle(customStyleProbe),
  strength: effectiveStyleStrength(customStyleProbe, 56),
  style: customStyleProbe,
});
assert(customModeResult.safe, `Custom mode failed the shared safety gates: ${customModeResult.notice ?? customModeResult.text}`);
assert(customModeResult.text !== "The system assists individuals and utilizes a rigid process.", "Custom mode did not produce a rewrite through the shared engine");

const brokenResult = await generateLocalParaphrase({
  originalText: "they is ready. writing hard. need help",
  examples: [],
  memory: createEmptyPreferenceMemory(),
  mode: "personal",
  strength: 56,
});
assert(brokenResult.text !== "they is ready. writing hard. need help", "Broken prose stayed unchanged");
assert(!/\bthey\s+is\b/i.test(brokenResult.text), `Broken prose kept subject-verb disagreement: ${brokenResult.text}`);
assert(/[.!?]$/.test(brokenResult.text), "Broken prose repair did not finish with punctuation");

const finalizerRegressionCases = [
  {
    id: "meridiem",
    original: "The system peak occurred at 3am and lead to alot of failed requests.",
    candidate: "The system peak occurred at 3 a.m. and led to a lot of failed requests.",
    expected: /3 a\.m\. and led/i,
  },
  {
    id: "late-imperative",
    original: "The meeting is moved to 3pm Thursday — same Zoom link https://example.com/meet/abc123, do not be late.",
    candidate: "The meeting is moved to 3:00 pm Thursday — same Zoom link https://example.com/meet/abc123. Do not be late.",
    expected: /Do not be late\.$/,
  },
  {
    id: "version",
    original: "Version 2.4.1 ships on 2026-03-15; see https://example.com/releases/v2.4.1 for notes.",
    candidate: "Version 2.4.1 ships on 2026-03-15; see https://example.com/releases/v2.4.1 for notes.",
    expected: /Version 2\.4\.1 ships/,
  },
  {
    id: "adjective-clause",
    original: "The seperate informations was recieved alot more later then we had hopped, alot was missing.",
    candidate: "The separate information was received a lot more later than we had hoped, and a lot was missing.",
    expected: /a lot was missing\.$/i,
  },
];
for (const regressionCase of finalizerRegressionCases) {
  const spans = extractProtectedSpans(regressionCase.original);
  const finalized = finalizeDraft(regressionCase.candidate, regressionCase.original, spans, "personal", false);
  assert(regressionCase.expected.test(finalized), `${regressionCase.id} finalizer regression: ${finalized}`);
  assert(!/\b(?:be is|was are is)\b/i.test(finalized), `${regressionCase.id} introduced auxiliary duplication: ${finalized}`);
  assert(validateProtectedContent(regressionCase.original, finalized, spans).safe, `${regressionCase.id} changed protected content: ${finalized}`);
}
assert(
  extractProtectedSpans(finalizerRegressionCases[2].original).some((span) => span.text === "2.4.1"),
  "Semantic version was not treated as one protected number"
);
const frameResult = rewriteText(
  "The manager asked me to follow up with the client.",
  {
    mode: "personal",
    strength: 90,
    freezeWords: "",
    automaticRewriteStrategy: "conservative",
    automaticRewriteBudget: 3,
  },
  {}
);
assert(frameResult.tokens.some((token) => token.originalText.toLowerCase() === "asked me to"), "Phrase-first frame matching missed asked me to");
assert(!/\b(?:sought|requested|inquired|questioned)\s+(?:me|us|you|him|her|them)\s+to\b/i.test(frameResult.outputText), "Frame rewrite created an invalid object pattern");
const directQualityFailure = validateRewriteQuality(
  "The manager asked me to follow up with the client.",
  "The manager sought me to follow up with the client."
);
assert(!directQualityFailure.safe, "Quality gate accepted an invalid verb frame");
const namedQualityFailure = validateRewriteQuality(
  "Ava Lopez asked Jordan Kim to review the draft.",
  "Ava Lopez sought Jordan Kim to review the draft."
);
assert(!namedQualityFailure.safe, "Quality gate accepted a named-person sought/to frame");
const bareGuideFailure = validateRewriteQuality(
  "The approach could help, but the team needs more evidence.",
  "The approach could guide, but the team needs more evidence."
);
assert(!bareGuideFailure.safe, "Quality gate accepted a bare transitive guide frame");
const broadProvideProbe = rewriteText(
  "A clear explanation should define the problem, acknowledge its limits, and give readers a practical next step.",
  { mode: "personal", strength: 90, freezeWords: "", automaticRewriteStrategy: "broad", automaticRewriteBudget: 8 },
  {},
);
assert(!/\b(?:provide|share) readers a\b/i.test(broadProvideProbe.outputText), "Broad rewrite created an invalid provide/share readers frame");
assert(
  !validateRewriteQuality(
    "A clear explanation should define the problem and give readers a practical next step.",
    "A clear explanation should define the problem and share readers a practical next step."
  ).safe,
  "Quality gate accepted the malformed “share readers a” frame"
);

const automaticDriftRegressions = [
  {
    id: "early-results",
    input: "The early results suggest that the approach could help, but the team should collect more evidence before making a firm claim.",
    forbidden: /\b(?:early consequences|collaborative group|working group)\b/i,
  },
  {
    id: "point-of-view",
    input: "The tool keeps the original point of view and avoids sounding like a different person wrote it.",
    forbidden: /\b(?:source|first|initial) point of (?:perspective|viewpoint)\b|\bvaried person\b/i,
  },
  {
    id: "paragraph-unit",
    input: "Meeting notes: review the opening paragraph before sending the draft.",
    forbidden: /\bopening (?:excerpt|selection)\b/i,
  },
  {
    id: "readers-frame",
    input: "A clear explanation should define the problem, acknowledge its limits, and give readers a practical next step.",
    forbidden: /\b(?:provide|share) readers a\b/i,
  },
];
for (const strength of [40, 60, 90]) {
  for (const regression of automaticDriftRegressions) {
    const result = await generateLocalParaphrase({
      originalText: regression.input,
      examples: [],
      memory: createEmptyPreferenceMemory(),
      mode: "personal",
      strength,
    });
    assert(result.safe, `${regression.id} was not returned as a safe local result at strength ${strength}`);
    assert(!regression.forbidden.test(result.text), `${regression.id} drifted at strength ${strength}: ${result.text}`);
  }
}

const strengthMonotonicProbe = "The careful writer reviewed the useful draft and explained its limits to the group.";
for (const [lower, higher] of [[25, 49], [50, 74], [75, 100]]) {
  const lowerResult = rewriteText(
    strengthMonotonicProbe,
    { mode: "personal", strength: lower, freezeWords: "", automaticRewriteStrategy: lower >= 50 ? "broad" : "conservative" },
    {},
  );
  const higherResult = rewriteText(
    strengthMonotonicProbe,
    { mode: "personal", strength: higher, freezeWords: "", automaticRewriteStrategy: higher >= 50 ? "broad" : "conservative" },
    {},
  );
  const lowerEdits = lowerResult.tokens.filter((token) => token.changed).length;
  const higherEdits = higherResult.tokens.filter((token) => token.changed).length;
  assert(lowerEdits <= higherEdits, `Higher slider strength selected fewer automatic edits within its band (${lower}: ${lowerEdits}, ${higher}: ${higherEdits})`);
}

const transitionQualityFailure = validateRewriteQuality(
  "Because the system is local, users can keep private drafts on the device.",
  "Although the system is local, users can keep private drafts on the device."
);
assert(!transitionQualityFailure.safe, "Quality gate accepted a changed causal relationship");

const parallelQualityFailure = validateRewriteQuality(
  "The team likes reading, writing, and revising.",
  "The team likes reading, writing, and revise."
);
assert(!parallelQualityFailure.safe, "Quality gate accepted a mixed verb series");

const vagueFlowFailure = analyzeSentenceFlow(
  "The tool keeps drafts private. Users can review them locally.",
  "The tool keeps drafts private. This can review them locally."
);
assert(vagueFlowFailure.some((issue) => issue.id === "vague-sentence-opening"), "Sentence-flow gate missed a vague new topic");

const repairedTransition = repairSentenceFlow(
  "Because the system is local, users can keep private drafts on the device.",
  "Although the system is local, users can keep private drafts on the device."
);
assert(repairedTransition.startsWith("Because"), "Sentence-flow repair did not restore the source relationship");
const repairedEmbeddedTransition = repairSentenceFlow(
  "I can focus when there are distractions.",
  "I can focus although there are distractions.",
);
assert(/focus when there are distractions\./i.test(repairedEmbeddedTransition), `Embedded sentence-flow repair failed: ${repairedEmbeddedTransition}`);
const repairedDroppedEmbeddedTransition = repairSentenceFlow(
  "I stay focused when there are distractions, and I organize tasks.",
  "I stay focused over long periods, handle distractions, and organize tasks.",
);
assert(/focused over long periods when there are distractions/i.test(repairedDroppedEmbeddedTransition), `Dropped sentence-flow relation was not restored: ${repairedDroppedEmbeddedTransition}`);
assert(!/\bwhen\s+handle\b/i.test(repairedDroppedEmbeddedTransition), `Dropped sentence-flow repair created a non-finite subordinate clause: ${repairedDroppedEmbeddedTransition}`);
const repairedParallelSeries = repairSentenceFlow(
  "The team likes reading, writing, and revising.",
  "The team likes reading, writing, and revise."
);
assert(/likes reading, writing, and revising\./i.test(repairedParallelSeries), `Parallel verb repair failed: ${repairedParallelSeries}`);
const repairedParallelFragment = repairSentenceFlow(
  "The team likes reading, writing, and revising. The draft is ready.",
  "The team likes reading, writing, and revise. The draft is ready."
);
assert(/likes reading, writing, and revising\./i.test(repairedParallelFragment), `Parallel repair failed after a paragraph boundary: ${repairedParallelFragment}`);

const concisionResult = await generateLocalParaphrase({
  originalText: "The team met in order to make use of the private tool at this point in time.",
  examples: [],
  memory: createEmptyPreferenceMemory(),
  mode: "personal",
  strength: 56,
});
assert(concisionResult.safe, "Concision repair produced an unsafe result");
assert(!/\bin order to\b|\bmake use of\b|\bat this point in time\b/i.test(concisionResult.text), `Concision repair left padded wording: ${concisionResult.text}`);

const modeProbeText = "The team used simple tools to improve their writing and review difficult ideas.";
assert(strengthBand(24) === "light" && strengthLabel(24) === "Light", "Light strength boundary drifted");
assert(strengthBand(25) === "balanced" && strengthLabel(25) === "Balanced", "Balanced strength boundary drifted");
assert(strengthBand(50) === "strong" && strengthLabel(50) === "Strong", "Strong strength boundary drifted");
assert(strengthBand(75) === "deep" && strengthLabel(75) === "Deep", "Deep strength boundary drifted");
assert(percentToStrengthLevel(74) === 3 && percentToStrengthLevel(75) === 4, "Strength level bands drifted from the slider");
assert(minimumAutomaticRewrites(16) === 0, "Light strength unexpectedly requires a rewrite");
assert(minimumAutomaticRewrites(60) === 2 && minimumAutomaticRewrites(90) === 3, "Higher strength minimum rewrite policy drifted");
assert(maximumAutomaticRewrites(16) === 1 && maximumAutomaticRewrites(60) === 5 && maximumAutomaticRewrites(90) === 8, "Rewrite budgets do not scale with strength");
const broadProbe = rewriteText(
  "The team revised the draft after reviewers identified gaps in the evidence.",
  { mode: "personal", strength: 90, freezeWords: "", automaticRewriteStrategy: "broad", automaticRewriteBudget: 8 },
  {},
).outputText;
assert(broadProbe !== "The team revised the draft after reviewers identified gaps in the evidence.", "Broad Strong/Deep fallback did not select a wider curated candidate");
const personalProbeResults = Object.fromEntries(
  [16, 40, 60, 90].map((strength, index) => [
    `level-${index + 1}`,
    rewriteText(
      modeProbeText,
      {
        mode: "personal",
        strength,
        freezeWords: "",
        disableAutomaticRewrites: false,
        automaticRewriteStrategy: strength >= 50 ? "broad" : "conservative",
        automaticRewriteBudget: maximumAutomaticRewrites(strength),
      },
      {}
    ).outputText,
  ])
);
const lexicalDifferenceCount = (original, candidate) => {
  const originalWords = original.toLowerCase().match(/[a-z0-9']+/g) ?? [];
  const candidateWords = candidate.toLowerCase().match(/[a-z0-9']+/g) ?? [];
  const width = Math.max(originalWords.length, candidateWords.length);
  return Array.from({ length: width }, (_, index) => originalWords[index] !== candidateWords[index]).filter(Boolean).length;
};
assert(
  lexicalDifferenceCount(modeProbeText, personalProbeResults["level-4"]) >= lexicalDifferenceCount(modeProbeText, personalProbeResults["level-1"]) + 2,
  "Deep Rewrite amount did not produce a materially larger lexical change than Light",
);
for (const [level, output] of Object.entries(personalProbeResults)) {
  assert(!/\bapplied applications?\b/i.test(output), `Personal ${level} produced an applied/application collision`);
  assert(!/\b([A-Za-z]+)\s+\1\b/i.test(output), `Personal ${level} repeated an adjacent word`);
}
const protectedOriginal =
  'Dr. Maya Chen wrote, "Keep the 42.5% result unchanged" in 2024. Email maya@example.com or visit https://example.com/report. The device may not change $1,200.';
const protectedSpans = extractProtectedSpans(protectedOriginal);
assert(protectedSpans.some((span) => span.kind === "percentage"), "Percentage was not protected");
assert(protectedSpans.some((span) => span.kind === "url"), "URL was not protected");
assert(protectedSpans.some((span) => span.kind === "email"), "Email was not protected");
assert(
  protectedSpans.find((span) => span.kind === "url")?.text === "https://example.com/report",
  "URL protection included trailing sentence punctuation"
);
assert(!validateProtectedContent(protectedOriginal, protectedOriginal.replace("42.5%", "43.5%"), protectedSpans).safe, "Changed percentage was accepted");
assert(validateProtectedContent(protectedOriginal, protectedOriginal.replace("device", "machine"), protectedSpans).safe, "Safe wording edit was rejected");
const negationCaseOriginal = "No idea where the file went.";
const negationCaseSpans = extractProtectedSpans(negationCaseOriginal);
assert(
  validateProtectedContent(negationCaseOriginal, "I have no idea where the file went.", negationCaseSpans).safe,
  "Case-only normalization of a protected negation was rejected",
);
assert(
  !validateProtectedContent(negationCaseOriginal, "I have some idea where the file went.", negationCaseSpans).safe,
  "Protected negation removal was accepted",
);

const baseMemory = createEmptyPreferenceMemory();
const learnedExample = {
  originalText: "The tool is useful.",
  finalText: "The tool is helpful.",
  groupedEditSummary: [{
    id: "edit-1",
    sequence: 1,
    type: "synonym-replacement",
    originalFragment: "useful",
    replacementFragment: "helpful",
    source: "synonym",
    relativeTimestamp: 1,
  }],
};
const learnedMemory = learnFromApproval(baseMemory, learnedExample);
assert(Object.keys(baseMemory.approvedReplacements).length === 0, "Memory changed before an approval was learned");
const nativeStyleContextProbe = buildNativeStyleContext([learnedExample], learnedMemory);
assert(nativeStyleContextProbe?.approvedExamples[0]?.finalText === "The tool is helpful.", "Approved style examples were not projected to the native context");
assert(nativeStyleContextProbe?.preferredReplacements.some((entry) => entry.original === "useful" && entry.replacement === "helpful"), "Approved replacement preference was not projected to the native context");
const directEditMemory = learnFromApproval(baseMemory, {
  originalText: "I wanted to explain the project.",
  finalText: "I needed to explain the project.",
  groupedEditSummary: [{
    id: "edit-direct-1",
    sequence: 1,
    type: "typed-replacement",
    originalFragment: "wanted",
    replacementFragment: "needed",
    source: "typed",
    relativeTimestamp: 1,
  }],
});
const directEditResult = await generateLocalParaphrase({
  originalText: "I wanted to explain the project.",
  examples: [],
  memory: directEditMemory,
  mode: "personal",
  strength: 40,
});
assert(/\bneeded\b/i.test(directEditResult.text), "A saved direct edit did not guide a future Personal rewrite");
const directPhraseMemory = learnFromApproval(baseMemory, {
  originalText: "The editor gives writers direct ideas.",
  finalText: "The editor gives writers practical ideas.",
  groupedEditSummary: [{
    id: "edit-direct-2",
    sequence: 1,
    type: "typed-replacement",
    originalFragment: "direct",
    replacementFragment: "practical",
    source: "typed",
    relativeTimestamp: 1,
  }],
});
const directPhraseResult = await generateLocalParaphrase({
  originalText: "The editor gives writers direct ideas.",
  examples: [],
  memory: directPhraseMemory,
  mode: "personal",
  strength: 40,
});
assert(/\bpractical\b/i.test(directPhraseResult.text), "A saved direct phrase edit did not guide a future Personal rewrite");
const wordBoundaryEdit = describeTextEdit(
  "The manager requested a follow-up.",
  "The supervisor requested a follow-up.",
  "typed"
);
assert(wordBoundaryEdit.originalFragment === "manager", "Typed edit diff split the original word at a shared suffix");
assert(wordBoundaryEdit.replacementFragment === "supervisor", "Typed edit diff split the replacement word at a shared suffix");
const wordBoundaryMemory = learnFromApproval(baseMemory, {
  originalText: "The manager requested a follow-up.",
  finalText: "The supervisor requested a follow-up.",
  groupedEditSummary: [wordBoundaryEdit],
});
const wordBoundaryResult = await generateLocalParaphrase({
  originalText: "The manager requested a follow-up.",
  examples: [],
  memory: wordBoundaryMemory,
  mode: "personal",
  strength: 40,
});
assert(/\bsupervisor\b/i.test(wordBoundaryResult.text), "A saved whole-word direct edit did not guide a future Personal rewrite");
const pastedEditMemory = learnFromApproval(baseMemory, {
  originalText: "The manager requested a follow-up.",
  finalText: "The supervisor requested a follow-up.",
  groupedEditSummary: [{
    ...wordBoundaryEdit,
    id: "edit-pasted-boundary",
    type: "pasted-revision",
    source: "paste",
  }],
});
const pastedEditResult = await generateLocalParaphrase({
  originalText: "The manager requested a follow-up.",
  examples: [],
  memory: pastedEditMemory,
  mode: "personal",
  strength: 40,
});
assert(/\bsupervisor\b/i.test(pastedEditResult.text), "A saved pasted revision did not guide a future Personal rewrite");
const generatedPersonalResults = {};
for (const [level, strength] of [["light", 16], ["balanced", 40], ["strong", 60], ["deep", 90]]) {
  const result = await generateLocalParaphrase({
    originalText: modeProbeText,
    examples: [],
    memory: learnedMemory,
    mode: "personal",
    strength,
  });
  assert(result.safe, `Personal ${level} did not return a safe generated result`);
  assert(!/\b(?:applied|employed|utilized)\s+(?:[A-Za-z-]+\s+)?applications?\b/i.test(result.text), `Personal ${level} kept an applied/application collision`);
  assert(!/\b([A-Za-z]+)\s+\1\b/i.test(result.text), `Personal ${level} repeated an adjacent word`);
  generatedPersonalResults[level] = result.text;
}

const attentionSample = "My ADHD makes it difficult for me to sustain attention for long periods, stay focused when there are distractions, organize tasks and assignments, and remember information or instructions.";
const attentionResult = await generateLocalParaphrase({
  originalText: attentionSample,
  examples: [],
  memory: learnedMemory,
  mode: "personal",
  strength: 56,
});
assert(attentionResult.safe, "The attention sample did not return a safe result");
assert(attentionResult.text !== attentionSample, "Strong paraphrase returned the original text unchanged when a safe local rewrite was available");

const qualityProbeSamples = [
  "The researchers used the method to examine the results.",
  "Because the system is local, users can keep private drafts on the device.",
  "The editor gives writers clear suggestions that make sentences easier to read.",
  "When students review their work, they can find better ways to explain difficult ideas.",
  "Although the process is simple, it may take time to understand.",
  "People often use these tools because they want faster feedback.",
  "The teacher asked the class to make the paragraph more concise.",
  "A strong argument should show evidence and address different perspectives.",
  "The app helps users organize and revise their drafts without sending them to a server.",
  "The team worked with teachers and students to improve communication.",
  "I asked for more time after the deadline changed.",
];
const qualityProbeForbiddenPatterns = [
  /\b(?:grasp|comprehend|recognize|fathom)\s+(?:myself|yourself|himself|herself|ourselves|themselves|itself)\s+(?:better|clearer|clearly|more clearly)\b/i,
  /\b(?:receive|get|accept|obtain)\s+a\s+break\s+from\b/i,
  /\b(?:easy|uncomplicated)\s+(?:tools?|devices?)\b/i,
  /\b(?:direct|plain|readable)\s+ideas?\b/i,
  /\b(?:fast|faster|rapid|timely)\s+(?:advice|guidance|comments?)\b/i,
  /\bit\s+(?:may|might|could|can)\s+(?:spend\s+time\s+learning|need\s+time\s+to\s+grasp)\b/i,
  /\binvited\s+the\s+class\s+to\b/i,
  /\b(?:improve|improves|improved|strengthen|strengthens|strengthened|enhance|enhances|enhanced)\s+(?:dialogue|interaction|exchange|conversation)\b/i,
];
const qualityProbeResults = [];
for (const sample of qualityProbeSamples) {
  const result = await generateLocalParaphrase({ originalText: sample, examples: [], memory: learnedMemory, strength: 76 });
  assert(result.safe, `Quality probe was not safe: ${sample}`);
  assert(!/\b([A-Za-z]+)\s+\1\b/i.test(result.text), `Quality probe repeated a word: ${result.text}`);
  assert(!/\b(?:sought|requested|inquired)\s+for\b/i.test(result.text), `Quality probe created an invalid verb-preposition pair: ${result.text}`);
  for (const pattern of qualityProbeForbiddenPatterns) {
    assert(!pattern.test(result.text), `Quality probe contained ${pattern}: ${result.text}`);
  }
  qualityProbeResults.push(`${sample} => ${result.text}`);
}
const adversarialSamples = [
  {
    input: "The manager asked me to follow up with the client tomorrow.",
    forbidden: [/\b(?:sought|requested|inquired|questioned)\s+(?:me|us|you|him|her|them)\s+to\b/i],
  },
  {
    input: "The students were asked to compare the sources and explain their reasoning.",
    forbidden: [/\b(?:sought|requested|inquired|questioned)\s+to\b/i, /\bmake\s+clear\s+(?:their|his|her|our|your|my)\b/i, /\bpupils?\b/i],
  },
  {
    input: "We need to take the cultural context into account.",
    forbidden: [/\b(?:require|receive|accept|obtain|grab|seize|carry)\s+[^.]*\s+into\s+account\b/i],
  },
  {
    input: "The conversation turned into an argument after the misunderstanding.",
    forbidden: [/\b(?:a|an)\s+case\b/i],
  },
  {
    input: "I appreciate your help with this project.",
    forbidden: [/\byour\s+guide\b/i, /\bguide\s+your\b/i],
  },
  {
    input: "This change could lead to better communication between the groups.",
    forbidden: [/\b(?:connection|interaction)\b/i],
  },
  {
    input: "The teacher gave feedback on my paragraph.",
    forbidden: [/\bguide\b/i, /\bsection\b/i],
  },
  {
    input: "This approach protects their original ideas.",
    forbidden: [/\bfirst\s+ideas\b/i],
  },
  {
    input: "I asked for more time after the deadline changed.",
    forbidden: [/\b(?:sought|requested|inquired|questioned)\s+for\b/i],
  },
];
for (const [level, strength] of [["light", 16], ["balanced", 40], ["strong", 60], ["deep", 90]]) {
  for (const sample of adversarialSamples) {
    const result = await generateLocalParaphrase({
      originalText: sample.input,
      examples: [],
      memory: learnedMemory,
      mode: "personal",
      strength,
    });
    const quality = validateRewriteQuality(sample.input, result.text, result.protectedSpans);
    assert(result.safe && quality.safe, "Adversarial " + level + " sample was not safe: " + sample.input);
    for (const forbidden of sample.forbidden) {
      assert(!forbidden.test(result.text), "Adversarial " + level + " sample created " + forbidden + ": " + result.text);
    }
  }
}

const naturalnessQualityProbes = [
  {
    original: "The presentation depended on strong eye contact.",
    candidate: "The presentation depended on convincing eye contact.",
    issue: "strong eye contact collocation",
  },
  {
    original: "The class discussed effective communication.",
    candidate: "The class discussed potent communication.",
    issue: "effective communication collocation",
  },
  {
    original: "The group had clear responsibilities.",
    candidate: "The group had understandable responsibilities.",
    issue: "clear responsibilities collocation",
  },
  {
    original: "The course covered relationships and groups.",
    candidate: "The course covered relations and groups.",
    issue: "relationships and groups collocation",
  },
  {
    original: "The teacher gave clear expectations to the class.",
    candidate: "The tutor gave understandable expectations to the class.",
    issue: "teacher role and expectations collocation",
  },
  {
    original: "The authors compared different perspectives before reaching a conclusion.",
    candidate: "The authors compared varied lenses before reaching a conclusion.",
    issue: "perspectives collocation",
  },
  {
    original: "The plan should improve communication between departments.",
    candidate: "The plan should improve dialogue between departments.",
    issue: "communication between groups collocation",
  },
  {
    original: "The report should explain the limits.",
    candidate: "The report should make clear the limits.",
    issue: "explain object frame",
  },
  {
    original: "Every student can ask for help when a topic is difficult.",
    candidate: "Every student can ask for guide when a topic is difficult.",
    issue: "ask for help frame",
  },
  {
    original: "The editor preserved the original wording.",
    candidate: "The editor preserved the source wording.",
    issue: "original wording collocation",
  },
  {
    original: "Our group used Microsoft Teams to coordinate the project.",
    candidate: "Our group drew on Microsoft Teams to coordinate the project.",
    issue: "named-tool collocation",
  },
  {
    original: "The team used simple tools to improve their writing and review difficult ideas.",
    candidate: "The team used basic devices to polish their writing and characterize difficult ideas.",
    issue: "tools and review collocations",
  },
  {
    original: "The type of memory test used can affect the result.",
    candidate: "The type of memory test worked with can affect the result.",
    issue: "postnominal used frame",
  },
  {
    original: "The test used three measures.",
    candidate: "The test drew on three measures.",
    issue: "used object frame",
  },
  {
    original: "Objective tests may help show whether a person is accurate.",
    candidate: "Objective tests may guide show whether a person is accurate.",
    issue: "help complement frame",
  },
  {
    original: "The findings explain that confidence is not always accurate.",
    candidate: "The findings describe that confidence is not always accurate.",
    issue: "explain that frame",
  },
  {
    original: "Practice can make people better at recognizing faces.",
    candidate: "Practice can make people clearer at recognizing faces.",
    issue: "better at frame",
  },
  {
    original: "A good general ability to remember faces is useful.",
    candidate: "A positive general ability to remember faces is useful.",
    issue: "good ability frame",
  },
  {
    original: "A person can be strong or weak at recognizing faces.",
    candidate: "A person can be powerful or weak at recognizing faces.",
    issue: "strong and weak ability contrast",
  },
  {
    original: "A strong argument should address different perspectives.",
    candidate: "A convincing point should address different perspectives.",
    issue: "argument meaning frame",
  },
  {
    original: "I helped clean without being asked.",
    candidate: "I helped clean without being sought.",
    issue: "passive asked frame",
  },
  {
    original: "I asked questions when the instructions were unclear.",
    candidate: "I sought questions when the instructions were unclear.",
    issue: "asked questions frame",
  },
  {
    original: "Boredom can help people understand themselves better and take a break from stimulation.",
    candidate: "Boredom can help people grasp themselves clearer and receive a break from stimulation.",
    issue: "reflexive understanding and break frames",
  },
  {
    original: "The team used simple tools to improve their writing.",
    candidate: "The crew used easy devices to improve their writing.",
    issue: "writing-tool context",
  },
  {
    original: "The editor gives writers clear suggestions.",
    candidate: "The editor gives writers direct ideas.",
    issue: "clear suggestions frame",
  },
  {
    original: "People want faster feedback.",
    candidate: "People want faster advice.",
    issue: "feedback frame",
  },
  {
    original: "Although the process is simple, it may take time to understand.",
    candidate: "It may spend time learning even though the process is easy.",
    issue: "modal take-time frame",
  },
  {
    original: "The teacher asked the class to revise the paragraph.",
    candidate: "The teacher invited the class to revise the paragraph.",
    issue: "asked-class frame",
  },
  {
    original: "The team worked to improve communication.",
    candidate: "The team worked to strengthen dialogue.",
    issue: "improve-communication frame",
  },
];
for (const probe of naturalnessQualityProbes) {
  const quality = validateRewriteQuality(probe.original, probe.candidate);
  assert(!quality.safe, `Quality gate accepted ${probe.issue}`);
}

const contextualRepairProbes = [
  {
    original: "Boredom can help people understand themselves better and take a break from stimulation.",
    candidate: "Boredom can help people grasp themselves clearer and receive a break from stimulation.",
    expected: "Boredom can help people understand themselves more clearly and take a break from stimulation.",
  },
  {
    original: "The team used simple tools to improve their writing.",
    candidate: "The crew used easy devices to improve their writing.",
    expected: "The team used basic tools to improve their writing.",
  },
  {
    original: "The editor gives writers clear suggestions.",
    candidate: "The editor gives writers direct ideas.",
    expected: "The editor gives writers clear suggestions.",
  },
  {
    original: "People want faster feedback.",
    candidate: "People want faster advice.",
    expected: "People want faster feedback.",
  },
  {
    original: "Although the process is simple, it may take time to understand.",
    candidate: "It may spend time learning even though the process is easy.",
    expected: "It may take time to understand even though the process is easy.",
  },
  {
    original: "The teacher asked the class to revise the paragraph.",
    candidate: "The teacher invited the class to revise the paragraph.",
    expected: "The teacher asked the class to revise the paragraph.",
  },
  {
    original: "The team worked to improve communication.",
    candidate: "The team worked to strengthen dialogue.",
    expected: "The team worked to strengthen communication.",
  },
];
for (const probe of contextualRepairProbes) {
  const repaired = repairContextualNaturalness(probe.original, probe.candidate);
  assert(repaired === probe.expected, "Contextual repair mismatch: " + repaired);
}

const naturalnessParagraph =
  "Our group used Microsoft Teams to coordinate the project. " +
  "I helped clean the room without being asked, and I asked questions when the instructions were unclear. " +
  "The presentation depended on strong eye contact and effective communication. " +
  "Clear responsibilities and clear expectations helped the group, and our relationships and groups improved over time. " +
  "The teacher compared different perspectives and improved communication between departments.";
for (const [level, strength] of [["light", 16], ["balanced", 40], ["strong", 60], ["deep", 90]]) {
  const result = await generateLocalParaphrase({
    originalText: naturalnessParagraph,
    examples: [],
    memory: learnedMemory,
    mode: "personal",
    strength,
  });
  assert(result.safe, `Naturalness ${level} paragraph was not safe`);
  for (const pattern of [
    /\b(?:drew on|turned to|relied on)\s+Microsoft Teams\b/i,
    /\bwithout being (?:sought|requested|questioned|inquired)\b/i,
    /\b(?:sought|requested|inquired|questioned)\s+questions?\b/i,
    /\b(?!strong\b)[A-Za-z-]+\s+eye\s+contact\b/i,
    /\b(?!clear\b)[A-Za-z-]+\s+responsibilities\b/i,
    /\b(?!relationships\b)[A-Za-z-]+\s+and\s+groups\b/i,
    /\b(?:potent|powerful|robust)\s+communication\b/i,
    /\b(?:tutor|mentor|guide)\s+(?:gave|asked|told|reminded)\b/i,
    /\b(?:varied|different|contrasting)\s+(?:angles?|views?|viewpoints?|outlooks?|lenses?|positions?|stances?)\b/i,
    /\b(?:connection|interaction|dialogue|conversation|exchange)\s+between\b/i,
  ]) {
    assert(!pattern.test(result.text), `Naturalness ${level} output contained ${pattern}: ${result.text}`);
  }
}
const eyewitnessEvidenceFixture = fs.readFileSync(
  path.join(ROOT_DIR, "tests/fixtures/eyewitness-evidence-start.txt"),
  "utf8"
).trim();
const eyewitnessForbiddenPatterns = [
  /\b(?:drew on|turned to|relied on|worked with)\s+Microsoft Teams\b/i,
  /\b(?:drew on|turned to|relied on|worked with)\s+(?:a|an|the)\s+(?:broom|test)\b/i,
  /\b(?:test|method|approach|system|tool)\s+(?:drew on|turned to|relied on|worked with)\b/i,
  /\b(?:guide|assist|aid|support|facilitate)\s+(?:show|understand|find|make|read)\b/i,
  /\b(?:display|present|demonstrate|clarify)\s+(?:whether|if|how|why|what)\b/i,
  /\b(?:describe|detail|outline|illustrate)\s+that\b/i,
  /\b(?:clearer|stronger|greater|higher|effective|improved|useful)\s+at\b/i,
  /\b(?:positive|healthy|constructive|helpful|powerful|worthwhile)\s+(?:(?:general|face|overall|specific)\s+)?(?:witnesses?|memory|ability|evidence)\b/i,
  /\b(?:powerful|convincing|persuasive|robust|solid)\b[^.!?]{0,45}\bweak\s+at\s+recognizing\s+faces\b/i,
  /\b([A-Za-z]+)\s+\1\b/i,
];
for (const [level, strength] of [["light", 16], ["balanced", 40], ["strong", 60], ["deep", 90]]) {
  const result = await generateLocalParaphrase({
    originalText: eyewitnessEvidenceFixture,
    examples: [],
    memory: learnedMemory,
    mode: "personal",
    strength,
  });
  const quality = validateRewriteQuality(
    eyewitnessEvidenceFixture,
    result.text,
    result.protectedSpans
  );
  assert(
    result.safe && quality.safe,
    `Eyewitness fixture ${level} was not safe: ${result.text}\nnotice=${result.notice ?? "none"} originalSentences=${countSentences(eyewitnessEvidenceFixture)} outputSentences=${countSentences(result.text)} issues=${quality.issues.map((issue) => issue.id).join(",")}`
  );
  assert(
    validateProtectedContent(
      eyewitnessEvidenceFixture,
      result.text,
      result.protectedSpans
    ).safe,
    `Eyewitness fixture ${level} changed protected content`
  );
  for (const pattern of eyewitnessForbiddenPatterns) {
    assert(!pattern.test(result.text), `Eyewitness fixture ${level} produced ${pattern}`);
  }
}
const unsafeLearnedMemory = learnFromApproval(baseMemory, {
  originalText: "This change improves communication between the groups.",
  finalText: "This change improves connection between the groups.",
  groupedEditSummary: [{
    id: "edit-unsafe-learned",
    sequence: 1,
    type: "typed-replacement",
    originalFragment: "communication",
    replacementFragment: "connection",
    source: "typed",
    relativeTimestamp: 1,
  }],
});
const unsafeLearnedResult = await generateLocalParaphrase({
  originalText: "This change could lead to better communication between the groups.",
  examples: [],
  memory: unsafeLearnedMemory,
  mode: "personal",
  strength: 90,
});
assert(unsafeLearnedResult.safe, "An unsafe learned replacement made Personal generation unsafe");
assert(!/\bconnection\b/i.test(unsafeLearnedResult.text), "An unsafe learned communication replacement bypassed context validation");
const sentenceRewriteInput = "The editor gives writers clear suggestions that make sentences easier to read.";
const sentenceRewriteResult = await generateLocalParaphrase({
  originalText: sentenceRewriteInput,
  examples: [],
  memory: learnedMemory,
  mode: "personal",
  strength: 100,
});
assert(sentenceRewriteResult.safe, "Sentence rewrite result was not safe");
assert(sentenceRewriteResult.text !== sentenceRewriteInput, "Sentence rewrite did not change the selected sentence");
assert((sentenceRewriteResult.text.match(/[.!?]/g) ?? []).length === 1, "Sentence rewrite changed sentence count");
const highStructureInput = "Because the system is local, users can keep private drafts on the device. In some situations, being bored can help people think more creatively.";
const highStructureOutput = restructureHighStrength(highStructureInput, 100);
assert(
  highStructureOutput === "Users can keep private drafts on the device because the system is local. Boredom can help people think more creatively in some situations.",
  `High Rewrite amount did not restructure safe fronted clauses: ${highStructureOutput}`,
);
assert(
  restructureHighStrength(highStructureInput, 56) === highStructureInput,
  "Balanced Rewrite amount unexpectedly applied the high-strength structure pass",
);
const highNativeStructureOutput = restructureHighStrength(
  "Boredom is often perceived as a negative experience. In certain contexts, it can foster creative thinking.",
  100,
);
assert(
  highNativeStructureOutput === "Boredom is often perceived as a negative experience. It can foster creative thinking in certain contexts.",
  `High native candidate did not receive the bounded structural pass: ${highNativeStructureOutput}`,
);
const pronounOrderInput = "When students review their work, they can find clearer ways to explain difficult ideas.";
assert(
  restructureHighStrength(pronounOrderInput, 100) === pronounOrderInput,
  "High Rewrite amount created a cataphoric pronoun opening",
);
const trailingStructureOutput = restructureHighStrength(
  "Users can keep private drafts on the device because the system is local. Most people try to avoid boredom by watching videos, scrolling through social media, and playing games.",
  100,
);
assert(
  trailingStructureOutput === "Because the system is local, users can keep private drafts on the device. By watching videos, scrolling through social media, and playing games, most people try to avoid boredom.",
  `High Rewrite amount did not move safe trailing clauses: ${trailingStructureOutput}`,
);
const restoredQuantityOutput = repairQuantityScope(
  "Most people avoid boredom.",
  "Many individuals avoid boredom.",
);
assert(restoredQuantityOutput === "Most individuals avoid boredom.", `Native quantity repair did not restore most after a weakening drift: ${restoredQuantityOutput}`);
assert(
  repairQuantityScope("Most people avoid boredom.", "The majority of people avoid boredom.") === "The majority of people avoid boredom.",
  "Native quantity repair overwrote an explicit majority equivalent",
);
const factualTimeInput = "Jordan Lee emailed the draft to review@example.org at 3:40 p.m. The subject line was 'Budget revision v2,' and the attachment was 2.8 MB.";
const factualTimeSpans = extractProtectedSpans(factualTimeInput);
const factualTimeSentences = splitSentences(factualTimeInput);
assert(factualTimeSentences.length === 2, `Sentence splitter misread factual time anchors: ${factualTimeSentences.map((sentence) => sentence.text).join(" | ")}`);
assert(factualTimeSentences[0]?.text.endsWith("3:40 p.m."), `Sentence splitter truncated a meridiem: ${factualTimeSentences[0]?.text ?? ""}`);
assert(countSentences("The release is version 2.8.1. It is ready.") === 2, "Sentence splitter treated a decimal version as a sentence boundary");
const factualTimeCandidate = "Jordan Lee sent the draft to review@example.org at 3:40 p.m. The subject line was \"Budget revision v2,\" and the attachment was 2.8 MB.";
const factualTimeFinal = finalizeDraft(factualTimeCandidate, factualTimeInput, factualTimeSpans, "personal", false);
assert(factualTimeFinal.startsWith("Jordan Lee sent the draft"), `Factual time finalizer dropped the sentence prefix: ${factualTimeFinal}`);
assert(
  factualTimeFinal.includes("review@example.org") && factualTimeFinal.includes("3:40 p.m.") && factualTimeFinal.includes("2.8 MB"),
  `Factual time finalizer changed protected anchors: ${factualTimeFinal}`,
);
const factualTimeHigh = restructureHighStrength(factualTimeCandidate, 100, factualTimeSpans);
assert(factualTimeHigh.startsWith("Jordan Lee sent the draft"), `High structure pass dropped factual prefix: ${factualTimeHigh}`);
assert(
  factualTimeHigh.includes("3:40 p.m.") && factualTimeHigh.includes("2.8 MB"),
  `High structure pass changed factual time anchors: ${factualTimeHigh}`,
);
const protectedStructureOutput = restructureHighStrength(
  "Because Pari is local, users can keep private drafts on the device.",
  100,
  [{ text: "Pari" }],
);
assert(protectedStructureOutput.includes("Pari"), "High-strength structure pass changed a protected span");
const secondPassResult = await generateLocalParaphrase({
  originalText: (await generateLocalParaphrase({ originalText: modeProbeText, examples: [], memory: learnedMemory, strength: 76 })).text,
  examples: [],
  memory: learnedMemory,
  mode: "personal",
  strength: 100,
});
assert(secondPassResult.safe, "Second-pass paraphrase was not safe");
assert(!/\bapplications?\s+(?:authors?|writers?|users?|people)\b/i.test(secondPassResult.text), "Second-pass paraphrase created a noun/subject collision");
assert(!/\b(?:helps?|aids?|assists?|supports?|guides?)\s+(?:authors?|writers?|users?|students?)\s+(?:review|assess|examine|organize|revise)\b/i.test(secondPassResult.text), "Second-pass paraphrase created a missing-complement collocation");
const usefulEntry = getSynonymEntry("useful");
const usefulOptions = buildCandidateOptions("useful", usefulEntry);
const usefulRanked = rankCandidatesByMemory(
  usefulOptions.map((option, index) => ({ option, score: usefulOptions.length - index, risk: "low", warnings: [] })),
  "useful",
  learnedMemory
);
assert(usefulRanked[0]?.option.replacement.toLowerCase() === "helpful", "Approved replacement did not move to the top");
assert(retrieveRelevantExamples("The tool is useful.", [{ ...learnedExample, id: "approved-1", createdAt: "2026-07-23T00:00:00Z" }], 5).length === 1, "Approved example retrieval missed a relevant example");

const typedOne = describeTextEdit("The tool is helpful.", "The tool is very helpful.", "typed", {}, 10);
const typedTwo = describeTextEdit("The tool is very helpful.", "The tool is very helpful today.", "typed", {}, 500);
const grouped = appendGroupedEdit(appendGroupedEdit([], typedOne), typedTwo);
assert(grouped.length === 1, "Typed edits were stored as individual keystroke events");

const samples = [
  "Students can improve their writing when teachers give clear feedback. A useful tool can help a student find better words and understand difficult ideas.",
  "A company may use simple local software to make work more efficient. People need fast suggestions, but the tool should keep the original meaning clear.",
  "Local writing tools are important because private drafts should stay on the device. Fast offline models can suggest better phrasing without sending personal text to a remote server.",
  "Private drafts stay on the device while people review their writing.",
];

const results = [];
for (const sample of samples) {
  const result = await generateLocalParaphrase({ originalText: sample, examples: [], memory: learnedMemory });
  assert(result.text.trim().length > 0, "Generated paragraph was empty");
  assert(result.source === "local-safe-engine", "Unexpected non-local generation source");
  assert(validateProtectedContent(sample, result.text, result.protectedSpans).safe, "Generated output failed protection validation");
  assert(!/\b(?:raise|boost|increase)\s+(?:their|my|your|his|her|our|its)\s+(?:wording|prose|draft)\b/i.test(result.text), "Generated output contains an awkward writing collocation");
  assert(!/\b(?:helpful|useful)\s+tool\s+can\s+help\b/i.test(result.text), "Generated output repeats the same help stem in one phrase");
  assert(!/\bwithout\s+contribute\b/i.test(result.text), "Generated output contains an invalid infinitive after without");
  if (/\bwhile\b/i.test(sample)) {
    assert(/\bwhile\b/i.test(result.text), "Generated output changed a temporal while-clause");
    assert(!/\balthough\b/i.test(result.text), "Generated output changed a temporal clause into a contrast");
  }
  results.push(result);
}

const nuclearFixtures = [
  {
    name: "fragment-notes",
    mode: "personal",
    text: "need fix this text. no grammar. ideas missing. make it good",
    forbidden: [/\bneed\s+fix\b/i, /\bno\s+grammar\b/i, /\bideas?\s+missing\b/i],
  },
  {
    name: "meeting-notes",
    mode: "personal",
    text: "meeting tomorrow with the client, who is upset due to the delay. need to explain clearly without blaming. send update before noon",
    forbidden: [/^Meeting tomorrow/i, /^Need\s+to\s+explain\b/i, /\bsend\s+update\b/i],
  },
  {
    name: "punctuation-free-meeting-notes",
    mode: "personal",
    text: "meeting tomorrow client upset delay need explain no blame and keep message short",
    forbidden: [/^Meeting tomorrow/i, /\bneed\s+explain\b/i, /\bno\s+blame\s+and\s+keep\b/i],
    required: [/(?:Tomorrow's meeting|The meeting tomorrow) is with a client/i, /(?:explain|describe) the delay, with no blame, and keep the message short/i],
  },
  {
    name: "agreement-collapse",
    mode: "personal",
    text: "the project was not finished, reasons unclear, team say they is waiting, manager want answer now",
    forbidden: [/\bthey\s+is\b/i, /\bteam\s+say\b/i, /\bmanager\s+want\b/i, /\breasons?\s+unclear\b/i],
  },
  {
    name: "warmth-cold-brief",
    mode: "warmth",
    text: "The user failed to comply. Their request is invalid. No further assistance will be provided.",
    forbidden: [/\bfailed\s+to\s+comply\b/i, /\brequest\s+is\s+invalid\b/i, /\bno\s+further\s+assistance\b/i],
    required: [/clarification about the next step is welcome/i],
  },
  {
    name: "warmth-cynical-notes",
    mode: "warmth",
    text: "Deadline missed. Team performance unacceptable. Fix immediately. No excuses.",
    forbidden: [/\bdeadline\s+missed\b/i, /\bperformance\s+unacceptable\b/i, /\bfix\s+immediately\b/i, /\bno\s+excuses\b/i],
    required: [/performance is not where it needs to be/i, /focus on the next step/i],
  },
  {
    name: "meaning-guardrails",
    mode: "personal",
    text: "Not all users approved the plan. The model may fail. Only students reviewed the draft.",
    forbidden: [/\ball\s+users\s+approved\b/i, /\bmodel\s+will\s+fail\b/i, /\bsome\s+students\s+reviewed\b/i],
  },
  {
    name: "direct-english-filler",
    mode: "personal",
    text: "It is important to note that there are a number of issues due to the fact that the plan changed.",
    forbidden: [/\bit is important to note\b/i, /\bthere are a number of\b/i, /\bdue to the fact that\b/i],
  },
  {
    name: "bookish-negation",
    mode: "personal",
    text: "It is not the case that the method is useless. There is no indication that the team agrees.",
    forbidden: [/\bit is not the case that\b/i],
    required: [/\bthere is no indication that the team agrees\b/i],
  },
];

for (const fixture of nuclearFixtures) {
  const result = await generateLocalParaphrase({
    originalText: fixture.text,
    examples: [],
    memory: createEmptyPreferenceMemory(),
    mode: fixture.mode,
    strength: 82,
  });
  assert(result.safe, `${fixture.name}: nuclear repair was not safe: ${result.notice ?? "no notice"} -> ${result.text}`);
  assert(result.text !== fixture.text, `${fixture.name}: nuclear repair did not change the input: ${result.notice ?? "no notice"} -> ${result.text}`);
  assert(/[.!?]$/.test(result.text), `${fixture.name}: nuclear repair did not close the paragraph`);
  assert(!/\.{2,}/.test(result.text), `${fixture.name}: duplicate sentence punctuation remained: ${result.text}`);
  for (const pattern of fixture.forbidden) {
    assert(!pattern.test(result.text), `${fixture.name}: unrepaired pattern remained: ${pattern} -> ${result.text}`);
  }
  for (const pattern of fixture.required ?? []) {
    assert(pattern.test(result.text), `${fixture.name}: expected structure was missing: ${pattern} -> ${result.text}`);
  }
  assert(!looksLikeModelControlEcho(result.text), `${fixture.name}: control text reached the output`);
  console.log(`[qa:paraphrase] nuclear ${fixture.mode}/${fixture.name}: ${result.text}`);
}

const baselineReflection = fs.readFileSync(
  path.join(ROOT_DIR, "tests/fixtures/final-communication-reflection.txt"),
  "utf8"
).trim();
const baselineReflectionResult = await generateLocalParaphrase({
  originalText: baselineReflection,
  examples: [],
  memory: learnedMemory,
  mode: "personal",
  strength: 56,
});
assert(baselineReflectionResult.safe, "Communication reflection baseline was not safe");
assert(
  validateProtectedContent(
    baselineReflection,
    baselineReflectionResult.text,
    baselineReflectionResult.protectedSpans
  ).safe,
  "Communication reflection baseline changed protected content"
);
for (const pattern of [
  /\bbody\s+(?:speech|tongue)\b/i,
  /\b(?:drew on|turned to|worked with)\s+(?:different|varied|contrasting)\s+(?:tones?|details?)\b/i,
  /\bwithout being (?:invited|questioned)\b/i,
  /\b(?:invited|questioned)\s+clean\b/i,
  /\breadable\s+expectations\b/i,
]) {
  assert(!pattern.test(baselineReflectionResult.text), `Baseline contains a low-quality context rewrite: ${pattern}`);
}

const benchmarkText = Array.from({ length: 120 }, (_, index) => `The local writing tool helps people review a paragraph quickly and keep private drafts on device ${index + 1}.`).join(" ");
const timings = [];
for (let index = 0; index < 5; index += 1) {
  const started = performance.now();
  const result = await generateLocalParaphrase({ originalText: benchmarkText, examples: [], memory: learnedMemory });
  timings.push(Math.round(performance.now() - started));
  assert(result.safe, "Warm benchmark output was not safe");
}
const sortedTimings = [...timings].sort((left, right) => left - right);
const median = sortedTimings[Math.floor(sortedTimings.length / 2)];

console.log(`[qa:paraphrase] synonym choices: ${targetTerms.map((term) => `${term}=${buildCandidateOptions(term, getSynonymEntry(term)).length}`).join(", ")}`);
console.log(`[qa:paraphrase] used choices: ${usedOptions.length}; phrase rewrite available`);
console.log(`[qa:paraphrase] ordinary inline choices: ${["communication", "skills", "students", "connect"].map((term) => `${term}=${ordinaryWords.tokens.find((token) => token.originalText.toLowerCase() === term)?.alternatives.length ?? 0}`).join(", ")}`);
console.log(`[qa:paraphrase] broader inline choices: ${["editor", "writers", "models", "workflow", "server"].map((term) => `${term}=${broaderOrdinaryWords.tokens.find((token) => token.originalText.toLowerCase() === term)?.alternatives.length ?? 0}`).join(", ")}`);
console.log(`[qa:paraphrase] contextual dictionary choices: ${contextualChoiceCounts.join(", ")}`);
console.log(`[qa:paraphrase] Personal levels: ${Object.entries(personalProbeResults).map(([level, output]) => `${level}=${output}`).join(" | ")}`);
console.log(`[qa:paraphrase] generated Personal levels: ${Object.entries(generatedPersonalResults).map(([level, output]) => `${level}=${output}`).join(" | ")}`);
console.log(`[qa:paraphrase] sentence rewrite: ${sentenceRewriteInput} => ${sentenceRewriteResult.text}`);
for (const probe of qualityProbeResults) console.log(`[qa:paraphrase] quality probe: ${probe}`);
console.log(`[qa:paraphrase] protected spans: ${protectedSpans.length}`);
console.log(`[qa:paraphrase] approved preference: helpful ranks first`);
console.log(`[qa:paraphrase] grouped edit events: ${grouped.length}`);
for (const [index, result] of results.entries()) {
  console.log(`[qa:paraphrase] sample ${index + 1}: ${result.text}`);
}
console.log(`[qa:paraphrase] latency benchmark ms: ${timings.join(", ")} median=${median}`);
console.log("[qa:paraphrase] PASS");

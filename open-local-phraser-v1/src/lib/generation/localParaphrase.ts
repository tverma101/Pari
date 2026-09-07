import { rewriteText } from "@/lib/phraseEngine/rewriteText";
import type { CandidateOption } from "@/lib/ranking/types";
import type { RewriteMode } from "@/lib/types";
import {
  extractProtectedSpans,
  serializeProtectedSpans,
  validateProtectedContent,
  type ProtectedSpan,
} from "@/lib/safety/protectedContent";
import {
  repairArticleAgreement,
  repairContextualNaturalness,
  needsStructuralRepair,
  validateRewriteQuality,
} from "@/lib/generation/rewriteQuality";
import { repairSentenceFlow } from "@/lib/generation/sentenceFlow";
import { repairEnglishGrammar } from "@/lib/generation/englishGrammarRepair";
import {
  looksLikeModelControlEcho,
  repairBrokenProse,
} from "@/lib/generation/brokenProseRepair";
import { infinitiveFromGerund, repairDirectEnglish } from "@/lib/generation/directEnglishRepair";
import { analyzeHarperGrammar } from "@/lib/nlp/harper";
import {
  generateNativeParaphrase,
  nativeParaphraseAvailable,
  type NativeStyleContext,
} from "@/lib/platform/nativeParaphrase";
import { rankNativeCandidates } from "@/lib/generation/nativeCandidateRanker";
import {
  preferredCandidate,
  retrieveRelevantExamples,
  type ApprovedExample,
  type PreferenceMemory,
} from "@/lib/personalization/approvalMemory";
import type { RewriteToken } from "@/lib/phraseEngine/types";
import {
  effectiveStyleStrength,
  engineModeForStyle,
  type CustomStyle,
} from "@/lib/styles/customStyles";

export interface LocalParaphraseRequest {
  originalText: string;
  examples: ApprovedExample[];
  memory: PreferenceMemory;
  mode?: RewriteMode;
  strength?: number;
  style?: CustomStyle;
  signal?: AbortSignal;
}

export interface LocalParaphraseResult {
  text: string;
  protectedSpans: ProtectedSpan[];
  source: "native-mlx" | "freellm-api" | "local-safe-engine";
  durationMs: number;
  retryCount: number;
  retrievedExampleCount: number;
  safe: boolean;
  notice?: string;
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw new DOMException("Paraphrase cancelled", "AbortError");
}

function protectedValuesFor(originalText: string, protectedSpans: ProtectedSpan[]): string[] {
  return [...new Set(
    (protectedSpans.length ? protectedSpans : extractProtectedSpans(originalText)).map((span) => span.text)
  )].sort((left, right) => right.length - left.length);
}

function withProtectedPlaceholders(
  text: string,
  protectedValues: string[],
  transform: (masked: string) => string
): string {
  let masked = text;
  protectedValues.forEach((value, index) => {
    masked = masked.split(value).join("\uE000" + String.fromCharCode(0xE100 + index) + "\uE001");
  });
  const transformed = transform(masked);
  return transformed.replace(
    /\uE000([\s\S])\uE001/g,
    (_match, index) => protectedValues[index.charCodeAt(0) - 0xE100] ?? ""
  );
}

function compactStyleText(value: string, maxLength: number): string {
  return value.trim().replace(/\s+/g, " ").slice(0, maxLength);
}

/**
 * Project approved local behavior into a small style-only context for the
 * native generator. The current paragraph remains the only source of facts;
 * this context exists to carry voice, rhythm, and explicitly approved word
 * preferences across the native/fallback boundary.
 */
export function buildNativeStyleContext(
  examples: ApprovedExample[],
  memory: PreferenceMemory,
): NativeStyleContext | undefined {
  const approvedExamples = examples
    .slice(0, 3)
    .map((example) => ({
      originalText: compactStyleText(example.originalText, 420),
      finalText: compactStyleText(example.finalText, 420),
    }))
    .filter((example) => example.originalText && example.finalText);

  const preferredReplacements = Object.entries(memory.approvedReplacements)
    .flatMap(([original, replacements]) => Object.entries(replacements).map(([replacement, count]) => ({
      original: compactStyleText(original, 80),
      replacement: compactStyleText(replacement, 80),
      count,
    })))
    .filter((entry) => entry.original && entry.replacement && entry.original !== entry.replacement)
    .sort((left, right) => right.count - left.count || left.original.localeCompare(right.original))
    .slice(0, 12);

  const avoidedPhrases = Object.entries(memory.avoidedPhrases)
    .sort(([, leftCount], [, rightCount]) => rightCount - leftCount)
    .map(([phrase]) => compactStyleText(phrase, 80))
    .filter(Boolean)
    .slice(0, 8);

  const preferredContractions = Object.entries(memory.contractions)
    .sort(([, leftCount], [, rightCount]) => rightCount - leftCount)
    .map(([contraction]) => compactStyleText(contraction, 32))
    .filter((contraction) => /['’]/.test(contraction))
    .slice(0, 8);

  const sentencePreference = (['shorter', 'longer', 'similar'] as const)
    .map((value) => ({ value, count: memory.sentenceStructure[value] ?? 0 }))
    .sort((left, right) => right.count - left.count)[0];

  if (
    approvedExamples.length === 0 &&
    preferredReplacements.length === 0 &&
    avoidedPhrases.length === 0 &&
    preferredContractions.length === 0 &&
    !sentencePreference?.count
  ) {
    return undefined;
  }

  return {
    approvedExamples,
    preferredReplacements,
    avoidedPhrases,
    preferredContractions,
    ...(sentencePreference?.count ? { sentencePreference: sentencePreference.value } : {}),
  };
}

export function applyWarmthAdjustments(
  text: string,
  originalText: string,
  protectedSpans: ProtectedSpan[]
): string {
  const protectedValues = protectedValuesFor(originalText, protectedSpans);
  const protectedPlaceholder = "\\uE000[\\s\\S]\\uE001";
  const warmConditionalRefusal = new RegExp(
    `(^|\\s)((?:no|${protectedPlaceholder}))\\s+further\\s+(?:assistance|help|guide)\\s+((?:will|${protectedPlaceholder}))\\s+be\\s+(?:provided|given|available)\\s+until\\s+([^.!?]+)`,
    "gi",
  );
  const warmAbsoluteRefusal = new RegExp(
    `(^|\\s)((?:no|${protectedPlaceholder}))\\s+further\\s+(?:assistance|help|guide)\\s+((?:will|${protectedPlaceholder}))\\s+be\\s+(?:provided|given|available)\\b(?!\\s+until)`,
    "gi",
  );
  const warmNoExcuses = new RegExp(
    `(^|\\s)((?:no|${protectedPlaceholder}))\\s+excuses\\b`,
    "gi",
  );
  const polished = withProtectedPlaceholders(text, protectedValues, (masked) => masked
    .replace(warmConditionalRefusal, (_match, prefix: string, noWord: string, willWord: string, condition: string) =>
      `${prefix}${noWord} further help ${willWord} be available until ${condition.trim()}, and clarification about the next step is welcome`
    )
    .replace(warmAbsoluteRefusal, (_match, prefix: string, noWord: string, willWord: string) =>
      `${prefix}${noWord} further help ${willWord} be available; clarification about the next step is welcome`
    )
    .replace(warmNoExcuses, (_match, prefix: string, noWord: string) =>
      `${prefix}${noWord} valid excuses are needed; let's focus on the next step`
    )
    .replace(/\bindividuals\b/gi, "people")
    .replace(/\bpersons\b/gi, "people")
    .replace(/\butili[sz](?:e|ed|es|ing)\b/gi, (match) => {
      if (/ing$/i.test(match)) return "using";
      if (/ed$/i.test(match)) return "used";
      if (/es$/i.test(match)) return "uses";
      return "use";
    })
    .replace(/\bassistance\b/gi, "help")
    .replace(/\bassist(?:s|ed|ing)?\b/gi, (match) => {
      if (/ing$/i.test(match)) return "helping";
      if (/ed$/i.test(match)) return "helped";
      if (/s$/i.test(match)) return "helps";
      return "help";
    })
    .replace(/\bcommence(?:s|d)?\b/gi, (match) => /s$/i.test(match) ? "begins" : /d$/i.test(match) ? "began" : "begin")
    .replace(/\bterminate(?:s|d)?\b/gi, (match) => /s$/i.test(match) ? "ends" : /d$/i.test(match) ? "ended" : "end")
    .replace(/\bprior to\b/gi, "before")
    .replace(/\bsubsequent to\b/gi, "after")
    .replace(/\bregarding\b/gi, "about")
    .replace(/\bcannot\b/gi, "can't")
    .replace(/\bdo not\b/gi, "don't")
    .replace(/\bdoes not\b/gi, "doesn't")
    .replace(/\bdid not\b/gi, "didn't")
    .replace(/\bwill not\b/gi, "won't")
    .replace(/\bis not\b/gi, "isn't")
    .replace(/\bare not\b/gi, "aren't")
    .replace(/\bwas not\b/gi, "wasn't")
    .replace(/\bwere not\b/gi, "weren't")
    .replace(/\bfailed to comply\b/gi, "didn't follow the instructions")
    .replace(/\bfailed to\b/gi, "didn't")
    .replace(/\bfails to comply\b/gi, "doesn't follow the instructions")
    .replace(/\bfails to\b/gi, "doesn't")
    .replace(/\brequest is invalid\b/gi, "request doesn't meet the requirements")
    .replace(/\bthis is your responsibility\b/gi, "you'll need to handle the next step")
    .replace(/\bfix immediately\b/gi, "please address this as soon as possible")
    .replace(/\bthe problem is obvious\b/gi, "the problem is clear")
    .replace(/\bI am disappointed\b/g, "I'm concerned")
    .replace(/\b(team(?:'s)? performance)\s+unacceptable\b/gi, "$1 is not where it needs to be")
    .replace(/\bis unacceptable\b/gi, "is not where it needs to be")
    .replace(/\bunacceptable\b/gi, "not where it needs to be")
    .replace(/\bcan't help\b(?!\s+with)/gi, "can't help with this")
    .replace(/\bno further (?:assistance|help) will be (?:provided|given) until\s+([^.!?]+)/gi, (_match, condition: string) => `Once ${condition.trim()}, the next step can move forward smoothly`)
    .replace(/\bno further help will be available until\s+([^.!?]+)/gi, (_match, condition: string) => `Once ${condition.trim()}, the next step can move forward smoothly`)
    .replace(/\b(the user) (?:didn't|did not) meet the requirements\b/gi, "$1 didn't meet the requirements. The missing pieces can be worked through")
    .replace(/\b(the deadline) was missed\b/gi, "$1 was missed. Let's focus on the next step")
  );
  return polished;
}

export function finalizeDraft(
  candidate: string,
  originalText: string,
  protectedSpans: ProtectedSpan[],
  mode: RewriteMode,
  warmthPolish = false
): string {
  let repaired = repairBrokenProse(candidate, originalText, protectedSpans);
  repaired = repairDirectEnglish(repaired, protectedSpans);
  repaired = repairLocalCollocations(repaired, originalText, protectedSpans);
  repaired = repairDirectEnglish(repaired, protectedSpans);
  repaired = repairBrokenProse(repaired, originalText, protectedSpans);
  if (mode === "warmth" || mode === "warm" || warmthPolish) {
    repaired = applyWarmthAdjustments(repaired, originalText, protectedSpans);
    repaired = repairDirectEnglish(repaired, protectedSpans);
  }
  return repairEnglishGrammar(repaired, protectedSpans);
}

function repairLocalCollocations(
  text: string,
  originalText: string,
  protectedSpans: ProtectedSpan[] = []
): string {
  const protectedValues = protectedValuesFor(originalText, protectedSpans);
  let repaired = text;

  protectedValues.forEach((value, index) => {
    repaired = repaired
      .split(value)
      .join("\uE000" + String.fromCharCode(0xE100 + index) + "\uE001");
  });

  repaired = repaired
    .replace(/\s+([,.;!?])/g, "$1")
    .replace(/([,.;!?])(?=[A-Za-z])/g, "$1 ")
    // Prefer the shorter, clearer construction when a synonym pass leaves
    // common nominalized or padded phrases behind. These edits preserve the
    // clause relationship and do not touch protected spans.
    .replace(/\bin order to\b/gi, "to")
    .replace(/\bdue to the fact that\b/gi, "because")
    .replace(/\bat (?:this|the present) point in time\b/gi, "now")
    .replace(/\bin the event that\b/gi, "if")
    .replace(/\bhas the ability to\b/gi, "can")
    .replace(/\bmake use of\b/gi, "use")
    .replace(/\bthere\s+are\s+a\s+number\s+of\b/gi, "there are several")
    .replace(/\bnotwithstanding\s+the\s+fact\s+that\b/gi, "although")
    .replace(/\bfor\s+the\s+purpose\s+of\s+([A-Za-z]+ing)\b/gi, (_match, verb: string) => `to ${infinitiveFromGerund(verb)}`)
    .replace(/\bdepend\s+of\b/gi, "depend on")
    .replace(/\bresponsible\s+of\b/gi, "responsible for")
    .replace(/\binterested\s+on\b/gi, "interested in")
    .replace(/\bprevent\s+([A-Za-z]+)\s+to\s+([A-Za-z]+ing)\b/gi, "prevent $1 from $2")
    .replace(/\ballow\s+([A-Za-z]+)\s+([A-Za-z]+ing)\b/gi, "allow $1 to $2")
    .replace(/\bsuggest\s+to\s+([A-Za-z]+ing)\b/gi, "suggest $1")
    .replace(/\b(aid|assist)\s+(a|an|the)\s+([A-Za-z]+)\s+to\s+(discover|find|understand|make|read)\b/gi, "help $2 $3 $4")
    .replace(/\b(aid|assist)\s+(a|an|the)\s+([A-Za-z]+)\s+(discover|find|understand|make|read|review)\b/gi, "help $2 $3 $4")
    .replace(/\b(aid|assist)\s+([A-Za-z]+)\s+(review|discover|find|understand|make|read)\b/gi, "help $2 $3")
    .replace(/\b(?:build|create)\s+(work|a sentence)\b/gi, "make $1")
    .replace(
      /\b(helps?|aids?|assists?|supports?|guides?)\s+(authors?|writers?|users?|students?)\s+(review|assess|examine|organize|revise)\b/gi,
      "$1 $2 as they $3"
    )
    .replace(/\b(?:seeing that|considering that)\b/gi, (match) => (/^[A-Z]/.test(match) ? "Because" : "because"))
    .replace(/\bat the place where\b/gi, "where")
    .replace(/\bwithout\s+contribute\b/gi, "without sending")
    .replace(/\bwork\s+and\s+(?:absorb|grasp|master)\b/gi, "work and learn")
    .replace(
      /\b(a|an|the)\s+(helpful|useful)\s+tool\s+can\s+help\s+(a|an|the)\s+student\s+(?:find|discover)\s+better\s+words\s+and\s+understand\s+difficult\s+ideas\b/gi,
      "$1 $2 tool can guide $3 student toward better words and help them understand difficult ideas"
    );

  // The generic bank can produce a technically related but unnatural pair
  // such as "raise their wording". When the source clearly refers to
  // writing, use a conservative phrase that keeps the original intent.
  if (/\bimprove\s+(?:their|my|your|his|her|our|its)\s+writing\b/i.test(originalText)) {
    repaired = repaired.replace(
      /\b(?:raise|boost|increase|develop)\s+(their|my|your|his|her|our|its)\s+(?:wording|prose|draft)\b/gi,
      "refine $1 writing"
    );
  }

  // Avoid a repeated stem when a formal synonym for "used" is followed by
  // the noun synonym "applications". Keep the sentence's register while
  // preserving the source meaning.
  repaired = repaired.replace(
    /\b(applied|employed|utilized)\s+((?:basic|simple|straightforward|local|online|digital)\s+)?applications?\b/gi,
    "$1 $2tools"
  );

  repaired = repairContextualNaturalness(originalText, repaired);
  if (/\bneed(?:s|ed)?\s+to\s+explain\s+clearly\b/i.test(originalText)) {
    repaired = repaired.replace(/\b(?:describe|detail|outline)\s+clearly\b/gi, "explain clearly");
  }
  repaired = repairSentenceFlow(originalText, repaired);

  repaired = repairArticleAgreement(repaired).replace(/\b(the)\s+the\b/gi, "$1");

  return repaired.replace(
    /\uE000([\s\S])\uE001/g,
    (_match, index) => protectedValues[index.charCodeAt(0) - 0xE100] ?? ""
  );
}

function automaticRewriteBudget(strength: number): number {
  // Two deliberate edits per sentence is enough to make a draft feel
  // different while preventing the synonym bank from replacing every noun.
  // Higher strength can add one more edit, but never turns into a word dump.
  if (strength >= 82) return 3;
  if (strength >= 42) return 2;
  return 1;
}

async function hasNewHighGrammarIssue(originalText: string, candidateText: string): Promise<string | null> {
  // Harper is an optional browser-side validator. A cold WASM startup must
  // not hold the user-facing generation promise indefinitely, especially on
  // the optional FreeLLM route where the model response has already arrived.
  const timeoutMs = 1500;
  let timeout: ReturnType<typeof setTimeout> | undefined;
  try {
    const grammarCheck = Promise.all([
      analyzeHarperGrammar(originalText),
      analyzeHarperGrammar(candidateText),
    ]).then(([originalIssues, candidateIssues]) => {
      const originalHighLabels = new Set(
        originalIssues.filter((issue) => issue.severity === "high").map((issue) => issue.label)
      );
      const newIssue = candidateIssues.find(
        (issue) => issue.severity === "high" && !originalHighLabels.has(issue.label)
      );
      return newIssue?.detail ?? null;
    }).catch(() => null);

    const boundedCheck = new Promise<string | null>((resolve) => {
      timeout = setTimeout(() => resolve(null), timeoutMs);
    });
    return await Promise.race([grammarCheck, boundedCheck]);
  } catch {
    // Harper is an additional local validator. The synchronous hard rules and
    // protected-content gate remain the required fallback if its WASM runtime
    // cannot initialize in a particular browser.
    return null;
  } finally {
    if (timeout !== undefined) clearTimeout(timeout);
  }
}

async function inspectNativeDraft(
  nativeText: string,
  originalText: string,
  protectedSpans: ProtectedSpan[],
  mode: RewriteMode,
  structuralRepair: boolean,
  warmthPolish = false,
): Promise<{ text: string; safe: boolean; reason?: string }> {
  if (looksLikeModelControlEcho(nativeText)) {
    return {
      text: nativeText,
      safe: false,
      reason: "The native draft echoed editing instructions instead of rewriting the text.",
    };
  }

  const repairedText = finalizeDraft(nativeText, originalText, protectedSpans, mode, warmthPolish);
  const validation = validateProtectedContent(originalText, repairedText, protectedSpans);
  const quality = validateRewriteQuality(originalText, repairedText, protectedSpans, {
    allowStructuralRepair: structuralRepair,
  });
  const grammarFailure = quality.safe
    ? await hasNewHighGrammarIssue(originalText, repairedText)
    : null;

  return {
    text: repairedText,
    safe: validation.safe && quality.safe && !grammarFailure && repairedText !== originalText,
    reason: grammarFailure ?? quality.reason ?? validation.reason ??
      (repairedText === originalText ? "The native draft did not make a safe wording change." : undefined),
  };
}

function buildPreferredChoices(
  originalText: string,
  memory: PreferenceMemory,
  protectedSpans: ProtectedSpan[],
  mode: RewriteMode,
  strength: number
): { choices: Record<string, string>; extraAlternatives: Record<string, CandidateOption[]> } {
  const protectedWords = new Set(
    protectedSpans.flatMap((span) => span.text.toLowerCase().match(/[a-z]+(?:[-'][a-z]+)*/g) ?? [])
  );
  const safeText = originalText;
  const preview = rewriteText(
    safeText,
    {
      mode,
      strength,
      freezeWords: serializeProtectedSpans(protectedSpans),
      disableAutomaticRewrites: true,
    },
    {}
  );
  const choices: Record<string, string> = {};
  const extraAlternatives: Record<string, CandidateOption[]> = {};

  const buildLearnedCandidate = (token: RewriteToken): CandidateOption | null => {
    const preferred = memory.approvedReplacements[token.originalText.trim().toLowerCase().replace(/\s+/g, " ")];
    if (!preferred) return null;

    const replacement = Object.entries(preferred)
      .sort(([left, leftCount], [right, rightCount]) => rightCount - leftCount || left.localeCompare(right))[0]?.[0]
      ?.trim();
    if (!replacement || replacement.toLowerCase() === token.originalText.trim().toLowerCase()) return null;

    // A direct approval may introduce a word that is not in the static bank.
    // Keep that learned candidate bounded to a word/phrase-shaped replacement;
    // the normal protected-content and fluency gates still decide whether it
    // survives paragraph generation.
    if (!/^[A-Za-z]+(?:[-'][A-Za-z]+)*(?:\s+[A-Za-z]+(?:[-'][A-Za-z]+)*)*$/.test(replacement)) return null;
    if (protectedWords.has(replacement.toLowerCase())) return null;

    return {
      id: `personal-memory-${token.id}`,
      original: token.originalText,
      replacement,
      label: "Personal preference",
      source: "rule",
      risk: "low",
      partOfSpeech: token.partOfSpeech,
      modePreference: ["personal"],
    };
  };

  for (const token of preview.tokens) {
    if (!token.isWord || token.frozen) continue;
    if (protectedWords.has(token.originalText.toLowerCase())) continue;
    const memoryKey = token.originalText.trim().toLowerCase().replace(/\s+/g, " ");
    const learnedCandidate = buildLearnedCandidate(token);
    if (!learnedCandidate && !memory.approvedReplacements[memoryKey]) continue;
    const options = learnedCandidate ? [...token.alternatives, learnedCandidate] : token.alternatives;
    if (learnedCandidate && !token.alternatives.some((option) => option.replacement.toLowerCase() === learnedCandidate.replacement.toLowerCase())) {
      extraAlternatives[token.id] = [learnedCandidate];
    }
    const choice = preferredCandidate(options, token.originalText, memory);
    if (choice) choices[token.id] = choice.id;
  }

  return { choices, extraAlternatives };
}

export async function generateLocalParaphrase(
  request: LocalParaphraseRequest
): Promise<LocalParaphraseResult> {
  const startedAt = performance.now();
  const originalText = request.originalText.trim();
  const customStyle = request.style ?? null;
  const mode = customStyle ? engineModeForStyle(customStyle) : request.mode ?? "personal";
  const strength = effectiveStyleStrength(customStyle, request.strength ?? 56);
  const protectedSpans = extractProtectedSpans(originalText);
  const structuralRepair = customStyle?.tweaks.preserveSentenceCount === false
    ? true
    : needsStructuralRepair(originalText);
  const preparedSource = structuralRepair
    ? repairBrokenProse(originalText, originalText, protectedSpans)
    : originalText;
  const warmthPolish = customStyle?.tweaks.warmthPolish ?? false;
  const retrievedExamples = retrieveRelevantExamples(originalText, request.examples, 5);
  const nativeStyleContext = buildNativeStyleContext(retrievedExamples, request.memory);
  throwIfAborted(request.signal);

  let nativeFailureNotice: string | undefined;
  if (nativeParaphraseAvailable()) {
    try {
      const native = await generateNativeParaphrase({
        originalText: preparedSource,
        protectedSpans: protectedSpans.map((span) => span.text),
        mode,
        strength,
        maxTokens: Math.min(1536, Math.max(256, Math.ceil(preparedSource.length / 2))),
        candidates: 4,
        styleInstructions: customStyle?.instructions,
        styleTweaks: customStyle?.tweaks,
        ...(nativeStyleContext ? { styleContext: nativeStyleContext } : {}),
      }, request.signal);
      throwIfAborted(request.signal);
      const nativeSource = native.backend === "freellm-api" ? "freellm-api" : "native-mlx";
      const nativeRouteLabel = native.backend === "freellm-api" ? "through FreeLLMAPI" : "locally";

      // Best-of-N: rank every candidate with the same gates a single draft
      // must pass. FreeLLM deliberately returns one network candidate, so use
      // the bounded single-draft inspector on that route: local learned model
      // assets are reserved for local multi-candidate ranking and cannot delay
      // an already-completed remote response. Protected-content, deterministic
      // quality, and the bounded Harper grammar gate still apply.
      let inspection: { text: string; safe: boolean; reason?: string };
      const candidateList = native.candidates ?? [{ text: native.text }];
      if (native.backend === "freellm-api" && candidateList.length === 1) {
        inspection = await inspectNativeDraft(
          candidateList[0]?.text ?? native.text,
          originalText,
          protectedSpans,
          mode,
          structuralRepair,
          warmthPolish,
        );
      } else {
        try {
          const ranked = await rankNativeCandidates(candidateList, {
            originalText,
            protectedSpans,
            mode,
            structuralRepair,
            finalizeDraft,
            warmthPolish,
          });
          const winner = ranked.find((candidate) => candidate.safe);
          if (winner) {
            return {
              text: winner.text,
              protectedSpans,
              source: nativeSource,
              durationMs: Math.round(performance.now() - startedAt),
              retryCount: 0,
              retrievedExampleCount: retrievedExamples.length,
              safe: true,
              notice: `Generated ${nativeRouteLabel} with ${native.modelId} (best of ${candidateList.length} candidates). Review the wording, then save it to teach Pari.`,
            };
          }
          inspection = { text: ranked[0]?.text ?? native.text, safe: false, reason: `No candidate passed Pari's meaning and grammar checks (ranked=${ranked.length}, requested=${candidateList.length}).` };
        } catch (rankError) {
          if (rankError instanceof DOMException && rankError.name === "AbortError") throw rankError;
          // Ranker unavailable: still use best-of-N via the single-draft inspector.
          inspection = { text: native.text, safe: false, reason: `Candidate ranking was unavailable (${candidateList.length} candidates): ${rankError instanceof Error ? rankError.message : String(rankError)}` };
          for (const candidate of candidateList) {
            if (!candidate.text.trim()) continue;
            throwIfAborted(request.signal);
            const single = await inspectNativeDraft(
              candidate.text,
              originalText,
              protectedSpans,
              mode,
              structuralRepair,
              warmthPolish,
            );
            if (single.safe) {
              return {
                text: single.text,
                protectedSpans,
                source: nativeSource,
                durationMs: Math.round(performance.now() - startedAt),
                retryCount: 0,
                retrievedExampleCount: retrievedExamples.length,
                safe: true,
                notice: `Generated ${nativeRouteLabel} with ${native.modelId} (best of ${candidateList.length} candidates). Review the wording, then save it to teach Pari.`,
              };
            }
            inspection = { ...inspection, reason: single.reason ?? inspection.reason };
          }
        }
      }
      if (inspection.safe) {
        return {
          text: inspection.text,
          protectedSpans,
          source: nativeSource,
          durationMs: Math.round(performance.now() - startedAt),
          retryCount: 0,
          retrievedExampleCount: retrievedExamples.length,
          safe: true,
          notice: `Generated ${nativeRouteLabel} with ${native.modelId}. Review the wording, then save it to teach Pari.`,
        };
      }

      nativeFailureNotice = inspection.reason ?? "The native draft did not pass Pari's meaning and grammar checks.";

      // A rejected generation gets one stricter native editorial pass before
      // Pari falls back to deterministic rewriting. This keeps the user-facing
      // behavior unchanged while giving the bundled model a chance to repair a
      // good-but-rough draft instead of discarding it immediately.
      throwIfAborted(request.signal);
      try {
        const repairedNative = await generateNativeParaphrase({
          originalText: preparedSource,
          protectedSpans: protectedSpans.map((span) => span.text),
          mode,
          strength,
          maxTokens: Math.min(1536, Math.max(256, Math.ceil(preparedSource.length / 2))),
          repairPass: true,
          temperature: 0.14,
          styleInstructions: customStyle?.instructions,
          styleTweaks: customStyle?.tweaks,
          ...(nativeStyleContext ? { styleContext: nativeStyleContext } : {}),
        }, request.signal);
        throwIfAborted(request.signal);
        const retryInspection = await inspectNativeDraft(
          repairedNative.text,
          originalText,
          protectedSpans,
          mode,
          structuralRepair,
          warmthPolish,
        );
        if (retryInspection.safe) {
          const repairedSource = repairedNative.backend === "freellm-api" ? "freellm-api" : "native-mlx";
          const repairedRouteLabel = repairedNative.backend === "freellm-api" ? "through FreeLLMAPI" : "locally";
          return {
            text: retryInspection.text,
            protectedSpans,
            source: repairedSource,
            durationMs: Math.round(performance.now() - startedAt),
            retryCount: 1,
            retrievedExampleCount: retrievedExamples.length,
            safe: true,
            notice: `Generated ${repairedRouteLabel} with ${repairedNative.modelId} after a quality repair pass. Review the wording, then save it to teach Pari.`,
          };
        }
        nativeFailureNotice = `${nativeFailureNotice} The native repair pass also failed: ${retryInspection.reason ?? "its draft was unsafe."}`;
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") throw error;
        nativeFailureNotice = `${nativeFailureNotice} The native repair pass was unavailable: ${error instanceof Error ? error.message : String(error)}`;
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      nativeFailureNotice = error instanceof Error ? error.message : String(error);
    }
  }

  // This backend is intentionally deterministic and local. It gives the UI a
  // safe paragraph workflow when the native model is unavailable or its draft
  // fails closed. Every candidate still goes through the same protection gate.
  const { choices, extraAlternatives } = buildPreferredChoices(preparedSource, request.memory, protectedSpans, mode, strength);
  const first = rewriteText(
    preparedSource,
    {
      mode,
      strength,
      freezeWords: serializeProtectedSpans(protectedSpans),
      automaticRewriteStrategy: "conservative",
      automaticRewriteBudget: automaticRewriteBudget(strength),
    },
    choices,
    extraAlternatives
  );
  throwIfAborted(request.signal);

  const repairedText = finalizeDraft(first.outputText, originalText, protectedSpans, mode, warmthPolish);
  const firstValidation = validateProtectedContent(originalText, repairedText, protectedSpans);
  const firstQuality = validateRewriteQuality(originalText, repairedText, protectedSpans, {
    allowStructuralRepair: structuralRepair,
  });
  const firstGrammarFailure = firstValidation.safe && firstQuality.safe
    ? await hasNewHighGrammarIssue(originalText, repairedText)
    : null;
  if (firstValidation.safe && firstQuality.safe && !firstGrammarFailure && repairedText !== originalText) {
    return {
      text: repairedText,
      protectedSpans,
      source: "local-safe-engine",
      durationMs: Math.round(performance.now() - startedAt),
      retryCount: 0,
      retrievedExampleCount: retrievedExamples.length,
      safe: true,
      notice: nativeFailureNotice
        ? `The native generator was not used: ${nativeFailureNotice} The safer offline rewrite was used.`
        : undefined,
    };
  }

  // A seeded conservative pass can legitimately choose no candidate at the
  // default Strong setting. That feels like a dead button to the writer even
  // though safe local candidates exist. Retry once with the smallest stronger
  // setting, while keeping Light intentionally unchanged when no safe edit is
  // available.
  const retryStrength = strength >= 40 ? Math.max(60, strength) : strength;
  if (retryStrength > strength) {
    throwIfAborted(request.signal);
    const retry = rewriteText(
      preparedSource,
      {
        mode,
        strength: retryStrength,
        freezeWords: serializeProtectedSpans(protectedSpans),
        automaticRewriteStrategy: "conservative",
        automaticRewriteBudget: automaticRewriteBudget(retryStrength),
      },
      choices,
      extraAlternatives
    );
    const retryText = finalizeDraft(retry.outputText, originalText, protectedSpans, mode, warmthPolish);
    const retryValidation = validateProtectedContent(originalText, retryText, protectedSpans);
    const retryQuality = validateRewriteQuality(originalText, retryText, protectedSpans, {
      allowStructuralRepair: structuralRepair,
    });
    const retryGrammarFailure = retryValidation.safe && retryQuality.safe
      ? await hasNewHighGrammarIssue(originalText, retryText)
      : null;
    if (retryValidation.safe && retryQuality.safe && !retryGrammarFailure && retryText !== originalText) {
      return {
        text: retryText,
        protectedSpans,
        source: "local-safe-engine",
        durationMs: Math.round(performance.now() - startedAt),
        retryCount: 1,
        retrievedExampleCount: retrievedExamples.length,
        safe: true,
        notice: nativeFailureNotice
          ? `The native generator was not used: ${nativeFailureNotice} A safer offline rewrite was used.`
          : "The first local pass made no safe wording changes. A stronger local pass was used.",
      };
    }
  }

  throwIfAborted(request.signal);
  const conservative = rewriteText(
    preparedSource,
    {
      mode,
      strength: Math.max(16, Math.round(strength * 0.55)),
      freezeWords: serializeProtectedSpans(protectedSpans),
      automaticRewriteStrategy: "conservative",
      automaticRewriteBudget: 1,
    },
    {}
  ).outputText;
  const safeFallback = finalizeDraft(conservative, originalText, protectedSpans, mode, warmthPolish);
  const fallbackValidation = validateProtectedContent(originalText, safeFallback, protectedSpans);
  const fallbackQuality = validateRewriteQuality(originalText, safeFallback, protectedSpans, {
    allowStructuralRepair: structuralRepair,
  });
  const fallbackGrammarFailure = fallbackValidation.safe && fallbackQuality.safe
    ? await hasNewHighGrammarIssue(originalText, safeFallback)
    : null;
  const fallbackSafe = fallbackValidation.safe && fallbackQuality.safe && !fallbackGrammarFailure;
  const finalText = fallbackSafe ? safeFallback : originalText;
  const finalValidation = validateProtectedContent(originalText, finalText, protectedSpans);
  const finalQuality = validateRewriteQuality(originalText, finalText, protectedSpans, {
    allowStructuralRepair: structuralRepair,
  });

  return {
    text: finalText,
    protectedSpans,
    source: "local-safe-engine",
    durationMs: Math.round(performance.now() - startedAt),
    retryCount: 1,
    retrievedExampleCount: retrievedExamples.length,
    safe: finalValidation.safe && finalQuality.safe,
    notice: finalText === originalText
      ? "No safe local wording change was found. The text is unchanged; try a higher Rewrite amount or edit it directly."
      : (nativeFailureNotice
        ? `The native generator was not used: ${nativeFailureNotice} The safer offline draft was used. `
        : "The first local draft needed a stricter quality pass. ") +
        (firstQuality.reason ?? firstValidation.reason ?? firstGrammarFailure ?? fallbackGrammarFailure ?? "The safer draft was used."),
  };
}

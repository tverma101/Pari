import { countSentences, splitSentences } from "@/lib/nlp/sentenceSplit";
import { analyzeSentenceFlow } from "@/lib/generation/sentenceFlow";
import { grammarSafetyIssues } from "@/lib/nlp/grammar";
import { countWords, normalizeWord, tokenize } from "@/lib/nlp/tokenizer";
import { looksLikeUnrepairedFragmentaryProse } from "@/lib/generation/brokenProseRepair";
import { clauseAttachmentIssues } from "@/lib/nlp/clauseAttachment";
import { meaningContractIssues } from "@/lib/generation/meaningContract";
import {
  extractProtectedSpans,
  validateProtectedContent,
  type ProtectedSpan,
} from "@/lib/safety/protectedContent";

export interface RewriteQualityIssue {
  id: string;
  detail: string;
}

export interface RewriteQualityValidation {
  safe: boolean;
  reason?: string;
  issues: RewriteQualityIssue[];
}

export interface RewriteQualityOptions {
  /** Permit the native editor to join or split source fragments that are not real sentences. */
  allowStructuralRepair?: boolean;
}

export function needsStructuralRepair(text: string): boolean {
  const trimmed = text.trim();
  if (!trimmed) return false;

  const sentences = splitSentences(trimmed);
  const shortFragments = sentences.filter((sentence) => countWords(sentence.text) <= 3).length;
  const hasBrokenBoundary = /[.!?][A-Za-z]/.test(trimmed) || /\s+[,.;!?]/.test(trimmed);
  const hasLowercaseSentenceStart = /(?:^|[.!?]\s+)[a-z]/.test(trimmed);
  const hasRepeatedWord = /\b([A-Za-z]+)\s+\1\b/i.test(trimmed);

  return grammarSafetyIssues(trimmed).some((issue) => issue.severity !== "low") ||
    shortFragments >= 2 ||
    hasBrokenBoundary ||
    hasLowercaseSentenceStart ||
    hasRepeatedWord ||
    !/[.!?]"?$/.test(trimmed);
}

function startsWithVowelSound(value: string): boolean {
  const normalized = value.trim().toLowerCase();
  if (!normalized) return false;

  if (/^(?:honest|honor|honour|hour|heir|herb)\b/.test(normalized)) return true;
  if (/^(?:ewe|euro|one|once|uniform|unique|unit|united|university|use|useful|usefully|user|usual)\b/.test(normalized)) {
    return false;
  }

  return /^[aeiou]/.test(normalized);
}

const FRAME_RULES: Array<{ id: string; pattern: RegExp; detail: string }> = [
  {
    id: "require-infinitive",
    pattern: /\brequires?\s+to\b/i,
    detail: "\"Require\" needs an object or a noun phrase before the infinitive.",
  },
  {
    id: "sought-object-infinitive",
    pattern: /\b(?:sought|requested|inquired|questioned)\s+(?:me|us|you|him|her|them)\s+to\b/i,
    detail: "This verb replacement does not preserve the source verb's object pattern.",
  },
  {
    id: "passive-sought-infinitive",
    pattern: /\b(?:was|were|is|are|be|been|being)\s+sought\s+to\b/i,
    detail: "\"Sought\" cannot replace a passive \"asked to\" frame here.",
  },
  {
    id: "requested-for",
    pattern: /\b(?:sought|requested|inquired|questioned)\s+for\b/i,
    detail: "This replacement creates an invalid verb-preposition pair.",
  },
  {
    id: "guide-with",
    pattern: /\b(?:guide|guides|guided|guiding)\s+(?:me|us|you|him|her|them|[A-Za-z]+)\s+with\b/i,
    detail: "\"Guide\" does not preserve this \"help with\" construction.",
  },
  {
    id: "make-clear-possessive",
    pattern: /\bmake(?:s)?\s+clear\s+(?:my|your|his|her|our|their)\b/i,
    detail: "This \"make clear\" replacement needs a clause or a direct noun phrase.",
  },
  {
    id: "bad-take-into-account",
    pattern: /\b(?:receive|accept|obtain|grab|seize|carry|choose)\s+(?:(?:the|a|an|this|that|their|its|our|your|my)\s+)?[A-Za-z]+(?:\s+[A-Za-z]+){0,3}\s+into\s+account\b/i,
    detail: "This replacement does not preserve the \"take into account\" construction.",
  },
  {
    id: "repeated-word",
    pattern: /\b([A-Za-z]+)\s+\1\b/i,
    detail: "The rewrite repeats an adjacent word.",
  },
];

function maskProtectedFragments(text: string, protectedSpans: ProtectedSpan[]): string {
  let masked = text;
  const values = [...new Set(protectedSpans.map((span) => span.text))]
    .filter(Boolean)
    .sort((left, right) => right.length - left.length);

  for (const value of values) {
    const escaped = value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    masked = masked.replace(new RegExp(escaped, "g"), value.replace(/\S/g, "x"));
  }

  return masked;
}

function punctuationSpacingIssues(text: string, protectedSpans: ProtectedSpan[]): RewriteQualityIssue[] {
  const maskedText = maskProtectedFragments(text, protectedSpans);
  const punctuationPattern = /\s+[,.;!?]|[,.;!?](?=[A-Za-z])/g;
  if (punctuationPattern.test(maskedText)) {
    return [{
      id: "punctuation-spacing",
      detail: "The rewrite has malformed punctuation spacing.",
    }];
  }

  return [];
}

function lexicalIssues(text: string, protectedSpans: ProtectedSpan[] = []): RewriteQualityIssue[] {
  return [
    ...FRAME_RULES.filter((rule) => rule.pattern.test(text)).map(({ id, detail }) => ({ id, detail })),
    ...punctuationSpacingIssues(text, protectedSpans),
  ];
}

const REGISTER_SPIKE_WORDS = new Set([
  "additionally",
  "commence",
  "consequently",
  "demonstrate",
  "facilitate",
  "hence",
  "individuals",
  "inquire",
  "moreover",
  "numerous",
  "persons",
  "potent",
  "rapidly",
  "robust",
  "utilize",
  "utilized",
  "therefore",
  "thus",
]);

function wordsIn(text: string): string[] {
  return tokenize(text)
    .filter((token) => token.type === "word")
    .map((token) => normalizeWord(token.text));
}

function contextualNaturalnessIssues(original: string, candidate: string): RewriteQualityIssue[] {
  const issues: RewriteQualityIssue[] = [];

  if (
    /\bwithout\s+being\s+asked\b/i.test(original) &&
    /\bwithout\s+being\s+(?:sought|requested|questioned|inquired)\b/i.test(candidate)
  ) {
    issues.push({
      id: "passive-asked-rewrite",
      detail: "Keep the familiar phrase “without being asked.”",
    });
  }

  if (
    /\basked\s+(?:(?:me|us|you|him|her|them)\s+)?questions?\b/i.test(original) &&
    /\b(?:sought|requested|inquired|questioned)\s+questions?\b/i.test(candidate)
  ) {
    issues.push({
      id: "asked-questions-frame",
      detail: "The replacement does not fit the phrase “asked questions.”",
    });
  }

  const namedTool = original.match(/\bused\s+([A-Z][A-Za-z0-9-]*(?:\s+[A-Z][A-Za-z0-9-]*)*)/);
  if (namedTool) {
    const escapedName = namedTool[1].replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    if (new RegExp(`\\b(?:drew on|turned to|relied on)\\s+${escapedName}\\b`, "i").test(candidate)) {
      issues.push({
        id: "named-tool-drew-on",
        detail: "A named product or service is more natural after “used” here.",
      });
    }
  }

  const postnominalUsed = original.match(
    /\b(test|method|approach|system|tool|procedure|technique|measure|strategy)\s+used\b/i
  );
  if (
    postnominalUsed &&
    new RegExp(
      `\\b${postnominalUsed[1]}\\s+(?:drew on|turned to|relied on|worked with|employed|utilized)\\b`,
      "i"
    ).test(candidate)
  ) {
    issues.push({
      id: "postnominal-used-frame",
      detail: "Keep “used” when it describes a test, method, tool, or approach.",
    });
  }

  if (
    /\bhelp\s+(?:show|understand|find|make|read|explain|see|determine|identify|improve|review|recognize|interpret|remember|learn|compare)\b/i.test(original) &&
    /\b(?:guide|assist|aid|support|facilitate)\s+(?:show|understand|find|make|read|explain|see|determine|identify|improve|review|recognize|interpret|remember|learn|compare)\b/i.test(candidate)
  ) {
    issues.push({
      id: "help-complement-frame",
      detail: "Keep the complement in the familiar “help show” or “help understand” frame.",
    });
  }

  if (
    /\bhelp\s+show\s+(?:whether|if|how|why|what)\b/i.test(original) &&
    /\bhelp\s+(?:display|present|demonstrate|clarify)\s+(?:whether|if|how|why|what)\b/i.test(candidate)
  ) {
    issues.push({
      id: "help-show-frame",
      detail: "Keep “help show” before a following clause.",
    });
  }

  if (
    /\bexplain\s+that\b/i.test(original) &&
    /\b(?:describe|detail|outline|illustrate)\s+that\b/i.test(candidate)
  ) {
    issues.push({
      id: "explain-that-frame",
      detail: "Keep a verb that naturally introduces a following “that” clause.",
    });
  }

  if (
    /\bbetter\s+at\b/i.test(original) &&
    !/\bbetter\s+at\b/i.test(candidate) &&
    /\b[A-Za-z-]+\s+at\b/i.test(candidate)
  ) {
    issues.push({
      id: "better-at-frame",
      detail: "Keep the established comparative frame “better at.”",
    });
  }

  if (
    /\bgood\s+at\b/i.test(original) &&
    !/\bgood\s+at\b/i.test(candidate) &&
    /\b[A-Za-z-]+\s+at\b/i.test(candidate)
  ) {
    issues.push({
      id: "good-at-frame",
      detail: "Keep the established ability frame “good at.”",
    });
  }

  if (
    /\bgood\s+(?:(?:general|face|overall|specific)\s+)?(?:witnesses?|memory|ability|evidence)\b/i.test(original) &&
    /\b(?:positive|healthy|constructive|helpful|powerful|worthwhile)\s+(?:(?:general|face|overall|specific)\s+)?(?:witnesses?|memory|ability|evidence)\b/i.test(candidate)
  ) {
    issues.push({
      id: "good-quality-frame",
      detail: "Keep “good” in this quality description instead of changing its meaning or tone.",
    });
  }

  if (
    /\bsimple\s+effect\b/i.test(original) &&
    /\b(?:easy|basic|uncomplicated)\s+effect\b/i.test(candidate)
  ) {
    issues.push({
      id: "simple-effect-frame",
      detail: "Keep “simple effect” in this technical sentence frame.",
    });
  }

  if (
    /\bstrong\b[^.!?]{0,45}\bweak\s+at\s+recognizing\s+faces\b/i.test(original) &&
    /\b(?:powerful|convincing|persuasive|robust|solid)\b[^.!?]{0,45}\bweak\s+at\s+recognizing\s+faces\b/i.test(candidate)
  ) {
    issues.push({
      id: "strong-weak-ability-contrast",
      detail: "Keep “strong” in the contrast with “weak at recognizing faces.”",
    });
  }

  if (
    /\bstrong\s+eye\s+contact\b/i.test(original) &&
    !/\bstrong\s+eye\s+contact\b/i.test(candidate) &&
    /\b[A-Za-z-]+\s+eye\s+contact\b/i.test(candidate)
  ) {
    issues.push({
      id: "strong-eye-contact",
      detail: "Keep the established collocation “strong eye contact.”",
    });
  }

  if (
    /\bclear\s+responsibilities\b/i.test(original) &&
    !/\bclear\s+responsibilities\b/i.test(candidate) &&
    /\b[A-Za-z-]+\s+responsibilities\b/i.test(candidate)
  ) {
    issues.push({
      id: "clear-responsibilities",
      detail: "“Clear responsibilities” is more natural in this sentence frame.",
    });
  }

  if (
    /\bclear\s+expectations\b/i.test(original) &&
    !/\bclear\s+expectations\b/i.test(candidate) &&
    /\b[A-Za-z-]+\s+expectations\b/i.test(candidate)
  ) {
    issues.push({
      id: "clear-expectations",
      detail: "Keep the familiar collocation “clear expectations.”",
    });
  }

  if (
    /\brelationships\s+and\s+groups\b/i.test(original) &&
    !/\brelationships\s+and\s+groups\b/i.test(candidate) &&
    /\b[A-Za-z-]+\s+and\s+groups\b/i.test(candidate)
  ) {
    issues.push({
      id: "relationships-and-groups",
      detail: "Keep “relationships and groups” together as a coherent topic.",
    });
  }

  if (
    /\bdifferent\s+perspectives\b/i.test(original) &&
    /\b(?:varied|different|contrasting)\s+(?:angles?|views?|viewpoints?|outlooks?|lenses?|positions?|stances?)\b/i.test(candidate)
  ) {
    issues.push({
      id: "perspectives-to-angles",
      detail: "Keep “perspectives” in this established comparison phrase.",
    });
  }

  if (
    /\bteacher\s+(?:gave|asked|told|reminded)\b/i.test(original) &&
    /\b(?:tutor|mentor|guide)\s+(?:gave|asked|told|reminded)\b/i.test(candidate)
  ) {
    issues.push({
      id: "teacher-role-drift",
      detail: "Keep the role “teacher” in this classroom action frame.",
    });
  }

  if (
    /\bteachers?\b/i.test(original) &&
    /\btutors?\b/i.test(candidate) &&
    !/\btutors?\b/i.test(original)
  ) {
    issues.push({
      id: "teacher-role-drift",
      detail: "Keep the role “teacher” instead of changing it to “tutor.”",
    });
  }

  if (
    /\breview(?:ed|s|ing)?\b[^.!?]{0,45}\b(?:ideas?|work|drafts?)\b/i.test(original) &&
    /\b(?:characterize|characterized|characterizes|depict|depicted|portray|portrayed)\b[^.!?]{0,45}\b(?:ideas?|work|drafts?)\b/i.test(candidate)
  ) {
    issues.push({
      id: "review-ideas-collocation",
      detail: "Use “review” for examining ideas, work, or a draft in this sentence frame.",
    });
  }

  if (
    /\btools?\b/i.test(original) &&
    /\bdevices?\b/i.test(candidate) &&
    !/\bdevices?\b/i.test(original)
  ) {
    issues.push({
      id: "tools-to-devices-drift",
      detail: "Keep “tools” when the source describes software or writing tools.",
    });
  }

  if (
    /\bcommunication\s+between\b/i.test(original) &&
    /\b(?:connection|interaction|dialogue|conversation|exchange)\s+between\b/i.test(candidate)
  ) {
    issues.push({
      id: "communication-between-groups",
      detail: "Keep broad “communication” wording between groups or departments.",
    });
  }

  if (
    /\bmake\b[^.!?]{0,40}\bclear\b/i.test(original) &&
    /\bmake\b[^.!?]{0,40}\b(?:direct|plain|readable)\b/i.test(candidate)
  ) {
    issues.push({
      id: "make-clear-frame",
      detail: "Keep “clear” in this make-and-result sentence frame.",
    });
  }

  if (
    /\bask(?:s|ed)?\s+for\s+help\b/i.test(original) &&
    /\bask(?:s|ed)?\s+for\s+(?:guide|guidance|aid|assist|assistance)\b/i.test(candidate)
  ) {
    issues.push({
      id: "ask-for-help-frame",
      detail: "Keep the natural phrase “ask for help.”",
    });
  }

  if (
    /\bexplain\s+(?:the|a|an)\b/i.test(original) &&
    /\bmake\s+clear\s+(?:the|a|an)\b/i.test(candidate)
  ) {
    issues.push({
      id: "explain-object-frame",
      detail: "“Explain the…” is more natural than “make clear the…” here.",
    });
  }

  if (
    /\boriginal\s+wording\b/i.test(original) &&
    /\b(?:source|first)\s+wording\b/i.test(candidate)
  ) {
    issues.push({
      id: "original-wording",
      detail: "Keep the established phrase “original wording.”",
    });
  }

  const contextRules: Array<{ id: string; original: RegExp; candidate: RegExp; detail: string }> = [
    {
      id: "effective-communication",
      original: /\beffective\s+communication\b/i,
      candidate: /\b(?:potent|powerful|robust)\s+communication\b/i,
      detail: "Keep the natural collocation “effective communication.”",
    },
    {
      id: "strong-argument-case",
      original: /\bstrong\s+argument\b/i,
      candidate: /\bcompelling\s+case\b/i,
      detail: "Keep “argument” when the source describes a written claim.",
    },
    {
      id: "helped-gerund-frame",
      original: /\bhelped\s+([A-Za-z]+ing)\b/i,
      candidate: /\b(?:assisted|aided|facilitated)\s+([A-Za-z]+ing)\b/i,
      detail: "The replacement does not fit the verb-plus-gerund frame.",
    },
    {
      id: "made-decision-frame",
      original: /\bmade\s+(?:a\s+)?decision\b/i,
      candidate: /\b(?:created|built|produced)\s+(?:a\s+)?decision\b/i,
      detail: "Use the natural phrase “made a decision.”",
    },
    {
      id: "took-responsibility-frame",
      original: /\btook\s+responsibility\b/i,
      candidate: /\b(?:received|accepted|obtained|carried)\s+responsibility\b/i,
      detail: "The replacement does not preserve the phrase “took responsibility.”",
    },
  ];

  for (const rule of contextRules) {
    if (rule.original.test(original) && rule.candidate.test(candidate)) {
      issues.push({ id: rule.id, detail: rule.detail });
    }
  }

  return issues;
}

function paragraphNaturalnessIssues(original: string, candidate: string): RewriteQualityIssue[] {
  const issues: RewriteQualityIssue[] = [];
  const originalWords = wordsIn(original);
  const candidateWords = wordsIn(candidate);
  const originalCounts = new Map<string, number>();
  const candidateCounts = new Map<string, number>();

  for (const word of originalWords) originalCounts.set(word, (originalCounts.get(word) ?? 0) + 1);
  for (const word of candidateWords) candidateCounts.set(word, (candidateCounts.get(word) ?? 0) + 1);

  // A single synonym may be fine, but repeating the same newly introduced
  // content word several times is a common sign of mechanical rewriting.
  for (const [word, count] of candidateCounts) {
    if (word.length < 5 || count < 3) continue;
    const added = count - (originalCounts.get(word) ?? 0);
    if (added >= 3) {
      issues.push({
        id: "repeated-new-content-word",
        detail: `The rewrite repeats the newly introduced word “${word}” too often.`,
      });
      break;
    }
  }

  // Personal is intentionally warm and explanatory. Several unusually
  // formal substitutions in one sentence read more like a thesaurus pass
  // than a human rewrite, so reject that local register spike.
  const originalSentences = original.split(/(?<=[.!?])\s+/).filter(Boolean);
  const candidateSentences = candidate.split(/(?<=[.!?])\s+/).filter(Boolean);
  for (let index = 0; index < Math.min(originalSentences.length, candidateSentences.length); index += 1) {
    const sentenceOriginal = new Set(wordsIn(originalSentences[index]));
    const newFormalWords = wordsIn(candidateSentences[index]).filter(
      (word) => REGISTER_SPIKE_WORDS.has(word) && !sentenceOriginal.has(word)
    );
    if (newFormalWords.length >= 3) {
      issues.push({
        id: "local-register-spike",
        detail: "The rewrite stacks too many formal substitutions in one sentence.",
      });
      break;
    }

    const originalWordCount = countWords(originalSentences[index]);
    const candidateWordCount = countWords(candidateSentences[index]);
    const deliberateConcision =
      /\bit is (?:important|worth) to note that\b|\bit should be noted that\b|\bit is not the case that\b|\bthere is no indication that\b|\bthere are a number of\b|\bdue to the fact that\b|\bnotwithstanding the fact that\b|\bin order to\b|\bat (?:this|the present) point in time\b|\bin the event that\b|\bhas the ability to\b|\bmake use of\b/i.test(originalSentences[index]) &&
      !/\bit is (?:important|worth) to note that\b|\bit should be noted that\b|\bit is not the case that\b|\bthere is no indication that\b|\bthere are a number of\b|\bdue to the fact that\b|\bnotwithstanding the fact that\b|\bin order to\b|\bat (?:this|the present) point in time\b|\bin the event that\b|\bhas the ability to\b|\bmake use of\b/i.test(candidateSentences[index]);
    if (
      originalWordCount >= 10 &&
      !deliberateConcision &&
      (candidateWordCount > originalWordCount * 1.45 || candidateWordCount < originalWordCount * 0.65)
    ) {
      issues.push({
        id: "sentence-shape-drift",
        detail: "The rewrite changed a sentence's length too sharply for a natural paraphrase.",
      });
      break;
    }
  }

  return issues;
}

function semanticShiftIssues(original: string, candidate: string): RewriteQualityIssue[] {
  const issues: RewriteQualityIssue[] = [];

  if (
    /\bcommunication\b/i.test(original) &&
    !/\bconnection\b/i.test(original) &&
    /\bconnection\b/i.test(candidate)
  ) {
    issues.push({
      id: "communication-to-connection",
      detail: "\"Connection\" is not a safe automatic substitute for \"communication\" in general writing.",
    });
  }

  if (
    /\bargument\b/i.test(original) &&
    /\b(?:case|point|claim)\b/i.test(candidate) &&
    !/\bargument\b/i.test(candidate)
  ) {
    issues.push({
      id: "argument-to-case",
      detail: "This replacement changes the meaning of an argument in this sentence frame.",
    });
  }

  if (/\boriginal\b/i.test(original) && /\bfirst\b/i.test(candidate)) {
    issues.push({
      id: "original-to-first",
      detail: "\"First\" changes the meaning of \"original\" in this context.",
    });
  }

  if (/\bparagraphs?\b/i.test(original) && /\bsections?\b/i.test(candidate)) {
    issues.push({
      id: "paragraph-to-section",
      detail: "\"Section\" is not a safe automatic substitute for \"paragraph\".",
    });
  }

  if (
    /\b(?:my|your|his|her|our|their)\s+help\b/i.test(original) &&
    /\b(?:my|your|his|her|our|their)\s+guide\b/i.test(candidate)
  ) {
    issues.push({
      id: "possessive-help-to-guide",
      detail: "A possessive \"help\" is a noun here, not a verb that can become \"guide\".",
    });
  }

  if (/\bteacher\b/i.test(original) && /\bguide\b/i.test(candidate)) {
    issues.push({
      id: "teacher-to-guide",
      detail: "\"Guide\" changes the role described by \"teacher\".",
    });
  }

  return issues;
}

function hasImpliedFirstPersonFragment(text: string): boolean {
  return /(?:^|[.!?]\s+)(?:need|want|have\s+to|am|was|feel|think|remember|explain|send|write|review|fix)\b/i.test(text.trim()) ||
    /\bneed(?:\s+to)?\b/i.test(text);
}

export function analyzeRewriteQuality(
  original: string,
  candidate: string,
  protectedSpans: ProtectedSpan[] = extractProtectedSpans(original)
): RewriteQualityIssue[] {
  return [
    ...grammarSafetyIssues(candidate).map(({ id, detail }) => ({ id, detail })),
    ...clauseAttachmentIssues(original, candidate).map(({ id, detail }) => ({ id, detail })),
    ...lexicalIssues(candidate, protectedSpans),
    ...analyzeSentenceFlow(original, candidate),
    ...semanticShiftIssues(original, candidate),
    ...meaningContractIssues(original, candidate),
    ...contextualNaturalnessIssues(original, candidate),
    ...paragraphNaturalnessIssues(original, candidate),
  ];
}

export function repairContextualNaturalness(original: string, candidate: string): string {
  let repaired = candidate;

  if (/\bwithout\s+being\s+asked\b/i.test(original)) {
    repaired = repaired.replace(
      /\bwithout\s+being\s+(?:sought|requested|questioned|inquired)\b/gi,
      "without being asked"
    );
  }

  if (/\basked\s+(?:(?:me|us|you|him|her|them)\s+)?questions?\b/i.test(original)) {
    repaired = repaired.replace(
      /\b(?:sought|requested|inquired|questioned)\s+questions?\b/gi,
      (match) => match.replace(/^(?:sought|requested|inquired|questioned)/i, "asked")
    );
  }

  const namedTool = original.match(/\bused\s+([A-Z][A-Za-z0-9-]*(?:\s+[A-Z][A-Za-z0-9-]*)*)/);
  if (namedTool) {
    const escapedName = namedTool[1].replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    repaired = repaired.replace(
      new RegExp(`\\b(?:drew on|turned to|relied on)\\s+${escapedName}\\b`, "gi"),
      `used ${namedTool[1]}`
    );
  }

  const postnominalUsed = original.match(
    /\b(test|method|approach|system|tool|procedure|technique|measure|strategy)\s+used\b/i
  );
  if (postnominalUsed) {
    const escapedNoun = postnominalUsed[1].replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    repaired = repaired.replace(
      new RegExp(`\\b${escapedNoun}\\s+(?:drew on|turned to|relied on|worked with|employed|utilized)\\b`, "gi"),
      `${postnominalUsed[1]} used`
    );
  }

  if (/\breview(?:ed|s|ing)?\b[^.!?]{0,45}\b(?:ideas?|work|drafts?)\b/i.test(original)) {
    repaired = repaired.replace(
      /\b(?:characterize|characterized|characterizes|depict|depicted|portray|portrayed)\b(?=[^.!?]{0,45}\b(?:ideas?|work|drafts?)\b)/gi,
      (match) => /s$/i.test(match) && !/ed$/i.test(match) ? "reviews" : /ed$/i.test(match) ? "reviewed" : "review"
    );
  }

  if (/\bteachers?\b/i.test(original) && !/\btutors?\b/i.test(original)) {
    repaired = repaired.replace(/\btutors?\b/gi, (match) => /s$/i.test(match) ? "teachers" : "teacher");
  }

  if (/\btools?\b/i.test(original) && !/\bdevices?\b/i.test(original)) {
    repaired = repaired.replace(/\bdevices?\b/gi, (match) => /s$/i.test(match) ? "tools" : "tool");
  }

  if (/\bhelp\s+(?:show|understand|find|make|read|explain|see|determine|identify|improve|review|recognize|interpret|remember|learn|compare)\b/i.test(original)) {
    repaired = repaired.replace(
      /\b(?:guide|assist|aid|support|facilitate)\s+(show|understand|find|make|read|explain|see|determine|identify|improve|review|recognize|interpret|remember|learn|compare)\b/gi,
      "help $1"
    );
  }

  if (/\bhelp\s+show\s+(?:whether|if|how|why|what)\b/i.test(original)) {
    repaired = repaired.replace(
      /\bhelp\s+(?:display|present|demonstrate|clarify)\s+(whether|if|how|why|what)\b/gi,
      "help show $1"
    );
  }

  if (/\bexplain\s+that\b/i.test(original)) {
    repaired = repaired.replace(
      /\b(?:describe|detail|outline|illustrate)\s+that\b/gi,
      "explain that"
    );
  }

  if (/\bbetter\s+at\b/i.test(original)) {
    repaired = repaired.replace(
      /\b(?:clearer|stronger|greater|higher|capable|effective|improved|useful)\s+at\b/gi,
      "better at"
    );
  }

  if (/\bgood\s+at\b/i.test(original)) {
    repaired = repaired.replace(
      /\b(?:positive|healthy|sound|beneficial|constructive|favorable|helpful|powerful)\s+at\b/gi,
      "good at"
    );
  }

  if (/\bgood\s+(?:(?:general|face|overall|specific)\s+)?(?:witnesses?|memory|ability|evidence)\b/i.test(original)) {
    repaired = repaired.replace(
      /\b(?:positive|healthy|constructive|helpful|powerful|worthwhile)\s+((?:general|face|overall|specific)\s+)?(witnesses?|memory|ability|evidence)\b/gi,
      "good $1$2"
    );
  }

  if (/\bsimple\s+effect\b/i.test(original)) {
    repaired = repaired.replace(
      /\b(?:easy|basic|uncomplicated)\s+effect\b/gi,
      "simple effect"
    );
  }

  if (/\bstrong\b[^.!?]{0,45}\bweak\s+at\s+recognizing\s+faces\b/i.test(original)) {
    repaired = repaired.replace(
      /\b(?:powerful|convincing|persuasive|robust|solid)\b([^.!?]{0,45}\bweak\s+at\s+recognizing\s+faces\b)/gi,
      "strong$1"
    );
  }

  const replacements: Array<[RegExp, RegExp, string]> = [
    [/\bstrong\s+eye\s+contact\b/i, /\b(?!strong\b)[A-Za-z-]+\s+eye\s+contact\b/gi, "strong eye contact"],
    [/\beffective\s+communication\b/i, /\b(?:potent|powerful|robust)\s+communication\b/gi, "effective communication"],
    [/\bclear\s+responsibilities\b/i, /\b(?!clear\b)[A-Za-z-]+\s+responsibilities\b/gi, "clear responsibilities"],
    [/\bclear\s+expectations\b/i, /\b(?!clear\b)[A-Za-z-]+\s+expectations\b/gi, "clear expectations"],
    [/\brelationships\s+and\s+groups\b/i, /\b(?!relationships\b)[A-Za-z-]+\s+and\s+groups\b/gi, "relationships and groups"],
    [/\bdifferent\s+perspectives\b/i, /\b(?:varied|different|contrasting)\s+(?:angles?|views?|viewpoints?|outlooks?|lenses?|positions?|stances?)\b/gi, "different perspectives"],
    [/\bcommunication\s+between\b/i, /\b(?:connection|interaction|dialogue|conversation|exchange)\s+between\b/gi, "communication between"],
    [/\bteacher\s+(?:gave|asked|told|reminded)\b/i, /\b(?:tutor|mentor|guide)\s+(gave|asked|told|reminded)\b/gi, "teacher $1"],
    [/\bmake\b[^.!?]{0,40}\bclear\b/i, /\bmake\b([^.!?]{0,40})\b(?:direct|plain|readable)\b/gi, "make$1clear"],
    [/\boriginal\s+wording\b/i, /\b(?:source|first)\s+wording\b/gi, "original wording"],
    [/\bstrong\s+argument\b/i, /\bcompelling\s+case\b/gi, "strong argument"],
    [/\bhelped\s+[A-Za-z]+ing\b/i, /\b(?:assisted|aided|facilitated)\s+([A-Za-z]+ing)\b/gi, "helped $1"],
    [/\bmade\s+(?:a\s+)?decision\b/i, /\b(?:created|built|produced)\s+(?:a\s+)?decision\b/gi, "made a decision"],
    [/\btook\s+responsibility\b/i, /\b(?:received|accepted|obtained|carried)\s+responsibility\b/gi, "took responsibility"],
  ];

  for (const [originalPattern, candidatePattern, replacement] of replacements) {
    if (originalPattern.test(original)) repaired = repaired.replace(candidatePattern, replacement);
  }

  if (/\bask(?:s|ed)?\s+for\s+help\b/i.test(original)) {
    repaired = repaired.replace(
      /\b(ask|asks|asked)\s+for\s+(?:guide|guidance|aid|assist|assistance)\b/gi,
      (_match, verb: string) => `${verb} for help`
    );
  }

  if (/\bexplain\s+(?:the|a|an)\b/i.test(original)) {
    repaired = repaired.replace(
      /\bmake\s+clear\s+(the|a|an)\b/gi,
      (_match, article: string) => `explain ${article}`
    );
  }

  return repaired;
}

export function repairArticleAgreement(text: string): string {
  return text.replace(/\b(a|an)\s+([A-Za-z][A-Za-z'-]*)\b/gi, (_match, article: string, word: string) => {
    const expected = startsWithVowelSound(word) ? "an" : "a";
    const adjustedArticle =
      article === article.toUpperCase()
        ? expected.toUpperCase()
        : article[0] === article[0].toUpperCase()
          ? expected[0].toUpperCase() + expected.slice(1)
          : expected;
    return adjustedArticle + " " + word;
  });
}

export function validateRewriteQuality(
  original: string,
  candidate: string,
  protectedSpans: ProtectedSpan[] = [],
  options: RewriteQualityOptions = {}
): RewriteQualityValidation {
  const protection = validateProtectedContent(
    original,
    candidate,
    protectedSpans.length > 0 ? protectedSpans : extractProtectedSpans(original)
  );
  if (!protection.safe) {
    return {
      safe: false,
      reason: protection.reason,
      issues: [],
    };
  }

  if (!options.allowStructuralRepair && countSentences(original) !== countSentences(candidate)) {
    return {
      safe: false,
      reason: "The rewrite changed the sentence count.",
      issues: [{ id: "sentence-count", detail: "Sentence count must remain unchanged." }],
    };
  }

  // High-severity hard grammar defects are never acceptable in a generated
  // candidate, even when the source already contained a defect of the same
  // category. This is the fail-closed boundary that prevents an error from
  // merely moving from “They is ready” to “the symptoms is serious.”
  const candidateHighGrammarIssue = grammarSafetyIssues(candidate).find((issue) => issue.severity === "high");
  if (candidateHighGrammarIssue) {
    return {
      safe: false,
      reason: candidateHighGrammarIssue.detail,
      issues: [{ id: candidateHighGrammarIssue.id, detail: candidateHighGrammarIssue.detail }],
    };
  }

  const originalIssues = analyzeRewriteQuality(original, original, protectedSpans);
  const candidateIssues = analyzeRewriteQuality(original, candidate, protectedSpans);
  // A malformed source may already contain one issue of a class, but that
  // does not give a candidate permission to add a second issue of the same
  // class. Compare bounded counts rather than only issue IDs, so “They is
  // ready” cannot become “They are ready and the symptoms is serious” and
  // pass merely because both defects are agreement issues.
  const originalIssueCounts = new Map<string, number>();
  for (const issue of originalIssues) {
    originalIssueCounts.set(issue.id, (originalIssueCounts.get(issue.id) ?? 0) + 1);
  }
  const candidateIssueUsage = new Map<string, number>();
  const newIssues = candidateIssues.filter((issue) => {
    const used = candidateIssueUsage.get(issue.id) ?? 0;
    candidateIssueUsage.set(issue.id, used + 1);
    if (used < (originalIssueCounts.get(issue.id) ?? 0)) return false;
    if (options.allowStructuralRepair && issue.id === "sentence-shape-drift") return false;
    if (options.allowStructuralRepair && issue.id === "point-of-view-drift" && hasImpliedFirstPersonFragment(original)) return false;
    return true;
  });

  if (options.allowStructuralRepair && looksLikeUnrepairedFragmentaryProse(candidate)) {
    newIssues.push({
      id: "unrepaired-fragment",
      detail: "The repaired paragraph still contains a note-like sentence fragment.",
    });
  }

  if (newIssues.length > 0) {
    return {
      safe: false,
      reason: newIssues[0].detail,
      issues: newIssues,
    };
  }

  return { safe: true, issues: [] };
}

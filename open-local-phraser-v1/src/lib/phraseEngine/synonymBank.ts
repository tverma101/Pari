import type { CandidateOption, CandidateSource } from "@/lib/ranking/types";
import type { PartOfSpeech, RewriteMode, RiskLevel } from "@/lib/types";

import { guessPartOfSpeech } from "@/lib/nlp/posTagger";
import { matchCase, normalizeWord } from "@/lib/nlp/tokenizer";
import { DEEP_SYNONYM_CLUSTERS } from "./deepSynonymClusters";

interface SynonymOptionDefinition {
  replacement: string;
  label?: string;
  risk?: RiskLevel;
  modePreference?: RewriteMode[];
  source?: CandidateSource;
}

export interface SynonymBankEntry {
  key: string;
  pos: PartOfSpeech;
  source: CandidateSource;
  options: SynonymOptionDefinition[];
}

const STRENGTH_RISK_WORDS: Record<string, RiskLevel> = {
  proves: "high",
  guarantees: "high",
  always: "high",
  never: "high",
  damages: "high",
  destroys: "high",
  controls: "high",
  demand: "high",
  demands: "high",
  impacts: "medium",
  want: "medium",
  wants: "medium",
  suggests: "medium",
  changes: "medium",
};

const DEEP_SYNONYM_MIN_OPTIONS = 40;
const DEEP_SYNONYM_MAX_OPTIONS = 40;

function buildDeepSynonymMap(): Record<string, string[]> {
  const map: Record<string, string[]> = {};

  for (const cluster of DEEP_SYNONYM_CLUSTERS) {
    const terms = cluster.map((term) => term.trim()).filter(Boolean);

    for (const term of terms) {
      const key = normalizeWord(term);
      const bucket = map[key] ?? [];
      const seen = new Set(bucket.map((item) => normalizeWord(item)));

      for (const candidate of terms) {
        const candidateKey = normalizeWord(candidate);
        if (candidateKey === key || seen.has(candidateKey)) continue;
        seen.add(candidateKey);
        bucket.push(candidate);
      }

      map[key] = bucket;
    }
  }

  return map;
}

const DEEP_SYNONYM_MAP = buildDeepSynonymMap();

export const LEGACY_SYNONYM_MAP: Record<string, string[]> = {
  use: ["utilize", "employ", "apply", "leverage"],
  used: ["utilized", "employed", "applied", "leveraged"],
  make: ["create", "produce", "construct", "build"],
  makes: ["creates", "produces", "constructs", "builds"],
  get: ["obtain", "acquire", "receive", "secure"],
  gets: ["obtains", "acquires", "receives", "secures"],
  show: ["demonstrate", "display", "reveal", "exhibit"],
  shows: ["demonstrates", "displays", "reveals", "exhibits"],
  help: ["assist", "aid", "support", "facilitate"],
  helps: ["assists", "aids", "supports", "facilitates"],
  improve: ["enhance", "refine", "upgrade", "better"],
  improves: ["enhances", "refines", "upgrades", "betters"],
  start: ["begin", "commence", "initiate", "launch"],
  think: ["consider", "believe", "reckon", "suppose"],
  want: ["desire", "wish", "seek", "aim for"],
  say: ["state", "mention", "remark", "express"],
  see: ["observe", "notice", "view", "perceive"],
  know: ["understand", "recognize", "comprehend", "realize"],
  find: ["discover", "locate", "identify", "uncover"],
  give: ["provide", "offer", "supply", "deliver"],
  take: ["grab", "seize", "obtain", "accept"],
  need: ["require", "necessitate", "demand", "want"],
  ask: ["inquire", "request", "question", "query"],
  work: ["function", "operate", "perform", "labor"],
  write: ["compose", "draft", "pen", "author"],
  read: ["peruse", "study", "examine", "review"],
  learn: ["study", "grasp", "master", "absorb"],
  understand: ["comprehend", "grasp", "perceive", "fathom"],
  change: ["modify", "alter", "transform", "adjust"],
  clear: ["plain", "direct", "easy to follow", "readable"],
  fast: ["quick", "swift", "rapid", "speedy"],
  slow: ["sluggish", "leisurely", "gradual", "unhurried"],
  easy: ["simple", "effortless", "straightforward", "uncomplicated"],
  hard: ["difficult", "tough", "challenging", "demanding"],
  important: ["crucial", "vital", "essential", "significant"],
  difficult: ["challenging", "tough", "demanding", "arduous"],
  smart: ["intelligent", "clever", "bright", "sharp"],
  new: ["fresh", "novel", "recent", "modern"],
  nice: ["pleasant", "agreeable", "delightful", "lovely"],
  great: ["excellent", "wonderful", "outstanding", "superb"],
  many: ["numerous", "various", "countless", "multiple"],
  few: ["several", "a handful of", "limited", "scarce"],
  interesting: ["fascinating", "engaging", "intriguing", "compelling"],
  amazing: ["incredible", "astonishing", "remarkable", "extraordinary"],
  popular: ["well-known", "favored", "trending", "renowned"],
  modern: ["contemporary", "current", "up-to-date", "recent"],
  simple: ["easy", "straightforward", "basic", "uncomplicated"],
  powerful: ["strong", "potent", "mighty", "robust"],
  effective: ["efficient", "productive", "successful", "potent"],
  efficient: ["effective", "productive", "streamlined", "optimal"],
  quick: ["fast", "swift", "rapid", "speedy"],
  best: ["finest", "top", "premier", "leading"],
  way: ["method", "approach", "manner", "means"],
  thing: ["item", "object", "matter", "element"],
  people: ["individuals", "persons", "folks", "humans"],
  person: ["individual", "human", "being", "participant", "someone", "one person"],
  time: ["period", "moment", "duration", "era"],
  place: ["location", "spot", "site", "venue"],
  idea: ["concept", "notion", "thought", "theory"],
  problem: ["issue", "challenge", "difficulty", "obstacle"],
  solution: ["resolution", "answer", "remedy", "fix"],
  goal: ["objective", "aim", "target", "purpose"],
  result: ["outcome", "consequence", "effect", "product"],
  company: ["business", "firm", "organization", "enterprise"],
  student: ["pupil", "learner", "scholar", "trainee"],
  teacher: ["instructor", "educator", "tutor", "mentor"],
  text: ["passage", "content", "writing", "material"],
  word: ["term", "expression", "phrase", "vocable"],
  sentence: ["statement", "phrase", "clause", "expression"],
  language: ["tongue", "dialect", "vernacular", "speech"],
  tool: ["instrument", "device", "utility", "implement"],
  local: ["on-device", "offline", "machine-local", "resident"],
  writing: ["wording", "prose", "draft", "copy"],
  quickly: ["rapidly", "swiftly", "speedily", "promptly"],
  often: ["frequently", "regularly", "commonly", "repeatedly"],
  always: ["consistently", "perpetually", "invariably", "constantly"],
  never: ["not ever", "at no time", "by no means", "under no circumstances"],
  also: ["additionally", "furthermore", "moreover", "as well"],
  however: ["nevertheless", "nonetheless", "yet", "though"],
  because: ["since", "as", "given that", "due to the fact that", "for the reason that", "considering that", "seeing that", "inasmuch as", "now that", "on the grounds that"],
  but: ["yet", "however", "though", "although"],
  and: ["plus", "as well as", "along with", "in addition to", "together with", "not to mention", "as well"],
  so: ["therefore", "thus", "hence", "consequently"],
  while: ["whereas", "although", "during", "as", "even as", "at the same time that"],
  when: ["once", "whenever", "as soon as", "at the time that", "if", "while"],
  where: ["in which", "wherever", "at the place where", "in the place that", "on which"],
  include: ["contain", "involve", "cover", "feature", "take in", "encompass", "account for"],
  different: ["distinct", "separate", "unlike", "not the same", "varied", "divergent", "contrasting"],
  high: ["strong", "elevated", "substantial", "considerable", "marked", "above-average"],
  low: ["reduced", "limited", "modest", "lower", "minimal", "below-average"],
  good: ["positive", "healthy", "sound", "beneficial", "constructive", "favorable"],
  bad: ["poor", "harmful", "negative", "weak", "unhelpful", "damaging"],
  "self-esteem": ["self-worth", "self-respect", "confidence", "self-regard", "personal confidence", "sense of worth", "self-confidence", "self-belief", "self-assurance", "self-image", "self-value", "self-appreciation", "self-acceptance", "sense of self", "inner confidence", "personal esteem"],
  esteem: ["respect", "regard", "admiration", "appreciation", "value"],
  narcissism: ["self-absorption", "egotism", "self-importance", "vanity", "self-centeredness", "egoism", "self-obsession", "grandiosity", "excessive self-focus", "self-admiration", "self-preoccupation", "ego-centeredness", "inflated self-view", "self-regard", "personal vanity", "self-infatuation"],
  narcissistic: ["self-absorbed", "egotistical", "self-important", "vain", "self-centered", "ego-driven", "self-obsessed", "grandiose", "overly self-focused", "self-admiring", "ego-centered", "self-preoccupied", "self-involved", "self-regarding", "attention-seeking", "self-infatuated"],
  entitlement: ["privilege", "deservingness", "special treatment", "automatic right", "claim", "expectation", "sense of being owed", "assumed privilege", "presumed right", "special claim", "unearned expectation", "right to receive", "demand for preference", "expectation of favor", "sense of due", "claim to advantage"],
  superiority: ["dominance", "greater status", "higher standing", "advantage", "supremacy", "upper hand", "greater importance", "higher rank", "elevated status", "higher position", "better standing", "perceived advantage", "greater worth", "higher value", "greater authority", "dominant position"],
  sense: ["feeling", "perception", "impression", "awareness", "belief", "notion"],
  status: ["standing", "rank", "position", "prestige", "social standing", "reputation"],
  relationships: ["connections", "bonds", "relations", "personal ties", "social links", "partnerships"],
  relationship: ["connection", "bond", "relation", "personal tie", "association", "partnership"],
  schools: ["classrooms", "campuses", "educational settings", "learning spaces", "institutions"],
  workplaces: ["offices", "jobsites", "work settings", "professional settings", "organizations"],
  workplace: ["office", "jobsite", "work setting", "professional setting", "organization"],
  caring: ["kind", "considerate", "compassionate", "supportive", "thoughtful", "empathetic"],
  working: ["collaborating", "cooperating", "operating", "functioning", "laboring", "teaming"],
  others: ["other people", "peers", "those around them", "the people nearby", "other individuals"],
  themselves: ["personally", "on their own", "for themselves", "as individuals", "in their own view"],
  yourself: ["oneself", "you personally", "your own self", "yourself as a person"],
  view: ["see", "regard", "consider", "perceive", "interpret", "understand"],
  similar: ["alike", "comparable", "related", "much the same", "parallel", "close"],
  increases: ["raises", "boosts", "heightens", "expands", "strengthens", "amplifies", "drives up"],
  increase: ["raise", "boost", "heighten", "expand", "strengthen", "amplify", "drive up"],
  includes: ["contains", "involves", "covers", "features", "takes in", "encompasses", "accounts for"],
  needed: ["required", "necessary", "essential", "called for", "important", "useful"],
  useful: ["helpful", "valuable", "practical", "beneficial", "worthwhile", "effective"],
  believe: ["think", "feel", "hold", "consider", "assume", "trust"],
  believes: ["thinks", "feels", "holds", "considers", "assumes", "trusts"],
  may: ["might", "could", "can", "is likely to", "has the potential to"],
  perhaps: ["maybe", "possibly", "potentially", "it may be that", "conceivably"],
  someone: ["a person", "an individual", "somebody", "one person", "another person"],
  along: ["beside", "together with", "with", "next to", "alongside"],
  original: ["initial", "first", "source", "unchanged", "starting"],
  compact: ["tight", "condensed", "space-saving", "streamlined", "compressed"],
  laggy: ["slow", "sluggish", "delayed", "unresponsive", "choppy"],
  better: ["stronger", "improved", "more useful", "clearer", "more effective"],
};

const CURATED_BANK: Record<string, SynonymBankEntry> = {
  show: {
    key: "show",
    pos: "verb",
    source: "static-bank",
    options: [
      { replacement: "display", label: "natural", risk: "low", modePreference: ["fluency"] },
      { replacement: "present", label: "clear", risk: "low" },
      { replacement: "indicate", label: "formal", risk: "low", modePreference: ["formal"] },
      { replacement: "make clear", label: "plain", risk: "low", modePreference: ["simple"] },
      { replacement: "reveal", label: "context", risk: "medium" },
      { replacement: "demonstrate", label: "formal", risk: "medium", modePreference: ["formal"] },
    ],
  },
  slow: {
    key: "slow",
    pos: "adjective",
    source: "static-bank",
    options: [
      { replacement: "sluggish", label: "natural", risk: "low", modePreference: ["fluency"] },
      { replacement: "delayed", label: "clear", risk: "low" },
      { replacement: "unresponsive", label: "interface", risk: "low" },
      { replacement: "laggy", label: "interface", risk: "medium", modePreference: ["simple"] },
      { replacement: "slow-moving", label: "natural", risk: "low" },
      { replacement: "leisurely", label: "tone shift", risk: "medium" },
      { replacement: "gradual", label: "process", risk: "medium" },
      { replacement: "unhurried", label: "tone shift", risk: "medium" },
    ],
  },
  useful: {
    key: "useful",
    pos: "adjective",
    source: "static-bank",
    options: [
      { replacement: "helpful", label: "natural", risk: "low", modePreference: ["fluency", "simple"] },
      { replacement: "valuable", label: "balanced", risk: "low" },
      { replacement: "practical", label: "clear", risk: "low" },
      { replacement: "worthwhile", label: "balanced", risk: "low" },
      { replacement: "effective", label: "results", risk: "low" },
      { replacement: "beneficial", label: "formal", risk: "medium", modePreference: ["formal"] },
    ],
  },
  improve: {
    key: "improve",
    pos: "verb",
    source: "static-bank",
    options: [
      { replacement: "boost", label: "natural", risk: "low", modePreference: ["fluency"] },
      { replacement: "increase", label: "clear", risk: "low" },
      { replacement: "enhance", label: "formal", risk: "low", modePreference: ["formal"] },
      { replacement: "strengthen", label: "balanced", risk: "low" },
      { replacement: "raise", label: "plain", risk: "low", modePreference: ["simple"] },
      { replacement: "refine", label: "quality", risk: "medium" },
      { replacement: "upgrade", label: "system", risk: "medium" },
      { replacement: "better", label: "awkward as verb", risk: "high" },
    ],
  },
  give: {
    key: "give",
    pos: "verb",
    source: "static-bank",
    options: [
      { replacement: "offer", label: "natural", risk: "low", modePreference: ["fluency"] },
      { replacement: "provide", label: "clear", risk: "low" },
      { replacement: "share", label: "soft", risk: "low" },
      { replacement: "supply", label: "formal", risk: "medium", modePreference: ["formal"] },
      { replacement: "present", label: "formal", risk: "medium" },
      { replacement: "deliver", label: "object-specific", risk: "medium" },
    ],
  },
  problem: {
    key: "problem",
    pos: "noun",
    source: "static-bank",
    options: [
      { replacement: "issue", label: "natural", risk: "low", modePreference: ["fluency"] },
      { replacement: "concern", label: "support", risk: "low" },
      { replacement: "difficulty", label: "balanced", risk: "low" },
      { replacement: "obstacle", label: "stronger", risk: "medium" },
      { replacement: "challenge", label: "softened", risk: "medium" },
    ],
  },
  quickly: {
    key: "quickly",
    pos: "adverb",
    source: "static-bank",
    options: [
      { replacement: "rapidly", label: "natural", risk: "low", modePreference: ["fluency"] },
      { replacement: "fast", label: "simple", risk: "low", modePreference: ["simple"] },
      { replacement: "swiftly", label: "formal", risk: "low", modePreference: ["formal"] },
      { replacement: "speedily", label: "formal", risk: "medium" },
      { replacement: "promptly", label: "response timing", risk: "medium" },
    ],
  },
  demonstrates: {
    key: "demonstrates",
    pos: "verb",
    source: "static-bank",
    options: [
      { replacement: "shows", label: "simple / natural", risk: "low", modePreference: ["simple"] },
      { replacement: "explains", label: "clear", risk: "low" },
      { replacement: "suggests", label: "softer claim", risk: "medium", modePreference: ["fluency"] },
      { replacement: "illustrates", label: "formal", risk: "low", modePreference: ["formal"] },
      { replacement: "proves", label: "stronger claim", risk: "high", modePreference: ["creative"] },
    ],
  },
  influences: {
    key: "influences",
    pos: "verb",
    source: "static-bank",
    options: [
      { replacement: "affects", label: "natural", risk: "low" },
      { replacement: "shapes", label: "softer", risk: "low" },
      { replacement: "changes", label: "simple", risk: "medium", modePreference: ["simple"] },
      { replacement: "impacts", label: "formal-ish", risk: "low", modePreference: ["formal"] },
      { replacement: "controls", label: "stronger claim", risk: "high" },
    ],
  },
  important: {
    key: "important",
    pos: "adjective",
    source: "static-bank",
    options: [
      { replacement: "key", label: "compact", risk: "low", modePreference: ["shorten"] },
      { replacement: "useful", label: "softer", risk: "low" },
      { replacement: "meaningful", label: "balanced", risk: "low" },
      { replacement: "essential", label: "stronger", risk: "medium", modePreference: ["formal"] },
    ],
  },
  difficult: {
    key: "difficult",
    pos: "adjective",
    source: "static-bank",
    options: [
      { replacement: "challenging", label: "natural", risk: "low", modePreference: ["fluency"] },
      { replacement: "hard", label: "simple", risk: "low", modePreference: ["simple"] },
      { replacement: "complex", label: "context", risk: "low" },
      { replacement: "demanding", label: "balanced", risk: "low" },
      { replacement: "tough", label: "casual", risk: "medium" },
      { replacement: "tricky", label: "casual", risk: "medium", modePreference: ["simple"] },
      { replacement: "arduous", label: "formal", risk: "medium", modePreference: ["formal"] },
      { replacement: "hard to understand", label: "plain", risk: "low", modePreference: ["simple"] },
    ],
  },
  good: {
    key: "good",
    pos: "adjective",
    source: "static-bank",
    options: [
      { replacement: "positive", label: "natural", risk: "low", modePreference: ["fluency", "simple"] },
      { replacement: "healthy", label: "context", risk: "low", modePreference: ["fluency"] },
      { replacement: "sound", label: "balanced", risk: "low", modePreference: ["formal"] },
      { replacement: "favorable", label: "formal", risk: "low", modePreference: ["formal"] },
      { replacement: "constructive", label: "clear", risk: "low" },
      { replacement: "beneficial", label: "useful", risk: "low" },
      { replacement: "helpful", label: "simple", risk: "low", modePreference: ["simple"] },
      { replacement: "worthwhile", label: "balanced", risk: "low" },
    ],
  },
  better: {
    key: "better",
    pos: "adjective",
    source: "static-bank",
    options: [
      { replacement: "clearer", label: "natural", risk: "low", modePreference: ["fluency", "simple"] },
      { replacement: "stronger", label: "natural", risk: "low" },
      { replacement: "greater", label: "comparative", risk: "low" },
      { replacement: "higher", label: "comparative", risk: "low" },
      { replacement: "more capable", label: "clear", risk: "low" },
      { replacement: "more effective", label: "clear", risk: "low" },
      { replacement: "superior", label: "formal", risk: "medium", modePreference: ["formal"] },
      { replacement: "improved", label: "changed state", risk: "medium" },
      { replacement: "more useful", label: "plain", risk: "low", modePreference: ["simple"] },
    ],
  },
  need: {
    key: "need",
    pos: "verb",
    source: "static-bank",
    options: [
      { replacement: "require", label: "natural", risk: "low", modePreference: ["fluency"] },
      { replacement: "seek", label: "context", risk: "low" },
      { replacement: "want", label: "softer", risk: "medium", modePreference: ["simple"] },
      { replacement: "call for", label: "phrase", risk: "low", modePreference: ["formal"] },
      { replacement: "depend on", label: "context", risk: "medium" },
      { replacement: "benefit from", label: "soft", risk: "medium", modePreference: ["fluency"] },
      { replacement: "necessitate", label: "formal", risk: "medium", modePreference: ["formal"] },
      { replacement: "demand", label: "stronger claim", risk: "high" },
    ],
  },
  view: {
    key: "view",
    pos: "noun",
    source: "static-bank",
    options: [
      { replacement: "perspective", label: "natural", risk: "low", modePreference: ["fluency"] },
      { replacement: "outlook", label: "natural", risk: "low" },
      { replacement: "perception", label: "formal", risk: "low", modePreference: ["formal"] },
      { replacement: "opinion", label: "simple", risk: "low", modePreference: ["simple"] },
      { replacement: "viewpoint", label: "balanced", risk: "low" },
      { replacement: "self-view", label: "context", risk: "low" },
      { replacement: "understanding", label: "careful", risk: "low" },
      { replacement: "stance", label: "formal", risk: "medium", modePreference: ["formal"] },
    ],
  },
  narcissistic: {
    key: "narcissistic",
    pos: "adjective",
    source: "static-bank",
    options: [
      { replacement: "self-absorbed", label: "natural", risk: "low", modePreference: ["fluency"] },
      { replacement: "self-centered", label: "natural", risk: "low" },
      { replacement: "self-important", label: "clear", risk: "low" },
      { replacement: "egotistical", label: "formal", risk: "low", modePreference: ["formal"] },
      { replacement: "ego-driven", label: "balanced", risk: "low" },
      { replacement: "grandiose", label: "specific", risk: "medium" },
      { replacement: "overly self-focused", label: "plain", risk: "low", modePreference: ["simple"] },
      { replacement: "attention-seeking", label: "related", risk: "medium" },
    ],
  },
  entitlement: {
    key: "entitlement",
    pos: "noun",
    source: "static-bank",
    options: [
      { replacement: "a sense of being owed", label: "natural", risk: "low", modePreference: ["fluency"] },
      { replacement: "assumed privilege", label: "clear", risk: "low" },
      { replacement: "special treatment", label: "plain", risk: "low", modePreference: ["simple"] },
      { replacement: "presumed right", label: "formal", risk: "low", modePreference: ["formal"] },
      { replacement: "special claim", label: "clear", risk: "low" },
      { replacement: "unearned expectation", label: "precise", risk: "low" },
      { replacement: "deservingness", label: "related", risk: "medium" },
      { replacement: "privilege", label: "shorter", risk: "low", modePreference: ["shorten"] },
    ],
  },
  superiority: {
    key: "superiority",
    pos: "noun",
    source: "static-bank",
    options: [
      { replacement: "feeling of being better", label: "natural", risk: "low", modePreference: ["fluency", "simple"] },
      { replacement: "higher status", label: "clear", risk: "low" },
      { replacement: "higher standing", label: "formal", risk: "low", modePreference: ["formal"] },
      { replacement: "dominance", label: "stronger", risk: "medium" },
      { replacement: "greater importance", label: "clear", risk: "low" },
      { replacement: "perceived advantage", label: "careful", risk: "low" },
      { replacement: "supremacy", label: "stronger", risk: "high" },
      { replacement: "upper hand", label: "idiom", risk: "medium" },
    ],
  },
  because: {
    key: "because",
    pos: "phrase",
    source: "static-bank",
    options: [
      { replacement: "since", label: "natural", risk: "low", modePreference: ["fluency", "simple"] },
      { replacement: "as", label: "compact", risk: "low", modePreference: ["shorten"] },
      { replacement: "given that", label: "clear", risk: "low" },
      { replacement: "seeing that", label: "natural", risk: "low", modePreference: ["fluency"] },
      { replacement: "considering that", label: "formal", risk: "low", modePreference: ["formal"] },
      { replacement: "due to the fact that", label: "formal", risk: "medium", modePreference: ["formal"] },
      { replacement: "for the reason that", label: "precise", risk: "medium" },
      { replacement: "on the grounds that", label: "formal", risk: "medium", modePreference: ["formal"] },
    ],
  },
  people: {
    key: "people",
    pos: "noun",
    source: "static-bank",
    options: [
      { replacement: "individuals", label: "formal", risk: "low", modePreference: ["formal"] },
      { replacement: "folks", label: "casual", risk: "medium", modePreference: ["creative"] },
      { replacement: "persons", label: "formal", risk: "low" },
    ],
  },
  person: {
    key: "person",
    pos: "noun",
    source: "static-bank",
    options: [
      { replacement: "human", label: "natural", risk: "low", modePreference: ["fluency", "simple"] },
      { replacement: "individual", label: "formal", risk: "low", modePreference: ["formal"] },
      { replacement: "human being", label: "natural", risk: "low" },
      { replacement: "person involved", label: "clear", risk: "low" },
      { replacement: "participant", label: "context", risk: "medium" },
      { replacement: "member", label: "context", risk: "medium" },
      { replacement: "someone", label: "pronoun", risk: "medium" },
      { replacement: "one person", label: "phrase", risk: "medium" },
    ],
  },
  "highlights the importance of": {
    key: "highlights the importance of",
    pos: "phrase",
    source: "phrase-bank",
    options: [
      { replacement: "shows why", label: "simple", risk: "low", modePreference: ["simple", "shorten"] },
      { replacement: "makes clear why", label: "direct", risk: "low" },
      { replacement: "points to why", label: "natural", risk: "low" },
      { replacement: "helps explain why", label: "soft", risk: "low", modePreference: ["fluency"] },
    ],
  },
  "in order to": {
    key: "in order to",
    pos: "phrase",
    source: "phrase-bank",
    options: [
      { replacement: "to", label: "shorter", risk: "low", modePreference: ["shorten", "simple"] },
      { replacement: "so it can", label: "softer", risk: "medium", modePreference: ["fluency"] },
    ],
  },
  "easier to read": {
    key: "easier to read",
    pos: "phrase",
    source: "phrase-bank",
    options: [
      { replacement: "more readable", label: "natural", risk: "low", modePreference: ["standard", "fluency", "shorten"] },
      { replacement: "easier to understand", label: "clear", risk: "low", modePreference: ["simple"] },
      { replacement: "clearer to read", label: "natural", risk: "low" },
      { replacement: "simpler to read", label: "simple", risk: "low", modePreference: ["simple"] },
      { replacement: "clearer for readers", label: "audience", risk: "low" },
      { replacement: "more accessible", label: "formal", risk: "low", modePreference: ["formal"] },
    ],
  },
  "as a result": {
    key: "as a result",
    pos: "phrase",
    source: "phrase-bank",
    options: [
      { replacement: "so", label: "shorter", risk: "low", modePreference: ["shorten", "simple"] },
      { replacement: "therefore", label: "formal", risk: "low", modePreference: ["formal"] },
      { replacement: "because of that", label: "natural", risk: "low" },
    ],
  },
  "as well as": {
    key: "as well as",
    pos: "phrase",
    source: "phrase-bank",
    options: [
      { replacement: "and", label: "shorter", risk: "low", modePreference: ["shorten", "simple"] },
      { replacement: "along with", label: "natural", risk: "low" },
      { replacement: "together with", label: "balanced", risk: "low" },
      { replacement: "in addition to", label: "formal", risk: "low", modePreference: ["formal"] },
      { replacement: "plus", label: "casual", risk: "medium", modePreference: ["creative"] },
    ],
  },
  "different from": {
    key: "different from",
    pos: "phrase",
    source: "phrase-bank",
    options: [
      { replacement: "distinct from", label: "formal", risk: "low", modePreference: ["formal"] },
      { replacement: "separate from", label: "clear", risk: "low" },
      { replacement: "not the same as", label: "simple", risk: "low", modePreference: ["simple"] },
      { replacement: "unlike", label: "shorter", risk: "low", modePreference: ["shorten"] },
      { replacement: "contrasts with", label: "formal", risk: "low" },
      { replacement: "differs from", label: "compact", risk: "low" },
      { replacement: "is not identical to", label: "precise", risk: "low" },
      { replacement: "varies from", label: "soft", risk: "medium" },
      { replacement: "stands apart from", label: "expressive", risk: "low", modePreference: ["creative"] },
      { replacement: "is unlike", label: "simple", risk: "low" },
      { replacement: "is separate from", label: "clear", risk: "low" },
      { replacement: "is distinct from", label: "formal", risk: "low", modePreference: ["formal"] },
      { replacement: "does not equal", label: "direct", risk: "low", modePreference: ["simple"] },
      { replacement: "should be separated from", label: "careful", risk: "medium" },
      { replacement: "is meaningfully different from", label: "precise", risk: "low" },
    ],
  },
  "high self-esteem": {
    key: "high self-esteem",
    pos: "phrase",
    source: "phrase-bank",
    options: [
      { replacement: "healthy self-esteem", label: "natural", risk: "low", modePreference: ["fluency"] },
      { replacement: "strong self-worth", label: "natural", risk: "low" },
      { replacement: "strong self-esteem", label: "clear", risk: "low" },
      { replacement: "positive self-regard", label: "formal", risk: "low", modePreference: ["formal"] },
      { replacement: "healthy confidence", label: "simple", risk: "low", modePreference: ["simple"] },
      { replacement: "solid self-confidence", label: "natural", risk: "low" },
      { replacement: "secure self-worth", label: "precise", risk: "low" },
      { replacement: "positive self-image", label: "related", risk: "medium" },
      { replacement: "stable self-respect", label: "balanced", risk: "low" },
      { replacement: "healthy self-respect", label: "balanced", risk: "low" },
      { replacement: "high confidence", label: "shorter", risk: "low", modePreference: ["shorten"] },
      { replacement: "robust self-esteem", label: "formal", risk: "low", modePreference: ["formal"] },
      { replacement: "well-grounded confidence", label: "precise", risk: "low" },
      { replacement: "strong sense of self-worth", label: "phrase", risk: "low" },
      { replacement: "healthy sense of self-worth", label: "phrase", risk: "low" },
      { replacement: "positive sense of self", label: "phrase", risk: "low" },
    ],
  },
  "self-esteem": {
    key: "self-esteem",
    pos: "noun",
    source: "static-bank",
    options: [
      { replacement: "self-worth", label: "natural", risk: "low" },
      { replacement: "confidence", label: "shorter", risk: "low", modePreference: ["shorten", "simple"] },
      { replacement: "self-respect", label: "balanced", risk: "low" },
      { replacement: "self-regard", label: "formal", risk: "low", modePreference: ["formal"] },
      { replacement: "sense of worth", label: "phrase", risk: "low" },
      { replacement: "self-confidence", label: "natural", risk: "low" },
      { replacement: "self-belief", label: "direct", risk: "low" },
      { replacement: "self-assurance", label: "formal", risk: "low", modePreference: ["formal"] },
      { replacement: "personal confidence", label: "phrase", risk: "low" },
      { replacement: "inner confidence", label: "phrase", risk: "low" },
      { replacement: "self-image", label: "related", risk: "medium" },
      { replacement: "self-value", label: "clear", risk: "low" },
      { replacement: "self-appreciation", label: "positive", risk: "low" },
      { replacement: "self-acceptance", label: "positive", risk: "low" },
      { replacement: "sense of self", label: "phrase", risk: "low" },
      { replacement: "personal esteem", label: "formal", risk: "low" },
    ],
  },
  "narcissism includes": {
    key: "narcissism includes",
    pos: "phrase",
    source: "phrase-bank",
    options: [
      { replacement: "narcissism involves", label: "natural", risk: "low", modePreference: ["fluency"] },
      { replacement: "narcissism contains", label: "direct", risk: "low" },
      { replacement: "narcissism is marked by", label: "formal", risk: "low", modePreference: ["formal"] },
      { replacement: "narcissism can involve", label: "careful", risk: "low" },
      { replacement: "narcissism often includes", label: "soft", risk: "low" },
      { replacement: "narcissism commonly involves", label: "formal", risk: "low" },
      { replacement: "narcissism is associated with", label: "careful", risk: "low" },
      { replacement: "narcissism features", label: "shorter", risk: "low", modePreference: ["shorten"] },
      { replacement: "narcissism brings in", label: "plain", risk: "medium", modePreference: ["simple"] },
      { replacement: "narcissism covers", label: "plain", risk: "medium" },
      { replacement: "narcissism centers on", label: "specific", risk: "medium" },
      { replacement: "narcissism may include", label: "soft", risk: "low" },
      { replacement: "narcissism tends to involve", label: "careful", risk: "low" },
      { replacement: "narcissism is characterized by", label: "formal", risk: "low", modePreference: ["formal"] },
      { replacement: "narcissism can be linked with", label: "careful", risk: "low" },
    ],
  },
  "sense of superiority": {
    key: "sense of superiority",
    pos: "phrase",
    source: "phrase-bank",
    options: [
      { replacement: "feeling of being better", label: "simple", risk: "low", modePreference: ["simple"] },
      { replacement: "belief in being superior", label: "clear", risk: "low" },
      { replacement: "superiority complex", label: "compact", risk: "medium", modePreference: ["shorten"] },
      { replacement: "feeling of higher status", label: "natural", risk: "low" },
      { replacement: "belief in greater importance", label: "formal", risk: "low", modePreference: ["formal"] },
    ],
  },
  "sense of superiority and entitlement": {
    key: "sense of superiority and entitlement",
    pos: "phrase",
    source: "phrase-bank",
    options: [
      { replacement: "feeling of being superior and owed special treatment", label: "clear", risk: "low" },
      { replacement: "belief in being above others and deserving special treatment", label: "clear", risk: "low" },
      { replacement: "superiority and entitlement", label: "shorter", risk: "low", modePreference: ["shorten"] },
      { replacement: "feeling of higher status and special privilege", label: "natural", risk: "low" },
      { replacement: "belief in greater importance and deserved privilege", label: "formal", risk: "low", modePreference: ["formal"] },
      { replacement: "superior self-view and entitlement", label: "compact", risk: "low" },
      { replacement: "inflated status and special claim", label: "compact", risk: "medium" },
      { replacement: "belief in being better and owed more", label: "simple", risk: "low", modePreference: ["simple"] },
      { replacement: "superiority complex and entitlement", label: "clinical", risk: "medium" },
      { replacement: "sense of being above others and owed preference", label: "clear", risk: "low" },
      { replacement: "belief in higher standing and special treatment", label: "formal", risk: "low" },
      { replacement: "feeling of superiority plus entitlement", label: "direct", risk: "low" },
      { replacement: "high-status self-view and assumed privilege", label: "precise", risk: "medium" },
      { replacement: "belief in greater worth and special rights", label: "clear", risk: "low" },
      { replacement: "view of oneself as superior and especially deserving", label: "plain", risk: "low" },
    ],
  },
  "narcissistic traits": {
    key: "narcissistic traits",
    pos: "phrase",
    source: "phrase-bank",
    options: [
      { replacement: "narcissistic characteristics", label: "formal", risk: "low", modePreference: ["formal"] },
      { replacement: "narcissistic tendencies", label: "natural", risk: "low" },
      { replacement: "self-centered traits", label: "simple", risk: "low", modePreference: ["simple"] },
      { replacement: "ego-driven traits", label: "compact", risk: "low" },
      { replacement: "self-important tendencies", label: "natural", risk: "low" },
      { replacement: "grandiose traits", label: "specific", risk: "low" },
      { replacement: "self-absorbed patterns", label: "natural", risk: "low" },
      { replacement: "attention-seeking tendencies", label: "related", risk: "medium" },
      { replacement: "ego-centered characteristics", label: "formal", risk: "low" },
      { replacement: "self-focused traits", label: "plain", risk: "low" },
      { replacement: "self-involved tendencies", label: "natural", risk: "low" },
      { replacement: "narcissistic patterns", label: "compact", risk: "low" },
      { replacement: "traits tied to narcissism", label: "careful", risk: "low" },
      { replacement: "grandiose tendencies", label: "specific", risk: "low" },
      { replacement: "self-centered characteristics", label: "clear", risk: "low" },
    ],
  },
  "believe they are better than others": {
    key: "believe they are better than others",
    pos: "phrase",
    source: "phrase-bank",
    options: [
      { replacement: "think they are superior to others", label: "clear", risk: "low" },
      { replacement: "believe they outrank other people", label: "formal", risk: "low" },
      { replacement: "feel superior to others", label: "shorter", risk: "low", modePreference: ["shorten"] },
      { replacement: "see themselves as better than others", label: "natural", risk: "low" },
      { replacement: "view themselves as superior", label: "compact", risk: "low" },
      { replacement: "believe they matter more than others", label: "simple", risk: "low", modePreference: ["simple"] },
      { replacement: "assume they are above other people", label: "clear", risk: "low" },
      { replacement: "consider themselves superior to others", label: "formal", risk: "low", modePreference: ["formal"] },
      { replacement: "think they deserve higher status", label: "related", risk: "medium" },
      { replacement: "see themselves as above others", label: "natural", risk: "low" },
      { replacement: "hold an inflated view of themselves", label: "careful", risk: "low" },
      { replacement: "believe they are more important than others", label: "clear", risk: "low" },
      { replacement: "feel they are above everyone else", label: "strong", risk: "medium" },
      { replacement: "rank themselves above other people", label: "direct", risk: "low" },
      { replacement: "treat themselves as superior to others", label: "behavior", risk: "medium" },
    ],
  },
  "work with": {
    key: "work with",
    pos: "phrase",
    source: "phrase-bank",
    options: [
      { replacement: "collaborate with", label: "formal", risk: "low", modePreference: ["formal"] },
      { replacement: "cooperate with", label: "clear", risk: "low" },
      { replacement: "team with", label: "shorter", risk: "low", modePreference: ["shorten"] },
      { replacement: "interact with", label: "neutral", risk: "low" },
    ],
  },
};

function inferRisk(value: string): RiskLevel {
  return STRENGTH_RISK_WORDS[normalizeWord(value)] ?? "low";
}

function inferModePreference(original: string, replacement: string): RewriteMode[] | undefined {
  const preferences: RewriteMode[] = [];

  if (replacement.length <= original.length) {
    preferences.push("shorten");
  }

  if (replacement.split(/\s+/).length <= Math.max(1, original.split(/\s+/).length)) {
    preferences.push("simple");
  }

  if (replacement.length >= original.length + 4) {
    preferences.push("formal");
  }

  if (Math.abs(replacement.length - original.length) <= 6) {
    preferences.push("fluency");
  }

  return preferences.length > 0 ? preferences : undefined;
}

function inferLabel(original: string, replacement: string): string | undefined {
  if (replacement.length <= original.length - 2) return "shorter";
  if (replacement.length >= original.length + 5) return "more formal";
  return undefined;
}

function createEntry(key: string, replacements: string[]): SynonymBankEntry {
  const pos = guessPartOfSpeech(key);
  const source: CandidateSource = key.includes(" ") ? "phrase-bank" : "static-bank";

  return {
    key,
    pos,
    source,
    options: replacements.map((replacement) => ({
      replacement,
      label: inferLabel(key, replacement),
      risk: inferRisk(replacement),
    })),
  };
}

function buildStructuredBank(): Record<string, SynonymBankEntry> {
  const base = Object.fromEntries(
    Object.entries(LEGACY_SYNONYM_MAP).map(([key, replacements]) => [key, createEntry(key, replacements)])
  );

  return {
    ...base,
    ...CURATED_BANK,
  };
}

export const SYNONYM_BANK: Record<string, SynonymBankEntry> = buildStructuredBank();

function expandSynonymOptions(entry: SynonymBankEntry): SynonymOptionDefinition[] {
  const normalizedOriginal = normalizeWord(entry.key);
  const expanded: SynonymOptionDefinition[] = [...entry.options];
  const seen = new Set(expanded.map((option) => normalizeWord(option.replacement)));
  const seeds = [entry.key, ...entry.options.map((option) => option.replacement)];

  for (const seed of seeds) {
    const candidates = DEEP_SYNONYM_MAP[normalizeWord(seed)] ?? [];

    for (const replacement of candidates) {
      const key = normalizeWord(replacement);
      if (!key || key === normalizedOriginal || seen.has(key)) continue;

      seen.add(key);
      expanded.push({
        replacement,
        label: inferLabel(entry.key, replacement) ?? "expanded",
        risk: inferRisk(replacement),
        modePreference: inferModePreference(entry.key, replacement),
        source: "deep-bank",
      });

      if (expanded.length >= DEEP_SYNONYM_MAX_OPTIONS) {
        return expanded;
      }
    }

    if (expanded.length >= DEEP_SYNONYM_MIN_OPTIONS) {
      break;
    }
  }

  return expanded;
}

export const PHRASE_KEYS = Object.keys(SYNONYM_BANK)
  .filter((key) => key.includes(" "))
  .sort((left, right) => right.split(/\s+/).length - left.split(/\s+/).length);

export function getSynonymEntry(term: string): SynonymBankEntry | undefined {
  return SYNONYM_BANK[normalizeWord(term)];
}

export function buildCandidateOptions(
  originalText: string,
  entry: SynonymBankEntry
): CandidateOption[] {
  const seen = new Set<string>();
  const options = expandSynonymOptions(entry);

  return options.flatMap((option, index) => {
    const replacement = matchCase(originalText, option.replacement);
    const key = normalizeWord(replacement);

    if (key === normalizeWord(originalText) || seen.has(key)) {
      return [];
    }

    seen.add(key);

    return [
      {
        id: `${normalizeWord(entry.key)}-${index}-${key}`,
        original: originalText,
        replacement,
        label: option.label,
        source: option.source ?? entry.source,
        risk: option.risk ?? "low",
        partOfSpeech: entry.pos,
        modePreference: option.modePreference,
      },
    ];
  });
}

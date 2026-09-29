import type { TokenAlternative, AlternativeType } from "../core/types.js";

/**
 * Core synonym bank with manually curated alternatives.
 * This is the V1 bank extracted and expanded.
 */

export interface SynonymEntry {
  word: string;
  pos: string;
  alternatives: Array<{
    text: string;
    type: AlternativeType;
    contextSafe: boolean;
    notes: string;
  }>;
}

// Core synonym bank
const SYNONYM_BANK: Map<string, SynonymEntry> = new Map();

function addEntry(word: string, pos: string, alternatives: SynonymEntry["alternatives"]): void {
  SYNONYM_BANK.set(word.toLowerCase(), { word, pos, alternatives });
}

// === Verb entries ===
addEntry("demonstrates", "verb", [
  { text: "shows", type: "true_synonym", contextSafe: true, notes: "preferred replacement" },
  { text: "suggests", type: "near_synonym", contextSafe: true, notes: "slightly weaker" },
  { text: "points to", type: "phrase_rewrite", contextSafe: true, notes: "more conversational" },
  { text: "makes clear", type: "phrase_rewrite", contextSafe: true, notes: "more direct" },
  { text: "helps show", type: "phrase_rewrite", contextSafe: true, notes: "softer" },
  { text: "reveals", type: "near_synonym", contextSafe: true, notes: "slightly stronger" },
  { text: "indicates", type: "near_synonym", contextSafe: true, notes: "slightly formal" },
  { text: "supports the idea", type: "phrase_rewrite", contextSafe: true, notes: "academic" },
  { text: "helps explain", type: "phrase_rewrite", contextSafe: true, notes: "conversational" },
  { text: "is a sign of", type: "phrase_rewrite", contextSafe: true, notes: "informal" },
  { text: "tells us", type: "phrase_rewrite", contextSafe: true, notes: "very informal" },
  { text: "reflects", type: "near_synonym", contextSafe: true, notes: "slightly formal" },
  { text: "proves", type: "near_synonym", contextSafe: false, notes: "too strong — use with caution" },
  { text: "confirms", type: "near_synonym", contextSafe: false, notes: "too strong — use with caution" },
  { text: "highlights", type: "near_synonym", contextSafe: true, notes: "good middle ground" },
  { text: "brings out", type: "phrase_rewrite", contextSafe: true, notes: "informal" },
  { text: "draws attention to", type: "phrase_rewrite", contextSafe: true, notes: "slightly formal" },
  { text: "hints that", type: "phrase_rewrite", contextSafe: true, notes: "softer meaning" },
  { text: "points out", type: "phrase_rewrite", contextSafe: true, notes: "conversational" },
  { text: "is evidence that", type: "phrase_rewrite", contextSafe: true, notes: "slightly formal" },
  { text: "signals", type: "near_synonym", contextSafe: true, notes: "good alternative" },
  { text: "shows us", type: "phrase_rewrite", contextSafe: true, notes: "conversational" },
  { text: "makes it clear that", type: "phrase_rewrite", contextSafe: true, notes: "more direct" },
  { text: "proves that", type: "near_synonym", contextSafe: false, notes: "too strong" },
  { text: "is proof that", type: "phrase_rewrite", contextSafe: false, notes: "too strong" },
  { text: "gives evidence that", type: "phrase_rewrite", contextSafe: true, notes: "fair" },
  { text: "lends support to", type: "phrase_rewrite", contextSafe: true, notes: "formal" },
  { text: "attests to", type: "near_synonym", contextSafe: true, notes: "formal" },
  { text: "bears out", type: "phrase_rewrite", contextSafe: true, notes: "somewhat idiomatic" },
  { text: "speaks to", type: "phrase_rewrite", contextSafe: true, notes: "conversational" },
]);

addEntry("show", "verb", [
  { text: "demonstrate", type: "true_synonym", contextSafe: true, notes: "more formal" },
  { text: "reveal", type: "true_synonym", contextSafe: true, notes: "slightly stronger" },
  { text: "indicate", type: "true_synonym", contextSafe: true, notes: "slightly formal" },
  { text: "suggest", type: "true_synonym", contextSafe: true, notes: "softer" },
  { text: "prove", type: "near_synonym", contextSafe: false, notes: "too strong" },
  { text: "make clear", type: "phrase_rewrite", contextSafe: true, notes: "direct" },
  { text: "point to", type: "phrase_rewrite", contextSafe: true, notes: "more specific" },
  { text: "highlight", type: "true_synonym", contextSafe: true, notes: "good" },
  { text: "illustrate", type: "true_synonym", contextSafe: true, notes: "slightly formal" },
  { text: "display", type: "true_synonym", contextSafe: true, notes: "neutral" },
  { text: "exhibit", type: "near_synonym", contextSafe: true, notes: "formal" },
  { text: "manifest", type: "near_synonym", contextSafe: false, notes: "too formal" },
  { text: "evidence", type: "near_synonym", contextSafe: true, notes: "slightly formal" },
  { text: "attest", type: "near_synonym", contextSafe: true, notes: "formal" },
  { text: "bear out", type: "phrase_rewrite", contextSafe: true, notes: "idiomatic" },
  { text: "give evidence of", type: "phrase_rewrite", contextSafe: true, notes: "formal" },
  { text: "be evidence of", type: "phrase_rewrite", contextSafe: true, notes: "neutral" },
  { text: "testify to", type: "phrase_rewrite", contextSafe: true, notes: "formal" },
  { text: "be a sign of", type: "phrase_rewrite", contextSafe: true, notes: "informal" },
  { text: "denote", type: "near_synonym", contextSafe: true, notes: "formal" },
  { text: "convey", type: "near_synonym", contextSafe: true, notes: "slightly formal" },
  { text: "communicate", type: "near_synonym", contextSafe: true, notes: "neutral" },
  { text: "express", type: "near_synonym", contextSafe: true, notes: "good" },
  { text: "demonstrate clearly", type: "phrase_rewrite", contextSafe: true, notes: "emphatic" },
  { text: "put on display", type: "phrase_rewrite", contextSafe: true, notes: "figurative" },
  { text: "bring to light", type: "phrase_rewrite", contextSafe: true, notes: "figurative" },
  { text: "cast light on", type: "phrase_rewrite", contextSafe: true, notes: "figurative" },
  { text: "shed light on", type: "phrase_rewrite", contextSafe: true, notes: "common idiom" },
  { text: "set forth", type: "phrase_rewrite", contextSafe: true, notes: "formal/archaic" },
]);

addEntry("significant", "adjective", [
  { text: "important", type: "true_synonym", contextSafe: true, notes: "preferred replacement" },
  { text: "clear", type: "near_synonym", contextSafe: true, notes: "describes clarity, not importance" },
  { text: "major", type: "true_synonym", contextSafe: true, notes: "good" },
  { text: "meaningful", type: "true_synonym", contextSafe: true, notes: "good" },
  { text: "big", type: "simpler_word", contextSafe: true, notes: "informal but clear" },
  { text: "noticeable", type: "true_synonym", contextSafe: true, notes: "good" },
  { text: "real", type: "near_synonym", contextSafe: true, notes: "slightly different meaning" },
  { text: "strong", type: "near_synonym", contextSafe: true, notes: "slightly different" },
  { text: "key", type: "true_synonym", contextSafe: true, notes: "good" },
  { text: "notable", type: "true_synonym", contextSafe: true, notes: "good" },
  { text: "substantial", type: "near_synonym", contextSafe: true, notes: "slightly formal" },
  { text: "considerable", type: "near_synonym", contextSafe: true, notes: "slightly formal" },
  { text: "serious", type: "near_synonym", contextSafe: true, notes: "context dependent" },
  { text: "sizable", type: "near_synonym", contextSafe: true, notes: "size connotation" },
  { text: "marked", type: "true_synonym", contextSafe: true, notes: "good" },
  { text: "pronounced", type: "true_synonym", contextSafe: true, notes: "slightly formal" },
  { text: "striking", type: "near_synonym", contextSafe: true, notes: "stronger" },
  { text: "impressive", type: "near_synonym", contextSafe: true, notes: "positive connotation" },
  { text: "critical", type: "near_synonym", contextSafe: true, notes: "urgent connotation" },
  { text: "vital", type: "near_synonym", contextSafe: true, notes: "strong" },
  { text: "essential", type: "near_synonym", contextSafe: true, notes: "strong" },
  { text: "necessary", type: "near_synonym", contextSafe: true, notes: "different nuance" },
  { text: "valuable", type: "near_synonym", contextSafe: true, notes: "positive" },
  { text: "useful", type: "near_synonym", contextSafe: true, notes: "weaker" },
  { text: "helpful", type: "near_synonym", contextSafe: true, notes: "weaker" },
  { text: "worthwhile", type: "near_synonym", contextSafe: true, notes: "slightly different" },
  { text: "influential", type: "near_synonym", contextSafe: true, notes: "causal connotation" },
  { text: "powerful", type: "near_synonym", contextSafe: true, notes: "strong" },
  { text: "heavy", type: "near_synonym", contextSafe: false, notes: "informal/colloquial" },
  { text: "weighty", type: "near_synonym", contextSafe: true, notes: "slightly formal" },
]);

addEntry("individuals", "noun", [
  { text: "people", type: "true_synonym", contextSafe: true, notes: "preferred replacement" },
  { text: "students", type: "contextual_replacement", contextSafe: true, notes: "if in educational context" },
  { text: "others", type: "near_synonym", contextSafe: true, notes: "different nuance" },
  { text: "someone", type: "near_synonym", contextSafe: true, notes: "singular only" },
  { text: "a person", type: "phrase_rewrite", contextSafe: true, notes: "singular" },
  { text: "folks", type: "simpler_word", contextSafe: true, notes: "informal but fine" },
  { text: "men and women", type: "phrase_rewrite", contextSafe: true, notes: "binary language" },
  { text: "human beings", type: "near_synonym", contextSafe: true, notes: "more specific" },
  { text: "humans", type: "near_synonym", contextSafe: true, notes: "more specific" },
  { text: "persons", type: "true_synonym", contextSafe: true, notes: "formal" },
  { text: "citizens", type: "contextual_replacement", contextSafe: true, notes: "civic context" },
  { text: "members", type: "contextual_replacement", contextSafe: true, notes: "if group context" },
  { text: "participants", type: "contextual_replacement", contextSafe: true, notes: "if study/activity" },
  { text: "everyone", type: "near_synonym", contextSafe: true, notes: "collective" },
  { text: "everybody", type: "near_synonym", contextSafe: true, notes: "collective/informal" },
  { text: "anyone", type: "near_synonym", contextSafe: true, notes: "indefinite" },
  { text: "people in general", type: "phrase_rewrite", contextSafe: true, notes: "explicit" },
  { text: "society", type: "near_synonym", contextSafe: true, notes: "broader" },
  { text: "the public", type: "phrase_rewrite", contextSafe: true, notes: "civic" },
  { text: "audience", type: "contextual_replacement", contextSafe: true, notes: "if communication context" },
  { text: "readers", type: "contextual_replacement", contextSafe: true, notes: "if writing context" },
  { text: "viewers", type: "contextual_replacement", contextSafe: true, notes: "if media context" },
  { text: "users", type: "contextual_replacement", contextSafe: true, notes: "if tech context" },
  { text: "peers", type: "contextual_replacement", contextSafe: true, notes: "if social context" },
  { text: "population", type: "near_synonym", contextSafe: true, notes: "statistical context" },
  { text: "group", type: "near_synonym", contextSafe: true, notes: "different nuance" },
  { text: "community", type: "near_synonym", contextSafe: true, notes: "positive connotation" },
  { text: "crowd", type: "near_synonym", contextSafe: true, notes: "less formal" },
  { text: "the average person", type: "phrase_rewrite", contextSafe: true, notes: "generalizing" },
  { text: "one", type: "simpler_word", contextSafe: true, notes: "formal/generic" },
]);

addEntry("communication", "noun", [
  { text: "communication", type: "true_synonym", contextSafe: true, notes: "preserve term" },
  { text: "the way people communicate", type: "phrase_rewrite", contextSafe: true, notes: "more explicit" },
  { text: "talking", type: "simpler_word", contextSafe: true, notes: "more specific" },
  { text: "how people talk", type: "phrase_rewrite", contextSafe: true, notes: "informal" },
  { text: "conversation", type: "near_synonym", contextSafe: true, notes: "two-way" },
  { text: "dialogue", type: "near_synonym", contextSafe: true, notes: "slightly formal" },
  { text: "discussion", type: "near_synonym", contextSafe: true, notes: "focused" },
  { text: "interaction", type: "near_synonym", contextSafe: true, notes: "broader" },
  { text: "exchange", type: "near_synonym", contextSafe: true, notes: "good" },
  { text: "sharing ideas", type: "phrase_rewrite", contextSafe: true, notes: "more specific" },
  { text: "sharing information", type: "phrase_rewrite", contextSafe: true, notes: "neutral" },
  { text: "exchanging thoughts", type: "phrase_rewrite", contextSafe: true, notes: "more specific" },
  { text: "correspondence", type: "near_synonym", contextSafe: true, notes: "written" },
  { text: "contact", type: "near_synonym", contextSafe: true, notes: "broader" },
  { text: "connection", type: "near_synonym", contextSafe: true, notes: "relational" },
  { text: "speaking", type: "simpler_word", contextSafe: true, notes: "verbal only" },
  { text: "writing", type: "simpler_word", contextSafe: true, notes: "written only" },
  { text: "messaging", type: "simpler_word", contextSafe: true, notes: "informal" },
  { text: "engagement", type: "near_synonym", contextSafe: true, notes: "business language" },
  { text: "back and forth", type: "phrase_rewrite", contextSafe: true, notes: "informal" },
  { text: "expression", type: "near_synonym", contextSafe: true, notes: "broader" },
  { text: "language", type: "near_synonym", contextSafe: true, notes: "tool-focused" },
  { text: "transmission", type: "near_synonym", contextSafe: true, notes: "technical" },
  { text: "dissemination", type: "near_synonym", contextSafe: true, notes: "formal" },
  { text: "two-way communication", type: "phrase_rewrite", contextSafe: true, notes: "more specific" },
  { text: "open communication", type: "phrase_rewrite", contextSafe: true, notes: "qualitative" },
  { text: "honest communication", type: "phrase_rewrite", contextSafe: true, notes: "qualitative" },
  { text: "communication skills", type: "phrase_rewrite", contextSafe: true, notes: "skill-focused" },
  { text: "the act of communicating", type: "phrase_rewrite", contextSafe: true, notes: "explicit" },
  { text: "interpersonal communication", type: "phrase_rewrite", contextSafe: true, notes: "academic — preserve" },
]);

// === Common adjectives ===
addEntry("important", "adjective", [
  { text: "important", type: "true_synonym", contextSafe: true, notes: "keep as is" },
  { text: "key", type: "true_synonym", contextSafe: true, notes: "good alternative" },
  { text: "main", type: "true_synonym", contextSafe: true, notes: "clear" },
  { text: "central", type: "true_synonym", contextSafe: true, notes: "slightly formal" },
  { text: "major", type: "true_synonym", contextSafe: true, notes: "good" },
  { text: "big", type: "simpler_word", contextSafe: true, notes: "informal" },
  { text: "essential", type: "near_synonym", contextSafe: true, notes: "stronger" },
  { text: "necessary", type: "near_synonym", contextSafe: true, notes: "slightly different" },
  { text: "vital", type: "near_synonym", contextSafe: true, notes: "stronger" },
  { text: "critical", type: "near_synonym", contextSafe: true, notes: "stronger" },
  { text: "crucial", type: "near_synonym", contextSafe: true, notes: "stronger" },
  { text: "meaningful", type: "true_synonym", contextSafe: true, notes: "good" },
  { text: "valuable", type: "true_synonym", contextSafe: true, notes: "positive" },
  { text: "significant", type: "true_synonym", contextSafe: true, notes: "the word we're avoiding" },
  { text: "noteworthy", type: "true_synonym", contextSafe: true, notes: "slightly formal" },
  { text: "substantial", type: "near_synonym", contextSafe: true, notes: "formal" },
  { text: "paramount", type: "near_synonym", contextSafe: false, notes: "too formal" },
  { text: "primary", type: "true_synonym", contextSafe: true, notes: "good" },
  { text: "relevant", type: "near_synonym", contextSafe: true, notes: "slightly different" },
  { text: "salient", type: "near_synonym", contextSafe: false, notes: "too formal" },
  { text: "pressing", type: "near_synonym", contextSafe: true, notes: "urgent" },
  { text: "urgent", type: "near_synonym", contextSafe: true, notes: "time-sensitive" },
  { text: "momentous", type: "near_synonym", contextSafe: false, notes: "too strong" },
  { text: "consequential", type: "near_synonym", contextSafe: false, notes: "too formal" },
  { text: "weighty", type: "near_synonym", contextSafe: true, notes: "slightly formal" },
  { text: "grave", type: "near_synonym", contextSafe: false, notes: "too serious" },
  { text: "of consequence", type: "phrase_rewrite", contextSafe: true, notes: "slightly formal" },
  { text: "of great importance", type: "phrase_rewrite", contextSafe: true, notes: "emphatic" },
  { text: "high-priority", type: "near_synonym", contextSafe: true, notes: "task focused" },
  { text: "foremost", type: "near_synonym", contextSafe: true, notes: "rank focused" },
]);

addEntry("better", "adjective", [
  { text: "better", type: "true_synonym", contextSafe: true, notes: "keep" },
  { text: "improved", type: "true_synonym", contextSafe: true, notes: "more specific" },
  { text: "stronger", type: "near_synonym", contextSafe: true, notes: "slightly different" },
  { text: "clearer", type: "near_synonym", contextSafe: true, notes: "clarity focused" },
  { text: "more effective", type: "phrase_rewrite", contextSafe: true, notes: "more specific" },
  { text: "more useful", type: "phrase_rewrite", contextSafe: true, notes: "utility focused" },
  { text: "more helpful", type: "phrase_rewrite", contextSafe: true, notes: "utility focused" },
  { text: "greater", type: "near_synonym", contextSafe: true, notes: "slightly formal" },
  { text: "superior", type: "near_synonym", contextSafe: true, notes: "strong" },
  { text: "higher-quality", type: "phrase_rewrite", contextSafe: true, notes: "specific" },
  { text: "of higher quality", type: "phrase_rewrite", contextSafe: true, notes: "clear" },
  { text: "more desirable", type: "phrase_rewrite", contextSafe: true, notes: "formal" },
  { text: "more beneficial", type: "phrase_rewrite", contextSafe: true, notes: "benefit focused" },
  { text: "more advantageous", type: "phrase_rewrite", contextSafe: true, notes: "formal" },
  { text: "improving", type: "near_synonym", contextSafe: true, notes: "process focused" },
  { text: "an improvement", type: "phrase_rewrite", contextSafe: true, notes: "different structure" },
  { text: "nicer", type: "simpler_word", contextSafe: true, notes: "informal" },
  { text: "easier", type: "near_synonym", contextSafe: true, notes: "different meaning" },
  { text: "simpler", type: "near_synonym", contextSafe: true, notes: "different meaning" },
  { text: "finer", type: "near_synonym", contextSafe: true, notes: "slightly formal" },
  { text: "enhanced", type: "near_synonym", contextSafe: true, notes: "slightly formal" },
  { text: "upgraded", type: "near_synonym", contextSafe: true, notes: "tech/product focused" },
  { text: "more advanced", type: "phrase_rewrite", contextSafe: true, notes: "tech focused" },
  { text: "more developed", type: "phrase_rewrite", contextSafe: true, notes: "growth focused" },
  { text: "more refined", type: "phrase_rewrite", contextSafe: true, notes: "polish focused" },
  { text: "more suitable", type: "phrase_rewrite", contextSafe: true, notes: "fit focused" },
  { text: "more appropriate", type: "phrase_rewrite", contextSafe: true, notes: "fit focused" },
  { text: "an improvement over", type: "phrase_rewrite", contextSafe: true, notes: "explicit" },
  { text: "a step up from", type: "phrase_rewrite", contextSafe: true, notes: "informal idiom" },
  { text: "preferable", type: "near_synonym", contextSafe: true, notes: "formal" },
]);

// === Common nouns ===
addEntry("role", "noun", [
  { text: "role", type: "true_synonym", contextSafe: true, notes: "preserve" },
  { text: "part", type: "true_synonym", contextSafe: true, notes: "good alternative" },
  { text: "function", type: "true_synonym", contextSafe: true, notes: "neutral" },
  { text: "place", type: "near_synonym", contextSafe: true, notes: "slightly different" },
  { text: "position", type: "true_synonym", contextSafe: true, notes: "good" },
  { text: "importance", type: "near_synonym", contextSafe: true, notes: "different nuance" },
  { text: "significance", type: "near_synonym", contextSafe: true, notes: "slightly formal" },
  { text: "contribution", type: "near_synonym", contextSafe: true, notes: "positive" },
  { text: "purpose", type: "near_synonym", contextSafe: true, notes: "slightly different" },
  { text: "job", type: "simpler_word", contextSafe: true, notes: "informal" },
  { text: "responsibility", type: "near_synonym", contextSafe: true, notes: "specific" },
  { text: "duty", type: "near_synonym", contextSafe: true, notes: "moral/obligation" },
  { text: "task", type: "near_synonym", contextSafe: true, notes: "more specific" },
  { text: "involvement", type: "near_synonym", contextSafe: true, notes: "participation focused" },
  { text: "impact", type: "near_synonym", contextSafe: true, notes: "effect focused" },
  { text: "effect", type: "near_synonym", contextSafe: true, notes: "different nuance" },
  { text: "way", type: "near_synonym", contextSafe: true, notes: "very general" },
  { text: "capacity", type: "near_synonym", contextSafe: true, notes: "formal" },
  { text: "character", type: "near_synonym", contextSafe: false, notes: "different meaning" },
  { text: "guise", type: "near_synonym", contextSafe: false, notes: "too formal/rare" },
  { text: "hat", type: "simpler_word", contextSafe: true, notes: "idiomatic ('wearing many hats')" },
  { text: "weight", type: "near_synonym", contextSafe: true, notes: "figurative" },
  { text: "standing", type: "near_synonym", contextSafe: true, notes: "formal" },
  { text: "status", type: "near_synonym", contextSafe: true, notes: "different meaning" },
  { text: "assignment", type: "near_synonym", contextSafe: true, notes: "task focused" },
  { text: "office", type: "near_synonym", contextSafe: false, notes: "different meaning" },
  { text: "post", type: "near_synonym", contextSafe: true, notes: "job focused" },
  { text: "calling", type: "near_synonym", contextSafe: true, notes: "vocation focused" },
  { text: "vocation", type: "near_synonym", contextSafe: false, notes: "formal" },
  { text: "niche", type: "near_synonym", contextSafe: true, notes: "specialized" },
]);

// === Function words get minimal entries ===
addEntry("the", "determiner", [
  { text: "the", type: "true_synonym", contextSafe: true, notes: "no useful alternative" },
]);
addEntry("and", "conjunction", [
  { text: "and", type: "true_synonym", contextSafe: true, notes: "no useful alternative" },
  { text: "as well as", type: "phrase_rewrite", contextSafe: true, notes: "more formal" },
  { text: "along with", type: "phrase_rewrite", contextSafe: true, notes: "slightly different" },
  { text: "plus", type: "simpler_word", contextSafe: true, notes: "informal" },
]);
addEntry("of", "preposition", [
  { text: "of", type: "true_synonym", contextSafe: true, notes: "no useful alternative" },
]);

// === Academic context words ===
addEntry("self-concept", "noun", [
  { text: "self-concept", type: "true_synonym", contextSafe: true, notes: "preserve technical term" },
  { text: "self-image", type: "near_synonym", contextSafe: true, notes: "slightly different" },
  { text: "how you see yourself", type: "phrase_rewrite", contextSafe: true, notes: "more accessible" },
  { text: "self-perception", type: "near_synonym", contextSafe: true, notes: "technical" },
  { text: "sense of self", type: "phrase_rewrite", contextSafe: true, notes: "good alternative" },
  { text: "identity", type: "near_synonym", contextSafe: true, notes: "broader" },
  { text: "understanding of yourself", type: "phrase_rewrite", contextSafe: true, notes: "conversational" },
  { text: "view of yourself", type: "phrase_rewrite", contextSafe: true, notes: "conversational" },
  { text: "idea of who you are", type: "phrase_rewrite", contextSafe: true, notes: "very accessible" },
  { text: "notion of self", type: "phrase_rewrite", contextSafe: true, notes: "slightly formal" },
  { text: "self-understanding", type: "near_synonym", contextSafe: true, notes: "technical" },
  { text: "awareness of oneself", type: "phrase_rewrite", contextSafe: true, notes: "formal" },
  { text: "personal identity", type: "near_synonym", contextSafe: true, notes: "broader" },
  { text: "who you are", type: "phrase_rewrite", contextSafe: true, notes: "very accessible" },
  { text: "your sense of who you are", type: "phrase_rewrite", contextSafe: true, notes: "conversational" },
]);

addEntry("social comparison", "noun", [
  { text: "social comparison", type: "true_synonym", contextSafe: true, notes: "preserve technical term" },
  { text: "comparing yourself to others", type: "phrase_rewrite", contextSafe: true, notes: "more accessible" },
  { text: "comparing with peers", type: "phrase_rewrite", contextSafe: true, notes: "good" },
  { text: "looking at others to judge yourself", type: "phrase_rewrite", contextSafe: true, notes: "explicit" },
  { text: "measuring yourself against others", type: "phrase_rewrite", contextSafe: true, notes: "clear" },
  { text: "judging yourself by others", type: "phrase_rewrite", contextSafe: true, notes: "conversational" },
  { text: "evaluating yourself relative to others", type: "phrase_rewrite", contextSafe: true, notes: "formal" },
  { text: "social comparison theory", type: "phrase_rewrite", contextSafe: true, notes: "technical — preserve" },
]);

/**
 * Get synonym entry for a word.
 */
export function getEntry(word: string): SynonymEntry | null {
  return SYNONYM_BANK.get(word.toLowerCase()) ?? null;
}

/**
 * Get alternatives for a word from the synonym bank.
 */
export function getBankAlternatives(word: string): TokenAlternative[] {
  const normalized = word.toLowerCase();
  const entry = SYNONYM_BANK.get(normalized);
  if (!entry) return [];

  const seen = new Set<string>();
  return entry.alternatives
    .filter((alt) => {
      const key = alt.text.toLowerCase();
      if (seen.has(key) || key === normalized) return false;
      seen.add(key);
      return true;
    })
    .map((alt) => ({
      text: alt.text,
      type: alt.type,
      contextSafe: alt.contextSafe,
      semanticScore: alt.type === "true_synonym" ? 0.9 : alt.type === "near_synonym" ? 0.7 : alt.type === "simpler_word" ? 0.6 : 0.5,
      naturalnessScore: alt.type === "true_synonym" ? 0.85 : alt.type === "simpler_word" ? 0.9 : 0.75,
      professorPenalty: alt.type === "not_recommended" ? 0.3 : 0.01,
      notes: alt.notes,
    }));
}

/**
 * Get all keys in the synonym bank (for lookup).
 */
export function getBankKeys(): string[] {
  return Array.from(SYNONYM_BANK.keys());
}

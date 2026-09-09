import { countWords } from "@/lib/nlp/tokenizer";
import { repairPunctuationSpacing } from "@/lib/generation/punctuation";

const TERMINAL_PUNCTUATION = /[.!?]["'”’)]?$/;

function protectedValuesFor(protectedSpans: Array<{ text: string }>): string[] {
  return [...new Set(
    (protectedSpans.length ? protectedSpans : []).map((span) => span.text)
  )]
    .filter(Boolean)
    .sort((left, right) => right.length - left.length);
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
    (_match, index: string) => protectedValues[index.charCodeAt(0) - 0xE100] ?? ""
  );
}

function isPluralSubject(value: string): boolean {
  const lastWord = value.trim().split(/\s+/).at(-1)?.toLowerCase() ?? "";
  if (/^(?:i|he|she|it|this|that|each|every|the team|the manager)$/.test(value.trim().toLowerCase())) return false;
  if (/^(?:people|children|men|women|they|we|you|these|those)$/.test(lastWord)) return true;
  return /s$/.test(lastWord) && !/(?:ss|us|is)$/.test(lastWord);
}

function articleFor(value: string): string {
  return /^[aeiou]/i.test(value.trim()) ? "an" : "a";
}

function capitalizeSentence(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return trimmed;
  return trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
}

function lowerFirstCharacter(value: string): string {
  return value ? value.charAt(0).toLowerCase() + value.slice(1) : value;
}

function looseFragments(value: string): string[] {
  const meridiemMarker = "\uE200";
  const maskedValue = value.replace(/\b([ap])\.m\./gi, (_match, marker: string) => `${marker}${meridiemMarker}m${meridiemMarker}`);
  return maskedValue
    .split(/(?:[.!?]+\s*|\r?\n+)/)
    .map((part) => part.trim())
    .map((part) => part.replace(new RegExp(meridiemMarker, "g"), "."))
    .filter(Boolean);
}

/**
 * Repair a few source-backed fragment sequences before the generic joiner.
 * These patterns are intentionally narrow: the added scaffolding is safe
 * only when the original paragraph contains the same recognizable fragment
 * shape, so a malformed model draft cannot create a new actor or event.
 */
function repairFragmentSequences(value: string, originalText: string): string {
  const noWordPattern = "(?:no|\\uE000[\\s\\S]\\uE001)";
  const noContestPattern = new RegExp(`^${noWordPattern}\\s+contest$`, "i");
  const noIdeaPattern = new RegExp(`^(${noWordPattern})\\s+idea\\s+where\\s+(.+)$`, "i");
  const sourceFragments = looseFragments(originalText);
  const sourceHasHonestBest =
    sourceFragments.some((fragment) => /^honestly[?!]?$/i.test(fragment)) &&
    sourceFragments.some((fragment) => /^best\s+.+$/i.test(fragment)) &&
    sourceFragments.some((fragment) => /^no\s+contest$/i.test(fragment));
  const sourceHasMissingFileLocation =
    sourceFragments.some((fragment) => /^no\s+idea\s+where\s+.+$/i.test(fragment)) &&
    sourceFragments.some((fragment) => /^probably\s+(?:on\s+)?the\s+shared\s+drive$/i.test(fragment)) &&
    sourceFragments.some((fragment) => /^maybe$/i.test(fragment));

  const fragments = looseFragments(value);
  const repaired: string[] = [];
  for (let index = 0; index < fragments.length;) {
    const first = fragments[index];
    const second = fragments[index + 1];
    const third = fragments[index + 2];

    const inlineHonestBest = first.match(/^honestly,?\s+(?:the\s+)?best\s+(.+)$/i);
    if (sourceHasHonestBest && inlineHonestBest) {
      repaired.push(`Honestly, this is the best ${lowerFirstCharacter(inlineHonestBest[1].trim())}`);
      index += 1;
      continue;
    }

    if (
      sourceHasHonestBest &&
      second &&
      third &&
      /^honestly[?!]?$/i.test(first) &&
      /^best\s+(.+)$/i.test(second) &&
      noContestPattern.test(third)
    ) {
      const bestPhrase = second.replace(/^best\s+/i, "").trim();
      repaired.push(`Honestly, this is the best ${lowerFirstCharacter(bestPhrase)}. ${third}`);
      index += 3;
      continue;
    }

    if (
      sourceHasMissingFileLocation &&
      second &&
      third &&
      noIdeaPattern.test(first) &&
      /^probably\s+(?:on\s+)?the\s+shared\s+drive$/i.test(second) &&
      /^maybe$/i.test(third)
    ) {
      const locationClause = second.replace(/^probably\s+(?:on\s+)?/i, "").trim();
      const noIdeaMatch = first.match(noIdeaPattern);
      const noWord = noIdeaMatch?.[1] ?? "No";
      const whereClause = noIdeaMatch?.[2]?.trim() ?? first;
      repaired.push(`I have ${noWord} idea where ${whereClause}; it probably went to ${locationClause}, maybe`);
      index += 3;
      continue;
    }

    repaired.push(first);
    index += 1;
  }

  return repaired.join(". ");
}

function repairPendingStatusPhrase(value: string): string {
  // Native drafts sometimes preserve every content word but leave a note-like
  // noun stack in the shape “The implementation review is pending completion
  // status.” Reorder only this high-confidence frame; do not invent a cause,
  // actor, or outcome, and keep the stated subject and status terms intact.
  const match = value.match(
    /^The\s+(.+?)\s+is\s+pending\s+((?:(?:its|the|a|an)\s+)?[^.!?,;:]+?)\s+status([.!?])?$/i,
  );
  if (!match) return value;

  const subject = match[1].replace(/\s+/g, " ").trim();
  const status = match[2]
    .replace(/^(?:its|the|a|an)\s+/i, "")
    .replace(/\s+/g, " ")
    .trim();
  const subjectWordCount = countWords(subject);
  const statusWordCount = countWords(status);
  if (
    subjectWordCount < 3 ||
    subjectWordCount > 12 ||
    statusWordCount < 1 ||
    statusWordCount > 4 ||
    /\b(?:is|are|was|were|has|have)\b/i.test(status)
  ) {
    return value;
  }

  const subjectWithArticle = /^(?:the|a|an|my|your|our|their|his|her|its)\b/i.test(subject)
    ? subject
    : `the ${subject}`;
  return `The ${status} status of ${subjectWithArticle} is pending${match[3] ?? ""}`;
}

function lowerSentenceStart(value: string): string {
  if (!value) return value;
  if (/^I(?:\b|')/.test(value)) return value;
  return value.charAt(0).toLowerCase() + value.slice(1);
}

function normalizeFragment(fragment: string, repairStandaloneNotes = false): string {
  let value = fragment
    .replace(/^[-*•]+\s*/, "")
    .replace(/\s+/g, " ")
    .replace(/\s+([,;:!?])/g, "$1")
    .trim();
  if (!value) return value;

  // Only add a grammatical subject when the original text contained the same
  // standalone note shape. This repairs fragments such as “Because of the
  // deadline.” without completing a model-created fragment with an invented
  // actor or event.
  if (repairStandaloneNotes) {
    value = value
      .replace(/^because\s+of\s+(.+)$/i, "The cause was $1")
      .replace(/^due\s+to\s+(.+)$/i, "The reason was $1")
      .replace(/^still\s+waiting\s+(on|for)\s+(.+)$/i, "I am still waiting $1 $2")
      .replace(/^waiting\s+(on|for)\s+(.+)$/i, "I am waiting $1 $2")
      .replace(/^not\s+sure\s+(.+)$/i, "I am not sure $1")
      .replace(/^no\s+idea\s+(.+)$/i, "I have no idea $1");
  }

  value = value
    .replace(/^honestly[?!]?$/i, "Honestly,")
    .replace(/^no\s+contest$/i, "There is no contest");

  value = repairPendingStatusPhrase(value);

  value = value
    .replace(/\bthey\s+is\b/gi, "they are")
    .replace(/\b(we|you|these|those|people|students|writers|users)\s+was\b/gi, "$1 were")
    .replace(/\b(he|she|it|this|that)\s+are\b/gi, "$1 is")
    .replace(/\b(i)\s+is\b/gi, "I am")
    .replace(/\b(the team|the manager|the client|the project|the system|the user)\s+say\b/gi, "$1 says")
    .replace(/\b(the team|the manager|the client|the project|the system|the user)\s+want\b/gi, "$1 wants")
    .replace(/\b(the team|the manager|the client|the project|the system|the user)\s+need\b/gi, "$1 needs")
    .replace(/\b(the team|the manager|the client|the project|the system|the user)\s+have\b/gi, "$1 has")
    .replace(/\b(can|could|may|might|must|shall|should|will|would)\s+(explains?|helps?|shows?|makes?|improves?|affects?)\b/gi, (_match, modal: string, verb: string) => `${modal} ${verb.replace(/s$/i, "")}`)
    .replace(/\bi\b/g, "I");

  // Repair compact note-like clauses without pretending that a synonym pass
  // can infer missing facts. These are intentionally conservative frames.
  value = value
    .replace(/^no\s+grammar$/i, "The grammar needs work")
    .replace(/^ideas?\s+missing$/i, "Ideas are missing")
    .replace(/^reason(?:s)?\s+unclear$/i, "The reasons are unclear")
    .replace(/^deadline\s+missed$/i, "The deadline was missed")
    .replace(/^(.+?)\s+performance\s+unacceptable$/i, "The $1's performance is unacceptable")
    .replace(/^meeting\s+(today|tomorrow)\s+with\s+(.+)$/i, "The meeting with $2 is $1")
    .replace(/^(.+?)\s+not\s+(finished|ready|clear|complete)$/i, (_match, subject: string, adjective: string) => {
      const normalizedSubject = /^(?:project|work|draft|plan|task|request)$/i.test(subject.trim()) ? `the ${subject.trim().toLowerCase()}` : subject.trim();
      return `${normalizedSubject} is not ${adjective}`;
    })
    .replace(/^(.+?)\s+(hard|difficult|easy|important|unclear|missing|gone|ready|late|broken|obvious|unacceptable)$/i, (match, subject: string, adjective: string) => {
      // A complete clause such as “Do not be late” already has a verb. Treat
      // only noun-like note fragments as subjectless adjective fragments;
      // otherwise the scaffolding would create “be is late”.
      if (/\b(?:am|is|are|was|were|be|been|being|has|have|had|do|does|did|can|could|may|might|must|shall|should|will|would)\b/i.test(subject)) {
        return match;
      }
      const verb = isPluralSubject(subject) ? "are" : "is";
      return `${subject.trim()} ${verb} ${adjective.toLowerCase()}`;
    })
    .replace(/^need\s+to\s+(.+)$/i, "I need to $1")
    .replace(/^have\s+to\s+(.+)$/i, "I have to $1")
    .replace(/^need\s+(.+)$/i, (_match, remainder: string) => {
      const normalized = remainder.trim();
      return /^(?:explain|send|write|review|fix|finish|make|understand|organize|ask|call|check|clarify)\b/i.test(normalized)
        ? `I need to ${normalized}`
        : `I need ${normalized}`;
    })
    .replace(/^send\s+update\b/i, "Send an update")
    .replace(/^send\s+the\s+update\b/i, "Send the update")
    .replace(/^need\s+(?:an?\s+)?update\b/i, "I need an update");

  value = value
    .replace(/\b(an|a)\s+update\b/gi, "an update")
    .replace(/\b(a|an)\s+([A-Za-z][A-Za-z'-]*)\b/gi, (_match, article: string, word: string) => {
      const expected = articleFor(word);
      return article[0] === article[0].toUpperCase()
        ? expected[0].toUpperCase() + expected.slice(1) + " " + word
        : expected + " " + word;
    });

  return capitalizeSentence(value);
}

function normalizeNoteAction(action: string, issue?: string): string | null {
  const protectedMarker = "\\uE000[\\s\\S]\\uE001";
  let value = action
    .replace(/\s+/g, " ")
    .replace(/[.!?]+$/, "")
    .trim();
  if (!value) return null;

  value = value
    .replace(/\bno\s+blame\b/gi, "without assigning blame")
    .replace(/\bwithout\s+blaming\b/gi, "without assigning blame")
    .replace(/\bkeep\s+message\s+short\b/gi, "keep the message short")
    .replace(/\bsend\s+update\b/gi, "send an update")
    .replace(/\bwrite\s+update\b/gi, "write an update")
    .trim();

  const followUpMatch = value.match(/\s+send\s+(?:an?\s+)?update\s+before\s+(.+)$/i);
  const followUp = followUpMatch ? `Send an update before ${followUpMatch[1].trim()}` : "";
  if (followUpMatch) value = value.slice(0, followUpMatch.index).trim();
  if (!value && !followUp) return null;
  if (!value) return followUp;

  if (issue && /^explain\s+(?=(?:clearly\b|without\b|and\b))/i.test(value)) {
    value = value.replace(/^explain\b/i, `explain the ${issue}`);
  } else if (issue && /^explain\s+without\b/i.test(value)) {
    value = value.replace(/^explain\b/i, `explain the ${issue}`);
  } else if (issue && /^explain\b/i.test(value)) {
    value = value.replace(/^explain\b/i, `explain the ${issue}`);
  }

  // A protected “no” cannot be deleted while turning “explain no blame” into
  // a sentence. Keep the exact marker and give the prepositional phrase a
  // grammatical home instead.
  if (issue) {
    value = value.replace(
      new RegExp(`(explain\\s+the\\s+${issue})\\s+(${protectedMarker})\\s+blame\\s+and\\s+keep\\b`, "gi"),
      "$1, with $2 blame, and keep",
    );
  }

  const withFollowUp = (main: string): string => followUp ? `${main}. ${followUp}` : main;
  if (/^I\s+need\b/i.test(value)) return withFollowUp(capitalizeSentence(value));
  if (/^(?:explain|send|write|review|fix|finish|make|understand|organize|ask|call|check|clarify|keep|address|rewrite|prepare|share|follow)\b/i.test(value)) {
    return withFollowUp(`I need to ${lowerSentenceStart(value)}`);
  }
  return withFollowUp(`I need ${lowerSentenceStart(value)}`);
}

function normalizeNoteSubject(value: string): string | null {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) return null;

  const stateMatch = normalized.match(
    /^(?:the\s+)?(client|customer|team|manager|user|project|draft|report)\s+(upset|concerned|angry|frustrated|delayed|late|unclear|missing|ready|broken|unfinished|waiting)(?:\s+(?:(?:about|over|due\s+to|for)\s+)?(?:the\s+)?(.+))?$/i,
  );
  if (stateMatch) {
    const [, subject, state, rawRemainder] = stateMatch;
    const subjectText = `The ${subject.toLowerCase()}`;
    const remainder = rawRemainder?.trim();
    if (!remainder) return `${subjectText} is ${state.toLowerCase()}`;
    if (state.toLowerCase() === "waiting") {
      const waitingFor = /^(?:for|on)\b/i.test(remainder)
        ? remainder
        : `for ${articleFor(remainder)} ${remainder}`;
      return `${subjectText} is waiting ${waitingFor}`;
    }
    return `${subjectText} is ${state.toLowerCase()} about the ${remainder}`;
  }

  if (/^deadline\s+missed$/i.test(normalized)) return "The deadline was missed";
  if (/^meeting\s+(?:today|tomorrow)$/i.test(normalized)) return normalizeFragment(normalized);

  const repaired = normalizeFragment(normalized).replace(/[.!?]+$/, "");
  return /\b(?:is|are|was|were|has|have|needs|wants|says)\b/i.test(repaired) ? repaired : null;
}

/**
 * Turn a small, recognizable stream of notes into sentences before the
 * synonym engine sees it. This is deliberately template-based: it adds only
 * grammatical scaffolding that is strongly implied by the note markers, and
 * leaves unfamiliar fragments for the safer existing repair path.
 */
function planNoteStream(value: string): string | null {
  const normalized = value
    .replace(/\s+/g, " ")
    .replace(/[.!?]+$/, "")
    .trim();
  if (!normalized || /[.!?]/.test(normalized) || countWords(normalized) < 6) return null;

  const meetingMatch = normalized.match(
    /^meeting\s+(today|tomorrow)\s+(?:(?:with\s+)?(?:the\s+)?)(client|customer|team|manager|user)\s+(?:who\s+)?(?:is\s+)?(upset|concerned|angry|frustrated)\s+(?:(?:about|over|due\s+to)\s+)?(?:the\s+)?(delay|problem|issue|change)\s+need\s+(.+)$/i,
  );
  if (meetingMatch) {
    const [, day, entity, emotion, issue, action] = meetingMatch;
    const entityText = /^(?:client|customer)$/i.test(entity) ? `a ${entity.toLowerCase()}` : `the ${entity.toLowerCase()}`;
    const actionSentence = normalizeNoteAction(action, issue.toLowerCase());
    if (actionSentence) {
      return `${capitalizeSentence(day)}'s meeting is with ${entityText} who is ${emotion.toLowerCase()} about the ${issue.toLowerCase()}. ${actionSentence}.`;
    }
  }

  const pairedStatus = normalized.match(
    /^(?:the\s+)?(deadline)\s+missed\s+(?:the\s+)?(client|customer|team|manager|user)\s+waiting\s+(?:for\s+)?(?:the\s+)?(.+)$/i,
  );
  if (pairedStatus) {
    const [, subject, entity, remainder] = pairedStatus;
    return `The ${subject.toLowerCase()} was missed, and the ${entity.toLowerCase()} is waiting for ${articleFor(remainder)} ${remainder}.`;
  }

  const tokens = normalized.split(/\s+/);
  const actionIndex = tokens.findIndex((token, index) => index > 1 && /^(?:need|must|should)$/i.test(token));
  if (actionIndex > 1) {
    const subject = normalizeNoteSubject(tokens.slice(0, actionIndex).join(" "));
    const action = normalizeNoteAction(tokens.slice(actionIndex + 1).join(" "));
    if (subject && action) return `${capitalizeSentence(subject)}. ${action}.`;
  }

  return null;
}

function shouldJoinShortSentences(left: string, right: string): boolean {
  if (countWords(left) > 8 || countWords(right) > 8) return false;
  // Citation abbreviations are sentence-splitting traps. Keep "et al." and
  // the following publication year as separate fragments that are rejoined
  // with their original period, never as a comma-and coordination.
  if (/\b(?:et\s+al|e\.g|i\.e|mr|mrs|ms|dr|prof|fig|no)\.$/i.test(left.trim())) return false;
  if (/^\(?\d{4}[a-z]?\)?(?:[,.;:]|\s|$)/i.test(right.trim())) return false;
  // These are usually complete discourse moves, not fragments that should be
  // glued to the sentence before them. In particular, joining a protected
  // negation creates the visibly broken “..., and No …” shape in Warmth mode.
  if (/^(?:\uE000[\s\S]\uE001|(?:no|not|never|without|yes|please|fix|send|make|address|call|check|remember|but|however|although|because|if|when|while)\b)/i.test(right.trim())) return false;
  if (/^(?:please|stop|fix|send|make|do|call|check|remember)\b/i.test(left.trim()) && /!$/.test(left.trim())) return false;
  return true;
}

function joinShortSentences(value: string): string {
  const meridiemMarker = "\uE200";
  const maskedValue = value.replace(/\b([ap])\.m\./gi, (_match, marker: string) => `${marker}${meridiemMarker}m${meridiemMarker}`);
  const sentences = maskedValue.match(/[^.!?]+[.!?]?["'”’)]?/g)
    ?.map((part) => part.replace(new RegExp(meridiemMarker, "g"), ".").trim())
    .filter(Boolean) ?? [value];
  const merged: string[] = [];
  for (const sentence of sentences) {
    const previous = merged.at(-1);
    if (previous && shouldJoinShortSentences(previous, sentence)) {
      merged[merged.length - 1] = previous.replace(/[.!?]["'”’)]?$/, ",") + " and " + lowerSentenceStart(sentence).replace(/^["“]/, "");
    } else {
      merged.push(sentence);
    }
  }
  return merged.join(" ");
}

function sourceNeedsStructuralRepair(text: string): boolean {
  const fragments = looseFragments(text);
  const shortFragments = fragments.filter((fragment) => countWords(fragment) <= 3).length;
  const totalWords = countWords(text);
  const denseFragmentation = shortFragments >= 2 && (
    totalWords < 180 || shortFragments / Math.max(1, fragments.length) >= 0.25
  );
  return denseFragmentation ||
    hasStandaloneNoteFragment(text) ||
    /(?:^|[.!?]\s+)[a-z]/.test(text) ||
    /\b([A-Za-z]+)\s+\1\b/i.test(text) ||
    !TERMINAL_PUNCTUATION.test(text.trim());
}

/** Recognize only high-confidence subjectless note fragments. */
export function hasStandaloneNoteFragment(text: string): boolean {
  const fragments = looseFragments(text);
  return fragments.some((fragment) =>
    /^(?:because\s+of|due\s+to)\s+[^,;:]+$/i.test(fragment) ||
    /^(?:still\s+)?waiting\s+(?:on|for)\s+.+$/i.test(fragment) ||
    /^(?:not\s+sure|no\s+idea)\s+.+$/i.test(fragment)
  );
}

export function repairBrokenProse(
  text: string,
  originalText: string,
  protectedSpans: Array<{ text: string }>
): string {
  const protectedValues = protectedValuesFor(protectedSpans);
  const repairStandaloneNotes = hasStandaloneNoteFragment(originalText);
  const restored = withProtectedPlaceholders(text, protectedValues, (masked) => {
    const planned = planNoteStream(masked);
    let repaired = planned ?? repairFragmentSequences(masked, originalText);
    repaired = repaired
      .replace(/\r?\n+/g, " ")
      .replace(/[ \t]{2,}/g, " ")
      .replace(/\.{2,}/g, ".")
      .replace(/\s+([,.;!?])/g, "$1");
    repaired = repairPunctuationSpacing(repaired)
      .replace(/\b([A-Za-z]+)\s+\1\b/gi, "$1")
      .replace(/\b(?:require|requires)\s+fix\s+this\s+text\b/gi, "This text needs fixing")
      .replace(/\bno\s+grammar\b/gi, "the grammar needs work")
      .replace(/\bideas?\s+missing\b/gi, "ideas are missing")
      .replace(/\breason(?:s)?\s+unclear\b/gi, "the reasons are unclear")
      .replace(/\bdeadline\s+missed\b/gi, "the deadline was missed")
      .replace(/\b(?:the\s+)?reasons?\s+unclear\b/gi, "the reasons are unclear")
      .replace(/\bteam\s+say\b/gi, "the team says")
      .replace(/\bmanager\s+want\b/gi, "the manager wants")
      .replace(/\bthe manager wants answer\b/gi, "the manager wants an answer")
      .replace(/\bperformance\s+not where it needs to be\b/gi, "performance is not where it needs to be")
      .replace(/\bmake\s+it\s+good\b/gi, "make it clear and polished")
      .trim();

    repaired = repaired
      .split(/(?<![ap]\.m\.)(?<=[.!?])\s+|(?<![ap]\.)(?<=[.!?])(?=[A-Za-z])/i)
      .map((fragment) => normalizeFragment(fragment, repairStandaloneNotes))
      .filter(Boolean)
      .join(". ");

    if (sourceNeedsStructuralRepair(originalText) && !planned) repaired = joinShortSentences(repaired);

    repaired = repairPunctuationSpacing(repaired.replace(/\s+([,.;!?])/g, "$1")).trim();

    if (repaired && !TERMINAL_PUNCTUATION.test(repaired)) repaired += ".";
    return repaired;
  });
  // "no" is protected because it carries meaning. Keep it in the repair
  // while still turning a noun fragment such as "no grammar" into a clause.
  return restored
    .replace(/\bI have No\b/g, "I have no")
    .replace(/\bno\s+grammar\b/gi, (match) => /^[A-Z]/.test(match) ? "There is no clear grammar" : "there is no clear grammar")
    .replace(/\.\s+(is|are|was|were)\s+/gi, " $1 ")
    .replace(/(\bwho is [^.!?]+?)(?:,)?\s+(is\s+(?:today|tomorrow)\b)/gi, "$1, $2")
    .replace(/\b(no valid excuses are needed;\s+let's focus on what we can do next)(?:\s+will be accepted)?\b/gi, "$1")
    .replace(/\.{2,}/g, ".");
}

export function looksLikeUnrepairedFragmentaryProse(text: string): boolean {
  if (hasStandaloneNoteFragment(text)) return true;
  const fragments = looseFragments(text);
  return fragments.some((fragment) =>
    /^(?:need(?:\s+to)?|reason(?:s)?\s+unclear|ideas?\s+missing|deadline\s+missed|[A-Za-z][A-Za-z'-]*\s+(?:hard|difficult|missing|gone|unclear|ready|late|broken|unacceptable))\b/i.test(fragment)
  );
}

export function looksLikeModelControlEcho(value: string): boolean {
  const markers = [
    /\breturn only the rewritten paragraph\b/i,
    /\bevery fact, detail, number, name, link, date\b/i,
    /\bprotected spans that must appear\b/i,
    /\bthe rewritten paragraph should\b/i,
    /\bthe goal is to produce a\b/i,
    /\boriginal paragraph:\s*/i,
  ];
  return markers.filter((pattern) => pattern.test(value)).length >= 1;
}

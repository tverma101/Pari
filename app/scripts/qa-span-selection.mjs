import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
import {
  applyEditorSpan,
  classifyEditorSpan,
  domPointToTextOffset,
  joinEditorSpanText,
  normalizeEditorSpan,
  splitEditorSpanText,
} from "../src/lib/editor/spanSelection.ts";
import { splitSentences } from "../src/lib/nlp/sentenceSplit.ts";

const text = "The quick brown fox stays calm. When the bell rings, everyone listens.";
const word = normalizeEditorSpan(text, 6, 8);
assert(word, "A selection inside one word should resolve to a word span");
assert.deepEqual(
  { start: word.start, end: word.end, text: word.text, kind: word.kind },
  { start: 4, end: 9, text: "quick", kind: "word" },
  "Word selection did not expand to exact word boundaries"
);

const phrase = normalizeEditorSpan(text, 4, 19);
assert.equal(phrase?.text, "quick brown fox");
assert.equal(phrase?.kind, "phrase");

const clauseStart = text.indexOf("When");
const clauseEnd = text.indexOf("rings") + "rings".length;
assert.equal(normalizeEditorSpan(text, clauseStart, clauseEnd)?.kind, "clause");

const firstSentence = splitSentences(text)[0];
assert.equal(normalizeEditorSpan(text, firstSentence.start, firstSentence.end)?.kind, "sentence");
assert.equal(normalizeEditorSpan(text, 0, text.length)?.kind, "multi-sentence");
assert.equal(normalizeEditorSpan(text, 0, 3)?.text, "The");
assert.equal(normalizeEditorSpan("!!! ???", 0, 7), null);
assert.equal(classifyEditorSpan(text, firstSentence.start, firstSentence.end), "sentence");

const replaced = applyEditorSpan(text, phrase, "slow red fox");
assert.equal(replaced, "The slow red fox stays calm. When the bell rings, everyone listens.");
assert.equal(text.slice(0, phrase.start), replaced.slice(0, phrase.start));
assert.equal(text.slice(phrase.end), replaced.slice(replaced.length - (text.length - phrase.end)));

const split = splitEditorSpanText("The editor revised the draft, and the writer approved it.");
assert.equal(split, "The editor revised the draft. And the writer approved it.");
const joined = joinEditorSpanText(
  "The editor revised the draft.",
  "The writer approved it."
);
assert.equal(joined, "The editor revised the draft, and the writer approved it.");
assert.equal(joinEditorSpanText("The editor left.", "and the writer approved it."), "The editor left and the writer approved it.");

function fakeTextNode(value) {
  return { nodeType: 3, textContent: value, childNodes: [] };
}

function fakeElement(children) {
  return {
    nodeType: 1,
    childNodes: children,
    textContent: children.map((child) => child.textContent).join(""),
    contains(node) {
      return node === this || children.some((child) => child.contains?.(node) ?? node === child);
    },
  };
}

const firstDomText = fakeTextNode("The quick ");
const selectedDomText = fakeTextNode("quick brown");
const lastDomText = fakeTextNode(" fox stays calm.");
const inlineSpan = fakeElement([selectedDomText]);
const fakeEditor = fakeElement([firstDomText, inlineSpan, lastDomText]);
assert.equal(domPointToTextOffset(fakeEditor, selectedDomText, 6), 16);
assert.equal(domPointToTextOffset(fakeEditor, selectedDomText, 0), 10);

const appSource = fs.readFileSync(path.join(ROOT_DIR, "src/App.tsx"), "utf8");
for (const requiredWiring of [
  "onMouseUp={handleSelection}",
  "onSelectRange={handleSelectSpan}",
  "Revert selection",
  "Split sentence",
  "Join with neighbor",
  "handleUndo",
  "handleRedo",
]) {
  assert(appSource.includes(requiredWiring), `Editor wiring is missing ${requiredWiring}`);
}

console.log("qa:span-selection ok");

import assert from "node:assert/strict";
import test from "node:test";
import { editorDomPointAt, editorTextOffsetAt, serializeEditorText } from "../../src/lib/editor/domText.ts";
import { extractContainedReplacement, joinSelectedSentenceWithNeighbor, joinWithSemicolon, replaceTextRange, splitAtClauseBoundary } from "../../src/lib/editor/textEditing.ts";

type FakeNode = {
  nodeType: number;
  nodeValue: string | null;
  tagName: string;
  childNodes: FakeNode[];
  parent: FakeNode | null;
  parentNode: FakeNode | null;
  contains(node: FakeNode): boolean;
};

function text(value: string): FakeNode {
  return { nodeType: 3, nodeValue: value, tagName: "", childNodes: [], parent: null, parentNode: null, contains: () => false };
}

function element(tagName: string, ...children: FakeNode[]): FakeNode {
  const node: FakeNode = {
    nodeType: 1,
    nodeValue: null,
    tagName: tagName.toUpperCase(),
    childNodes: children,
    parent: null,
    parentNode: null,
    contains(candidate) {
      return candidate === node || node.childNodes.some((child) => child === candidate || child.contains(candidate));
    },
  };
  children.forEach((child) => { child.parent = node; child.parentNode = node; });
  return node;
}

const asNode = (node: FakeNode) => node as unknown as Node;

test("serializes editor-created block and BR line breaks into matching text offsets", () => {
  const first = text("First para");
  const second = text("Second line");
  const root = element("div", element("div", first), element("div", second));
  assert.equal(serializeEditorText(asNode(root)).text, "First para\nSecond line");
  assert.equal(editorTextOffsetAt(asNode(root), asNode(second), 7), 18);
  const restoredPoint = editorDomPointAt(asNode(root), 11);
  assert.equal(restoredPoint?.container, asNode(second));
  assert.equal(restoredPoint?.offset, 0);

  const afterBreak = text("next line");
  const withBreak = element("div", text("line one"), element("br"), afterBreak);
  assert.equal(serializeEditorText(asNode(withBreak)).text, "line one\nnext line");
  assert.equal(editorTextOffsetAt(asNode(withBreak), asNode(afterBreak), 0), 9);
});

test("selection replacement supports expansion and compression without touching surrounding text", () => {
  assert.equal(replaceTextRange("The draft helped readers.", { start: 10, end: 16 }, "gave useful support to"),
    "The draft gave useful support to readers.");
  assert.equal(replaceTextRange("The draft was very clear.", { start: 14, end: 24 }, "clear"),
    "The draft was clear.");
});

test("candidate extraction permits length changes only inside the selected span", () => {
  const sentence = "The final draft needs detail before Friday.";
  const range = { start: 22, end: 28 };
  assert.equal(extractContainedReplacement(sentence, range,
    "The final draft needs extensive technical detail before Friday."), "extensive technical detail");
  assert.equal(extractContainedReplacement(sentence, range,
    "The final draft needs examples before Friday."), "examples");
  assert.equal(extractContainedReplacement(sentence, range,
    "The revised draft needs examples before Friday."), null);
});

test("safe split handles semicolon, colon, dash, and coordinating comma boundaries", () => {
  assert.equal(splitAtClauseBoundary("The source is clear; the result is useful."), "The source is clear. The result is useful.");
  assert.equal(splitAtClauseBoundary("The source is clear: the result is useful."), "The source is clear. The result is useful.");
  assert.equal(splitAtClauseBoundary("The source is clear — the result is useful."), "The source is clear. The result is useful.");
  assert.equal(splitAtClauseBoundary("The source is clear, but the result is incomplete."), "The source is clear. But the result is incomplete.");
  assert.equal(splitAtClauseBoundary("The source is clear, the result is useful."), null);
});

test("safe join combines exactly two complete period-ended sentences", () => {
  assert.equal(joinWithSemicolon("The source is clear. The result is useful."), "The source is clear; The result is useful.");
  assert.equal(joinWithSemicolon("The source is clear. Is the result useful?"), null);
});

test("joining one selected sentence includes its next or previous neighbor only", () => {
  const text = "First sentence is clear. Second sentence is useful. Third sentence is concise.";
  const firstEnd = text.indexOf(".") + 1;
  const secondEnd = text.indexOf(".", text.indexOf("Second")) + 1;
  const withNext = joinSelectedSentenceWithNeighbor(text, { start: 0, end: firstEnd });
  assert.deepEqual(withNext && { start: withNext.start, end: withNext.end, replacement: withNext.replacement }, {
    start: 0,
    end: secondEnd,
    replacement: "First sentence is clear; Second sentence is useful.",
  });

  const thirdStart = text.indexOf("Third");
  const thirdEnd = text.length;
  const withPrevious = joinSelectedSentenceWithNeighbor(text, { start: thirdStart, end: thirdEnd });
  assert.equal(withPrevious?.replacement, "Second sentence is useful; Third sentence is concise.");
  assert.equal(joinSelectedSentenceWithNeighbor(text, { start: 1, end: 10 }), null);
});

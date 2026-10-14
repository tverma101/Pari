export interface DomTextPoint {
  container: Node;
  offset: number;
}

export interface SerializedEditorText {
  text: string;
  pointOffset: number | null;
}

const BLOCK_TAGS = new Set(["DIV", "P", "LI", "BLOCKQUOTE", "PRE"]);
const ELEMENT_NODE = 1;
const TEXT_NODE = 3;

/** Serialize contenteditable text with the line breaks browsers imply between block children. */
export function serializeEditorText(root: Node, point?: DomTextPoint): SerializedEditorText {
  let text = "";
  let pointOffset: number | null = null;

  const addLineBreak = () => {
    if (text.length > 0 && !text.endsWith("\n")) text += "\n";
  };

  const visit = (node: Node): boolean => {
    if (point && node === point.container && node.nodeType === TEXT_NODE) {
      const value = node.nodeValue ?? "";
      pointOffset = text.length + Math.max(0, Math.min(point.offset, value.length));
      return true;
    }
    if (node.nodeType === TEXT_NODE) {
      text += (node.nodeValue ?? "").replace(/\u00a0/g, " ");
      return false;
    }
    if (node.nodeType !== ELEMENT_NODE && node !== root) return false;
    const element = node as Element;
    if (element.tagName === "BR") {
      text += "\n";
      return false;
    }

    const children = Array.from(node.childNodes);
    for (let index = 0; index < children.length; index += 1) {
      const child = children[index];
      if (child.nodeType === ELEMENT_NODE && BLOCK_TAGS.has((child as Element).tagName)) addLineBreak();
      if (point && node === point.container && point.offset === index) {
        pointOffset = text.length;
        return true;
      }
      if (visit(child)) return true;
      if (
        child.nodeType === ELEMENT_NODE &&
        BLOCK_TAGS.has((child as Element).tagName) &&
        index < children.length - 1
      ) addLineBreak();
    }
    if (point && node === point.container && point.offset >= children.length) {
      pointOffset = text.length;
      return true;
    }
    return false;
  };

  visit(root);
  return { text, pointOffset };
}

export function editorTextOffsetAt(root: Node, container: Node, offset: number): number | null {
  if (container !== root && !root.contains(container)) return null;
  return serializeEditorText(root, { container, offset }).pointOffset;
}

/** Map a serialized editor offset back to the DOM for restoring the caret. */
export function editorDomPointAt(root: Node, requestedOffset: number): DomTextPoint | null {
  let textLength = 0;
  let point: DomTextPoint | null = null;
  const addLineBreak = () => {
    if (textLength > 0 && lastCharacter !== "\n") {
      textLength += 1;
      lastCharacter = "\n";
    }
  };
  let lastCharacter = "";

  const visit = (node: Node): boolean => {
    if (node.nodeType === TEXT_NODE) {
      const value = (node.nodeValue ?? "").replace(/\u00a0/g, " ");
      if (requestedOffset <= textLength + value.length) {
        point = { container: node, offset: Math.max(0, requestedOffset - textLength) };
        return true;
      }
      textLength += value.length;
      if (value) lastCharacter = value[value.length - 1];
      return false;
    }
    if (node.nodeType !== ELEMENT_NODE && node !== root) return false;
    const children = Array.from(node.childNodes);
    for (const child of children) {
      if (child.nodeType === ELEMENT_NODE && BLOCK_TAGS.has((child as Element).tagName)) addLineBreak();
      if (child.nodeType === ELEMENT_NODE && (child as Element).tagName === "BR") {
        if (requestedOffset <= textLength + 1) {
          const parent = child.parentNode;
          if (parent) point = { container: parent, offset: Array.prototype.indexOf.call(parent.childNodes, child) + (requestedOffset > textLength ? 1 : 0) };
          return true;
        }
        textLength += 1;
        lastCharacter = "\n";
      } else if (visit(child)) {
        return true;
      }
      if (
        child.nodeType === ELEMENT_NODE &&
        BLOCK_TAGS.has((child as Element).tagName) &&
        child !== children[children.length - 1]
      ) addLineBreak();
    }
    if (requestedOffset <= textLength) {
      point = { container: node, offset: children.length };
      return true;
    }
    return false;
  };

  visit(root);
  return point;
}

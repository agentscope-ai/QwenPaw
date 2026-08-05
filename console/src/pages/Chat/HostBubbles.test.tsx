import { describe, expect, it } from "vitest";
import { getContainedSelectionText } from "./HostBubblesSelection";

function selectRange(start: Node, end: Node) {
  const range = document.createRange();
  range.setStart(start, 0);
  range.setEnd(end, end.textContent?.length ?? 0);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
  return selection;
}

describe("HostBubbles selectable message text", () => {
  it("returns selected text when the selection stays inside one card", () => {
    const root = document.createElement("div");
    const text = document.createTextNode("select me");
    root.appendChild(text);
    document.body.appendChild(root);

    const selection = selectRange(text, text);

    expect(getContainedSelectionText(root, selection)).toBe("select me");
  });

  it("ignores selections that cross outside the message card", () => {
    const root = document.createElement("div");
    const inside = document.createTextNode("inside");
    const outside = document.createTextNode(" outside");
    root.appendChild(inside);
    document.body.append(root, outside);

    const selection = selectRange(inside, outside);

    expect(getContainedSelectionText(root, selection)).toBe("");
  });
});

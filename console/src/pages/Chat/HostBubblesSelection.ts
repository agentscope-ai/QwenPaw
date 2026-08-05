export function getContainedSelectionText(
  root: HTMLElement,
  selection: Selection | null,
): string {
  if (!selection || selection.isCollapsed || selection.rangeCount === 0) {
    return "";
  }
  const range = selection.getRangeAt(0);
  const startNode = range.startContainer;
  const endNode = range.endContainer;
  if (!root.contains(startNode) || !root.contains(endNode)) {
    return "";
  }
  return selection.toString().trim();
}

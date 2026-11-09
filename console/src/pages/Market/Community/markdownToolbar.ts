/**
 * Markdown toolbar transformations, ported from the platform front
 * (src/lib/markdownToolbar.ts): GitHub-style wrap / line-prefix / link-image
 * insertion with selection bookkeeping, pure string in/out.
 */
export type MarkdownToolbarAction =
  | "heading"
  | "bold"
  | "italic"
  | "quote"
  | "code"
  | "link"
  | "ul"
  | "ol"
  | "task"
  | "image";

type ApplyResult = {
  nextValue: string;
  selectionStart: number;
  selectionEnd: number;
};

/** Inline wraps matching the GitHub PR description editor. */
const WRAP: Record<
  "bold" | "italic" | "code",
  { before: string; after: string }
> = {
  bold: { before: "**", after: "**" },
  // GitHub uses underscore italics.
  italic: { before: "_", after: "_" },
  code: { before: "`", after: "`" },
};

const LINE_PREFIX: Record<
  "heading" | "quote" | "ul" | "ol" | "task",
  { prefix: string }
> = {
  heading: { prefix: "### " },
  quote: { prefix: "> " },
  ul: { prefix: "- " },
  ol: { prefix: "1. " },
  task: { prefix: "- [ ] " },
};

function isWordChar(ch: string): boolean {
  return /[^\s]/.test(ch);
}

/** Expand an empty selection to the surrounding word boundary. */
function expandToWord(
  value: string,
  start: number,
  end: number,
): { start: number; end: number } {
  if (start !== end) return { start, end };
  let s = start;
  let e = end;
  while (s > 0 && isWordChar(value[s - 1]!)) s -= 1;
  while (e < value.length && isWordChar(value[e]!)) e += 1;
  return { start: s, end: e };
}

function wrapSelection(
  value: string,
  start: number,
  end: number,
  before: string,
  after: string,
): ApplyResult {
  const expanded = expandToWord(value, start, end);
  const selStart = expanded.start;
  const selEnd = expanded.end;
  const selected = value.slice(selStart, selEnd);

  // Already wrapped outside the selection: unwrap on second click.
  const outerStart = selStart - before.length;
  const outerEnd = selEnd + after.length;
  if (
    outerStart >= 0 &&
    outerEnd <= value.length &&
    value.slice(outerStart, selStart) === before &&
    value.slice(selEnd, outerEnd) === after
  ) {
    const nextValue =
      value.slice(0, outerStart) + selected + value.slice(outerEnd);
    return {
      nextValue,
      selectionStart: outerStart,
      selectionEnd: outerStart + selected.length,
    };
  }

  if (
    selected.startsWith(before) &&
    selected.endsWith(after) &&
    selected.length >= before.length + after.length
  ) {
    const inner = selected.slice(before.length, selected.length - after.length);
    const nextValue = value.slice(0, selStart) + inner + value.slice(selEnd);
    return {
      nextValue,
      selectionStart: selStart,
      selectionEnd: selStart + inner.length,
    };
  }

  const nextValue =
    value.slice(0, selStart) + before + selected + after + value.slice(selEnd);
  const selectionStart = selStart + before.length;
  return {
    nextValue,
    selectionStart,
    selectionEnd: selectionStart + selected.length,
  };
}

function prefixLines(
  value: string,
  start: number,
  end: number,
  prefix: string,
): ApplyResult {
  const lineStart = value.lastIndexOf("\n", Math.max(0, start - 1)) + 1;
  const lineEndIndex = value.indexOf("\n", end);
  const lineEnd = lineEndIndex === -1 ? value.length : lineEndIndex;
  const block = value.slice(lineStart, lineEnd);
  const lines = block.length ? block.split("\n") : [""];

  const matchesPrefix = (line: string) => {
    if (prefix === "1. ") return /^\d+\.\s+/.test(line);
    return line.startsWith(prefix);
  };
  const stripPrefix = (line: string) => {
    if (prefix === "1. ") return line.replace(/^\d+\.\s+/, "");
    return line.startsWith(prefix) ? line.slice(prefix.length) : line;
  };

  const allPrefixed = lines.every(
    (line) => !line.trim() || matchesPrefix(line),
  );
  const anyPrefixed = lines.some((line) => matchesPrefix(line));

  const nextLines = lines.map((line) => {
    if (allPrefixed && anyPrefixed) {
      return stripPrefix(line);
    }
    if (!line.trim()) {
      return prefix;
    }
    if (matchesPrefix(line)) {
      return line;
    }
    // Switching list kinds: drop the opposing prefix first.
    const stripped = line
      .replace(/^#{1,6}\s+/, "")
      .replace(/^>\s?/, "")
      .replace(/^- \[ \] /, "")
      .replace(/^- /, "")
      .replace(/^\d+\.\s+/, "");
    return `${prefix}${stripped}`;
  });

  const nextBlock = nextLines.join("\n");
  const nextValue =
    value.slice(0, lineStart) + nextBlock + value.slice(lineEnd);
  return {
    nextValue,
    selectionStart: lineStart,
    selectionEnd: lineStart + nextBlock.length,
  };
}

function applyLinkOrImage(
  value: string,
  selectionStart: number,
  selectionEnd: number,
  isImage: boolean,
): ApplyResult {
  const selected = value.slice(selectionStart, selectionEnd);
  const prefix = isImage ? "![" : "[";
  const urlToken = "url";
  const isUrl = /^https?:\/\//i.test(selected);

  if (isUrl) {
    // Selection is the address: ![|](selected), caret lands in the label.
    const inserted = `${prefix}](${selected})`;
    const nextValue =
      value.slice(0, selectionStart) + inserted + value.slice(selectionEnd);
    const cursor = selectionStart + prefix.length;
    return { nextValue, selectionStart: cursor, selectionEnd: cursor };
  }

  // [](url) / ![alt](url) with the url token selected for quick replacement.
  const inserted = `${prefix}${selected}](${urlToken})`;
  const nextValue =
    value.slice(0, selectionStart) + inserted + value.slice(selectionEnd);
  const urlStart = selectionStart + prefix.length + selected.length + 2;
  return {
    nextValue,
    selectionStart: urlStart,
    selectionEnd: urlStart + urlToken.length,
  };
}

function applyCode(
  value: string,
  selectionStart: number,
  selectionEnd: number,
): ApplyResult {
  const selected = value.slice(selectionStart, selectionEnd);
  if (selected.includes("\n")) {
    const block = `\`\`\`\n${selected}\n\`\`\``;
    const nextValue =
      value.slice(0, selectionStart) + block + value.slice(selectionEnd);
    const innerStart = selectionStart + 4; // after ```\n
    return {
      nextValue,
      selectionStart: innerStart,
      selectionEnd: innerStart + selected.length,
    };
  }
  return wrapSelection(
    value,
    selectionStart,
    selectionEnd,
    WRAP.code.before,
    WRAP.code.after,
  );
}

export function applyMarkdownAction(
  value: string,
  selectionStart: number,
  selectionEnd: number,
  action: MarkdownToolbarAction,
): ApplyResult {
  if (action === "image") {
    return applyLinkOrImage(value, selectionStart, selectionEnd, true);
  }
  if (action === "link") {
    return applyLinkOrImage(value, selectionStart, selectionEnd, false);
  }
  if (action === "code") {
    return applyCode(value, selectionStart, selectionEnd);
  }
  if (action === "bold" || action === "italic") {
    const { before, after } = WRAP[action];
    return wrapSelection(value, selectionStart, selectionEnd, before, after);
  }
  const { prefix } = LINE_PREFIX[action];
  return prefixLines(value, selectionStart, selectionEnd, prefix);
}

const HEADLINE_START_RE = /<!--\s*[⟦〚]/;
const HEADLINE_CLOSE_RE = /[⟧〛]\s*-->/;
const HEADLINE_LINE_RE =
  /^[ \t]*(?:<!--)?[ \t]*[⟦〚][ \t]*(.+?)[ \t]*[⟧〛][ \t]*(?:-->)?[ \t]*$/gm;

export type HeadlineStreamFilterState = {
  pending: string;
  suppressing: boolean;
};

export function createHeadlineFilterState(): HeadlineStreamFilterState {
  return { pending: "", suppressing: false };
}

export function stripScrollHeadlines(text: string): string {
  return text
    .replace(HEADLINE_LINE_RE, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/** Mutate completed text blocks without interpreting nested stream deltas. */
export function stripScrollHeadlineTextBlocks(node: unknown): void {
  if (!node || typeof node !== "object") return;
  if (Array.isArray(node)) {
    node.forEach(stripScrollHeadlineTextBlocks);
    return;
  }

  const record = node as Record<string, unknown>;
  if (record.type === "text" && typeof record.text === "string") {
    record.text = stripScrollHeadlines(record.text);
  }
  Object.values(record).forEach(stripScrollHeadlineTextBlocks);
}

function isPossibleHeadlineStartPrefix(value: string): boolean {
  const commentStart = "<!--";
  if (value.length < commentStart.length) {
    return commentStart.startsWith(value);
  }
  if (!value.startsWith(commentStart)) return false;
  return /^\s*$/.test(value.slice(commentStart.length));
}

function findPotentialHeadlineStart(text: string): number {
  const candidateStart = text.lastIndexOf("<");
  if (candidateStart < 0) return -1;
  return isPossibleHeadlineStartPrefix(text.slice(candidateStart))
    ? candidateStart
    : -1;
}

function isPossibleHeadlineClosePrefix(value: string): boolean {
  if (!value || !"⟧〛".includes(value[0])) return false;
  const suffix = value.slice(1);
  const markerStart = suffix.search(/\S/);
  if (markerStart < 0) return true;
  return "-->".startsWith(suffix.slice(markerStart));
}

function findPotentialHeadlineClose(text: string): number {
  const candidateStart = Math.max(
    text.lastIndexOf("⟧"),
    text.lastIndexOf("〛"),
  );
  if (candidateStart < 0) return -1;
  return isPossibleHeadlineClosePrefix(text.slice(candidateStart))
    ? candidateStart
    : -1;
}

export function filterHeadlineDelta(
  delta: string,
  state: HeadlineStreamFilterState,
): string {
  let text = state.pending + delta;
  state.pending = "";
  let out = "";

  while (text) {
    if (state.suppressing) {
      const close = HEADLINE_CLOSE_RE.exec(text);
      if (!close) {
        const potentialClose = findPotentialHeadlineClose(text);
        state.pending = potentialClose >= 0 ? text.slice(potentialClose) : "";
        return out;
      }
      text = text.slice(close.index + close[0].length);
      state.suppressing = false;
      continue;
    }

    const start = HEADLINE_START_RE.exec(text);
    if (start) {
      out += text.slice(0, start.index);
      text = text.slice(start.index + start[0].length);
      state.suppressing = true;
      continue;
    }

    const potentialStart = findPotentialHeadlineStart(text);
    if (potentialStart >= 0) {
      out += text.slice(0, potentialStart);
      state.pending = text.slice(potentialStart);
      return out;
    }

    return out + text;
  }

  return out;
}

export function flushHeadlineFilter(state: HeadlineStreamFilterState): string {
  const trailing = state.suppressing ? "" : state.pending;
  state.pending = "";
  state.suppressing = false;
  return trailing;
}

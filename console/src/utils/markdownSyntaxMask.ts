/**
 * Syntax-range masks for the CJK emphasis repair.
 *
 * The previous implementation walked the source line by line and re-implemented
 * CommonMark container parsing (blockquote depth, list-item indent, fence
 * continuation) by hand. Every review round turned up another nesting
 * combination it could not express, and one round produced the opposite bug:
 * text that should have been repaired was masked instead.
 *
 * This module delegates that job to micromark, which reports `start.offset` /
 * `end.offset` for every token. Ranges that must stay byte-for-byte identical
 * are read straight off the token stream instead of being inferred.
 */
import { parse, postprocess, preprocess } from "micromark";

interface Token {
  type: string;
  start?: { offset?: number };
  end?: { offset?: number };
}

/** Block ranges: fill the whole range, newlines included. */
const BLOCK_TOKENS = new Set(["codeFenced", "codeIndented", "htmlFlow"]);

/** Inline ranges: fill the characters the renderer treats literally. */
const TEXT_TOKENS = new Set([
  "codeText",
  "autolink",
  "autolinkMarker",
  "autolinkProtocol",
  "autolinkEmail",
  "resourceDestination",
  "resourceDestinationRaw",
  "resourceTitle",
  "resourceTitleString",
  "definitionDestination",
  "definitionDestinationRaw",
  "definitionDestinationString",
  "definitionTitle",
  "definitionTitleString",
  "htmlText",
]);

function tokenize(src: string): Token[] {
  const chunks = postprocess(
    parse()
      .document()
      .write(preprocess()(src, undefined, true)),
  );
  const out: Token[] = [];
  for (const event of chunks) {
    const token = (event as unknown as unknown[])[1] as Token | undefined;
    if (!token || typeof token.type !== "string") continue;
    if (token.start?.offset === undefined) continue;
    if (token.end?.offset === undefined) continue;
    out.push(token);
  }
  return out;
}

/**
 * Streaming input has no delimiter to close a construct yet. CommonMark does
 * not treat an unterminated run as a code span or a link, and none of those
 * constructs may cross a blank line, so a dangling opener only reaches the end
 * of the paragraph that contains it. Skipping to the end of the document
 * instead would let one stray `$` or backtick freeze every later paragraph.
 */
function maskDanglingTail(
  src: string,
  block: Uint8Array,
  text: Uint8Array,
): void {
  // Already tokenized code and literal spans cannot open a construct.
  const taken = (index: number) => block[index] === 1 || text[index] === 1;

  // Unterminated inline code: an odd number of backticks means the last run
  // has no partner.
  let open = -1;
  for (let i = 0; i < src.length; i++) {
    if (src[i] !== "`" || taken(i) || isEscaped(src, i)) continue;
    if (open < 0) {
      open = i;
    } else {
      open = -1;
      i += countRun(src, i) - 1;
    }
  }
  if (open >= 0) text.fill(1, open, paragraphEnd(src, open));

  // Unterminated inline math (`$...$` without the closing dollar). A `$` inside
  // code is already taken, so `echo $HOME` cannot open math.
  let mathOpen = -1;
  for (let i = 0; i < src.length; i++) {
    if (src[i] !== "$" || taken(i) || isEscaped(src, i)) continue;
    if (src[i + 1] === "$") {
      i++;
    }
    mathOpen = mathOpen < 0 ? i : -1;
  }
  if (mathOpen >= 0) text.fill(1, mathOpen, paragraphEnd(src, mathOpen));

  // Unterminated link destination: `[label](` with no closing paren. The
  // opening bracket has to exist, otherwise a literal `](` in running text
  // would mask the rest of the paragraph.
  const lastOpen = src.lastIndexOf("](");
  if (lastOpen >= 0) {
    const end = paragraphEnd(src, lastOpen);
    if (src.slice(lastOpen, end).indexOf(")") < 0) {
      const bracket = src.lastIndexOf("[", lastOpen);
      if (bracket >= 0) text.fill(1, lastOpen, end);
    }
  }
}

/** Offset of the line break that closes the paragraph starting at `from`. */
function paragraphEnd(src: string, from: number): number {
  let lineStart = from;
  while (lineStart < src.length) {
    const newline = src.indexOf("\n", lineStart);
    if (newline < 0) return src.length;
    let next = newline + 1;
    while (next < src.length && (src[next] === " " || src[next] === "\t")) {
      next++;
    }
    if (next >= src.length || src[next] === "\n" || src[next] === "\r") {
      return newline;
    }
    lineStart = next;
  }
  return src.length;
}

/**
 * An unterminated fence never becomes a token, so the tokenizer reports its
 * body as ordinary paragraphs. A fence body may contain blank lines, so this
 * skip has to reach the end of the document.
 */
function maskUnclosedFence(
  src: string,
  block: Uint8Array,
  text: Uint8Array,
): void {
  const fence = /^[ \t]{0,3}(`{3,}|~{3,})/gm;
  let openStart = -1;
  let openCharacter = "";
  let openLength = 0;
  let match: RegExpExecArray | null;
  while ((match = fence.exec(src)) !== null) {
    const marker = match[1];
    if (openStart < 0) {
      openStart = match.index;
      openCharacter = marker[0];
      openLength = marker.length;
    } else if (marker[0] === openCharacter && marker.length >= openLength) {
      openStart = -1;
    }
  }
  // A delivered fence already owns its range and must not be extended.
  if (openStart >= 0 && block[openStart] === 0 && text[openStart] === 0) {
    block.fill(1, openStart);
    text.fill(1, openStart);
  }
}

function isEscaped(src: string, index: number): boolean {
  let slashes = 0;
  for (let i = index - 1; i >= 0 && src[i] === "\\"; i--) slashes++;
  return slashes % 2 === 1;
}

function countRun(src: string, index: number): number {
  const ch = src[index];
  let n = 0;
  while (src[index + n] === ch) n++;
  return n;
}

export function buildSyntaxMasks(src: string): {
  block: Uint8Array;
  protectedText: Uint8Array;
  paragraphReset: Uint8Array;
} {
  const block = new Uint8Array(src.length);
  const text = new Uint8Array(src.length);
  const paragraphReset = new Uint8Array(src.length + 1);

  for (const token of tokenize(src)) {
    const from = token.start?.offset;
    const to = token.end?.offset;
    if (from === undefined || to === undefined || to <= from) continue;
    if (BLOCK_TOKENS.has(token.type)) {
      block.fill(1, from, to);
    } else if (TEXT_TOKENS.has(token.type)) {
      text.fill(1, from, to);
    }
  }

  maskUnclosedFence(src, block, text);
  maskDanglingTail(src, block, text);

  // A reference definition whose `<...>` destination wraps onto the next line
  // is not a valid CommonMark definition, so the tokenizer reads it as ordinary
  // paragraph text. The review asked for wrapped destinations to stay intact
  // anyway, so mask those spans explicitly.
  const wrappedDestination = /^\[[^\]\n]*\]:[ \t]*<[^>]*>/gm;
  let match: RegExpExecArray | null;
  while ((match = wrappedDestination.exec(src)) !== null) {
    if (match[0].indexOf("\n") >= 0) {
      text.fill(1, match.index, match.index + match[0].length);
    }
  }

  // Everything masked as block text is also literal text.
  for (let i = 0; i < src.length; i++) {
    if (block[i]) text[i] = 1;
  }

  // LaTeX: the core tokenizer has no math extension, so `$...$` reaches the
  // repair as ordinary text. Mask the whole formula.
  const mathPattern =
    /\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\$[^$\n]*\$|\\\([\s\S]*?\\\)/g;
  let math: RegExpExecArray | null;
  while ((math = mathPattern.exec(src)) !== null) {
    text.fill(1, math.index, math.index + math[0].length);
  }

  // A footnote definition reads as a reference definition to the core
  // tokenizer (`label: destination`), which masks its body. The review asked
  // for footnote text to be handled as ordinary inline content, so unmask it.
  const footnote = /^\[\^[^\]\n]+\]:[ \t]*/gm;
  let note: RegExpExecArray | null;
  while ((note = footnote.exec(src)) !== null) {
    const from = note.index + note[0].length;
    let to = src.indexOf("\n", from);
    if (to < 0) to = src.length;
    block.fill(0, from, to);
    text.fill(0, from, to);
  }

  // A blank line ends the paragraph; the repair must not reach across it.
  for (let i = 0; i < src.length; i++) {
    if (src[i] !== "\n") continue;
    let j = i + 1;
    while (j < src.length && (src[j] === " " || src[j] === "\t")) j++;
    if (j >= src.length || src[j] === "\n" || src[j] === "\r") {
      paragraphReset[i + 1] = 1;
    }
  }
  paragraphReset[src.length] = 1;

  return { block, protectedText: text, paragraphReset };
}

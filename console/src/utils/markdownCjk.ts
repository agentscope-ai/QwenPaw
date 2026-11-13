/**
 * CJK-friendly normalization for Markdown emphasis boundaries.
 *
 * CommonMark's emphasis "flanking" rules classify CJK sentence punctuation as
 * Unicode punctuation. CJK text is written without inter-word spaces, so a
 * closing emphasis delimiter that sits immediately after CJK punctuation and
 * immediately before CJK text is judged "not a valid closer" and the raw
 * markers leak into the rendered output, e.g.:
 *
 *     **没有改动任何设置。**所有内容保持不变。
 *
 * This helper rewrites such boundaries by moving the trailing CJK punctuation
 * run outside the delimiter, producing the equivalent, renderable form:
 *
 *     **没有改动任何设置**。所有内容保持不变。
 *
 * The repair is deliberately conservative and display-oriented:
 * - only `*`, `_`, `**`, `__`, `***` and `___` are considered;
 * - only `。！？；：，、…` plus full-width trailing closers are moved, and only
 *   when the delimiter is immediately followed by Han, Hiragana, Katakana or
 *   Hangul text;
 * - fenced, indented and inline code, escaped delimiters, CRLF endings and
 *   unrelated unfinished Markdown are preserved verbatim.
 *
 * Related: CommonMark discussion `commonmark/commonmark-spec#650`.
 */

const CORE_PUNCTUATION = new Set([
  "。",
  "！",
  "？",
  "；",
  "：",
  "，",
  "、",
  "…",
]);
const TRAILING_CLOSERS = new Set([
  "”",
  "’",
  "」",
  "』",
  "】",
  "》",
  "〉",
  "）",
  "〕",
  "］",
]);
const CJK_SCRIPT =
  /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]/u;
const UNICODE_PUNCTUATION_OR_SYMBOL = /[\p{P}\p{S}]/u;

const OPENING_FENCE = /^( {0,3})(`{3,}|~{3,})(.*)$/;
const LEADING_SPACE = /^ {0,3}/;
const INDENT = /^(?: {4}|\t)/;
const BLANK = /^[ \t]*$/;

interface Fence {
  character: "`" | "~";
  length: number;
}

interface Delimiter {
  character: "*" | "_";
  length: number;
}

interface Replacement {
  punctuationStart: number;
  delimiterStart: number;
  delimiterEnd: number;
}

/** Move CJK sentence punctuation out of malformed emphasis boundaries. */
export function normalizeCjkEmphasis(markdown: string): string {
  if (markdown.length === 0) return markdown;

  const { block, protectedText, paragraphReset } =
    buildProtectionMasks(markdown);
  const replacements: Replacement[] = [];
  let delimiters: Delimiter[] = [];
  let wasBlock = false;

  for (let index = 0; index < markdown.length; index++) {
    if (paragraphReset[index]) delimiters = [];

    if (block[index]) {
      if (!wasBlock) delimiters = [];
      wasBlock = true;
      continue;
    }
    if (wasBlock) {
      delimiters = [];
      wasBlock = false;
    }
    if (protectedText[index]) continue;

    const character = markdown[index];
    if (character !== "*" && character !== "_") continue;

    const runLength = countRun(markdown, protectedText, index, character);
    if (runLength !== 1 && runLength !== 2 && runLength !== 3) {
      index += runLength - 1;
      continue;
    }
    if (isEscaped(markdown, index)) {
      index += runLength - 1;
      continue;
    }

    const punctuationStart = findTrailingPunctuationStart(markdown, index);
    const top = delimiters[delimiters.length - 1];
    const matchingTop =
      top?.character === character && top.length === runLength;
    const isRepairCandidate =
      punctuationStart >= 0 &&
      isCjkAt(markdown, index + runLength) &&
      rangeIsUnprotected(protectedText, punctuationStart, index + runLength) &&
      !createsEscapePair(markdown, punctuationStart);

    if (isRepairCandidate && matchingTop) {
      delimiters.pop();
      replacements.push({
        punctuationStart,
        delimiterStart: index,
        delimiterEnd: index + runLength,
      });
      index += runLength - 1;
      continue;
    }

    const { canOpen, canClose } = delimiterFlanking(markdown, index, runLength);
    if (canClose && matchingTop) {
      delimiters.pop();
    } else if (canOpen) {
      delimiters.push({ character: character as "*" | "_", length: runLength });
    }
    index += runLength - 1;
  }

  if (replacements.length === 0) return markdown;

  let output = "";
  let copiedThrough = 0;
  for (const replacement of replacements) {
    output += markdown.slice(copiedThrough, replacement.punctuationStart);
    output += markdown.slice(
      replacement.delimiterStart,
      replacement.delimiterEnd,
    );
    output += markdown.slice(
      replacement.punctuationStart,
      replacement.delimiterStart,
    );
    copiedThrough = replacement.delimiterEnd;
  }
  output += markdown.slice(copiedThrough);
  return output;
}

function buildProtectionMasks(markdown: string): {
  block: Uint8Array;
  protectedText: Uint8Array;
  paragraphReset: Uint8Array;
} {
  const block = new Uint8Array(markdown.length);
  const paragraphReset = new Uint8Array(markdown.length + 1);
  let fence: Fence | undefined;
  let fenceOffset = 0;

  for (let lineStart = 0; lineStart < markdown.length; ) {
    const newline = markdown.indexOf("\n", lineStart);
    const lineEndWithNewline = newline < 0 ? markdown.length : newline + 1;
    let contentEnd = newline < 0 ? markdown.length : newline;
    if (contentEnd > lineStart && markdown[contentEnd - 1] === "\r") {
      contentEnd--;
    }
    const line = markdown.slice(lineStart, contentEnd);

    if (fence) {
      // Inside a fence only the container prefix that opened it may be
      // stripped. Re-deriving the prefix per line would read `- ~~~` or
      // `> ~~~` as the closing fence and start rewriting code.
      block.fill(1, lineStart, lineEndWithNewline);
      if (isClosingFence(line.slice(fenceOffset), fence)) fence = undefined;
    } else {
      const offset = containerOffset(line);
      const content = line.slice(offset);
      const openingFence = getOpeningFence(content);
      if (openingFence) {
        fence = openingFence;
        fenceOffset = offset;
        block.fill(1, lineStart, lineEndWithNewline);
      } else if (INDENT.test(content)) {
        block.fill(1, lineStart, lineEndWithNewline);
      } else if (BLANK.test(content)) {
        paragraphReset[lineStart] = 1;
        paragraphReset[lineEndWithNewline] = 1;
      }
    }
    lineStart = lineEndWithNewline;
  }

  const protectedText = block.slice();
  markInlineCode(markdown, block, protectedText);
  markLinkDestinations(markdown, block, protectedText);
  return { block, protectedText, paragraphReset };
}

/**
 * Length of the container prefix (blockquote markers and the first list
 * marker) so fenced and indented code inside quotes and list items are still
 * recognised.
 */
function containerOffset(line: string): number {
  let offset = 0;
  for (;;) {
    const quote = /^ {0,3}>[ \t]?/.exec(line.slice(offset));
    if (quote) {
      offset += quote[0].length;
      continue;
    }
    // Consume exactly one separator character after the marker. The rest is
    // real content indentation: `-     code` is an indented code block, and
    // swallowing those spaces would turn it into ordinary text.
    const list = /^ {0,3}(?:[-+*]|\d{1,9}[.)])[ \t]/.exec(line.slice(offset));
    if (!list) break;
    offset += list[0].length;
  }
  return offset;
}

function getOpeningFence(line: string): Fence | undefined {
  const match = OPENING_FENCE.exec(line);
  if (!match) return undefined;
  const run = match[2];
  if (run[0] === "`" && match[3].includes("`")) return undefined;
  return { character: run[0] as "`" | "~", length: run.length };
}

function isClosingFence(line: string, fence: Fence): boolean {
  const offset = LEADING_SPACE.exec(line)?.[0].length ?? 0;
  let end = offset;
  while (line[end] === fence.character) end++;
  return end - offset >= fence.length && BLANK.test(line.slice(end));
}

function markInlineCode(
  markdown: string,
  block: Uint8Array,
  protectedText: Uint8Array,
): void {
  for (let index = 0; index < markdown.length; index++) {
    if (block[index] || markdown[index] !== "`" || isEscaped(markdown, index)) {
      continue;
    }
    const openingLength = countCharacterRun(markdown, index, "`");
    let closingStart = -1;

    for (let cursor = index + openingLength; cursor < markdown.length; ) {
      if (block[cursor]) break;
      if (markdown[cursor] !== "`" || isEscaped(markdown, cursor)) {
        cursor++;
        continue;
      }
      const closingLength = countCharacterRun(markdown, cursor, "`");
      if (closingLength === openingLength) {
        closingStart = cursor;
        break;
      }
      cursor += closingLength;
    }

    if (closingStart < 0) {
      protectedText.fill(1, index);
      return;
    }
    const end = closingStart + openingLength;
    protectedText.fill(1, index, end);
    index = end - 1;
  }
}

/**
 * Mark inline-link destinations and reference definitions so their URLs are
 * never rewritten: moving punctuation inside a URL would change the target.
 */
function markLinkDestinations(
  markdown: string,
  block: Uint8Array,
  protectedText: Uint8Array,
): void {
  for (let index = 0; index < markdown.length - 1; index++) {
    if (block[index] || protectedText[index]) continue;
    if (markdown[index] !== "]" || markdown[index + 1] !== "(") continue;
    const close = findClosingParen(markdown, index + 1, block);
    if (close < 0) continue;
    protectedText.fill(1, index + 2, close);
    index = close;
  }

  // Reference definitions, possibly inside a blockquote, and possibly using an
  // angle-bracket destination that spans several lines.
  const definition =
    /^[ \t]*(?:>[ \t]?)*\[[^\]\n]+\]:[ \t]*(?:<([^<>]*)>|(\S+))/gm;
  for (const match of markdown.matchAll(definition)) {
    const target = match[1] ?? match[2];
    if (!target) continue;
    const start = (match.index ?? 0) + match[0].length - target.length;
    if (block[start]) continue;
    protectedText.fill(1, start, start + target.length);
  }

  // Autolinks: <https://...> and <user@host>. Their text is the destination.
  const autolink = /<([a-zA-Z][a-zA-Z0-9+.-]*:[^<>\s]*|[^<>\s@]+@[^<>\s]+)>/g;
  for (const match of markdown.matchAll(autolink)) {
    const start = (match.index ?? 0) + 1;
    if (block[start]) continue;
    protectedText.fill(1, start, start + match[1].length);
  }
}

/** Index of the `)` matching the `(` at `open`, or -1 when unclosed. */
function findClosingParen(
  markdown: string,
  open: number,
  block: Uint8Array,
): number {
  let depth = 0;
  for (let index = open; index < markdown.length; index++) {
    if (block[index]) return -1;
    const character = markdown[index];
    if (character === "\\") {
      index++;
      continue;
    }
    if (character === "(") {
      depth++;
      continue;
    }
    if (character !== ")") continue;
    depth--;
    if (depth === 0) return index;
  }
  return -1;
}

function countRun(
  markdown: string,
  protectedText: Uint8Array,
  start: number,
  character: string,
): number {
  let end = start;
  while (
    end < markdown.length &&
    !protectedText[end] &&
    markdown[end] === character
  ) {
    end++;
  }
  return end - start;
}

function countCharacterRun(
  markdown: string,
  start: number,
  character: string,
): number {
  let end = start;
  while (markdown[end] === character) end++;
  return end - start;
}

function isEscaped(markdown: string, index: number): boolean {
  let backslashes = 0;
  for (
    let cursor = index - 1;
    cursor >= 0 && markdown[cursor] === "\\";
    cursor--
  ) {
    backslashes++;
  }
  return backslashes % 2 === 1;
}

function findTrailingPunctuationStart(markdown: string, end: number): number {
  let cursor = end;
  while (cursor > 0 && TRAILING_CLOSERS.has(markdown[cursor - 1])) cursor--;
  const beforeCore = cursor;
  while (cursor > 0 && CORE_PUNCTUATION.has(markdown[cursor - 1])) cursor--;
  return cursor < beforeCore ? cursor : -1;
}

/**
 * Moving the punctuation run out of the delimiter must not turn an existing
 * backslash into an escape for the delimiter itself (``**a\。**b``), which
 * would drop the emphasis and leave a stray backslash behind.
 */
function createsEscapePair(
  markdown: string,
  punctuationStart: number,
): boolean {
  if (punctuationStart <= 0 || markdown[punctuationStart - 1] !== "\\") {
    return false;
  }
  let backslashes = 0;
  for (
    let cursor = punctuationStart - 1;
    cursor >= 0 && markdown[cursor] === "\\";
    cursor--
  ) {
    backslashes++;
  }
  return backslashes % 2 === 1;
}

function isCjkAt(markdown: string, index: number): boolean {
  const point = markdown.codePointAt(index);
  return point !== undefined && CJK_SCRIPT.test(String.fromCodePoint(point));
}

function rangeIsUnprotected(
  protectedText: Uint8Array,
  start: number,
  end: number,
): boolean {
  for (let index = start; index < end; index++) {
    if (protectedText[index]) return false;
  }
  return true;
}

function codePointBefore(markdown: string, index: number): string | undefined {
  if (index <= 0) return undefined;
  const second = markdown.charCodeAt(index - 1);
  if (second >= 0xdc00 && second <= 0xdfff && index >= 2) {
    return markdown.slice(index - 2, index);
  }
  return markdown[index - 1];
}

function codePointAt(markdown: string, index: number): string | undefined {
  const point = markdown.codePointAt(index);
  return point === undefined ? undefined : String.fromCodePoint(point);
}

function delimiterFlanking(
  markdown: string,
  start: number,
  length: number,
): { canOpen: boolean; canClose: boolean } {
  const previous = codePointBefore(markdown, start);
  const next = codePointAt(markdown, start + length);
  const previousWhitespace = previous === undefined || /\s/u.test(previous);
  const nextWhitespace = next === undefined || /\s/u.test(next);
  const previousPunctuation =
    previous !== undefined && UNICODE_PUNCTUATION_OR_SYMBOL.test(previous);
  const nextPunctuation =
    next !== undefined && UNICODE_PUNCTUATION_OR_SYMBOL.test(next);
  const leftFlanking =
    !nextWhitespace &&
    (!nextPunctuation || previousWhitespace || previousPunctuation);
  const rightFlanking =
    !previousWhitespace &&
    (!previousPunctuation || nextWhitespace || nextPunctuation);

  if (markdown[start] === "*") {
    return { canOpen: leftFlanking, canClose: rightFlanking };
  }
  return {
    canOpen: leftFlanking && (!rightFlanking || previousPunctuation),
    canClose: rightFlanking && (!leftFlanking || nextPunctuation),
  };
}

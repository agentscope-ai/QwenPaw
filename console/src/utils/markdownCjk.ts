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

import { buildSyntaxMasks } from "./markdownSyntaxMask";

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
  return buildSyntaxMasks(markdown);
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

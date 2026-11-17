import { Marked, type Token, type Tokens, type TokensList } from "marked";
import Latex from "@ant-design/x-markdown/plugins/Latex";

/**
 * CJK emphasis repair must be bounded by the grammar the chat bubble actually
 * renders with, not by an approximation of it.
 *
 * The bubble renders through the `Markdown` component of `@agentscope-ai/chat`,
 * which builds `new Marked()` with GFM on and `breaks` off, then applies
 * `use(options.markedConfig || {})`. This module rebuilds that configuration
 * and derives every editable region from its tokens, so the repair pass can
 * only touch source the renderer classified as inline text (or the delimiter
 * folds of an existing emphasis node).
 *
 * Everything else is out of reach: fenced and inline code, HTML, tables, link
 * destinations and titles, math spans, footnote markers, and any source no
 * token claims at all. Link reference definitions are protected for exactly
 * that last reason: `marked` drops them from the token stream, so nothing here
 * is allowed to edit them.
 */

/**
 * A text token that still holds one of these has an ambiguous boundary: the
 * renderer did not resolve it, so the repair may not either. Everything from
 * the first such occurrence to the end of the block is left untouched, which is
 * what a streaming segment ending in a lone backtick, `$` or `[` looks like.
 */
const UNFINISHED_CONSTRUCTS: readonly RegExp[] = [/`/, /\$/, /<[a-zA-Z/!]/];

/** Delimiters that must be paired before their interior is safe to rewrite. */
const PAIRED_DELIMITERS: readonly RegExp[] = [
  /\\\(([\s\S]*?)\\\)/g,
  /\\\[([\s\S]*?)\\\]/g,
];

export interface SourceSpan {
  start: number;
  end: number;
}

export interface RendererMasks {
  protectedText: Uint8Array;
  paragraphReset: Uint8Array;
}

let cachedRendererLexer: Marked | null = null;

export function buildRendererLexer(): Marked {
  // `Latex()` returns one extension object per maths construct, so it has to go
  // through `options.extensions`. Passing those objects positionally to the
  // constructor silently drops them: `use()` only reads a pack's own
  // `extensions` field, and a bare tokenizer has none.
  if (cachedRendererLexer === null) {
    cachedRendererLexer = new Marked({
      gfm: true,
      extensions: Latex(),
    });
  }
  return cachedRendererLexer;
}

export function lexWithRenderer(markdown: string): TokensList {
  return buildRendererLexer().lexer(markdown);
}

/**
 * `marked` normalises CRLF and lone CR to LF before tokenizing, so token offsets
 * only line up with a normalised buffer. This keeps the mapping back to the
 * caller's original source so masks land on the real characters.
 */
interface NormalizedSource {
  text: string;
  toOriginal: (index: number) => number;
}

function normalizeLineEndings(source: string): NormalizedSource {
  if (!source.includes("\r")) {
    return { text: source, toOriginal: (index) => index };
  }
  const offsets: number[] = [];
  let text = "";
  for (let index = 0; index < source.length; index++) {
    const character = source[index];
    if (character === "\r") {
      offsets.push(index);
      text += "\n";
      if (source[index + 1] === "\n") index++;
      continue;
    }
    offsets.push(index);
    text += character;
  }
  offsets.push(source.length);
  return {
    text,
    toOriginal: (index) =>
      offsets[index < offsets.length ? index : offsets.length - 1],
  };
}

function truncateAtUnfinishedConstruct(text: string): number {
  let cut = text.length;
  for (const pattern of UNFINISHED_CONSTRUCTS) {
    const match = pattern.exec(text);
    if (match && match.index < cut) cut = match.index;
  }
  const bracket = firstUnclosedBracketInText(text);
  if (bracket >= 0 && bracket < cut) cut = bracket;
  return cut;
}

/**
 * Bracket balance inside one already-editable `text` token. Code spans, links
 * and HTML never reach this function, so the only thing left to skip is an
 * escaped `\[`, which the renderer shows as a literal bracket.
 */
function firstUnclosedBracketInText(text: string): number {
  const open: number[] = [];
  for (let index = 0; index < text.length; index++) {
    const character = text[index];
    if (character === "\\") {
      index++;
      continue;
    }
    if (character === "[") open.push(index);
    else if (character === "]" && open.length > 0) open.pop();
  }
  return open.length > 0 ? open[0] : -1;
}

/**
 * Locate a token whose `raw` is a normalised copy of the source, which happens
 * to every container inside a blockquote or a list: `paragraph.raw` drops the
 * `> ` prefixes and a loose list item pads a blank line the source never had.
 * Matching verbatim fails there, so fall back to the first and last non-blank
 * lines, each trimmed the same way the renderer trimmed them. The span still
 * cannot leave `limit`.
 */
function locateByLines(
  raw: string,
  source: string,
  position: number,
  limit: number,
): SourceSpan | null {
  const lines = raw
    .split("\n")
    .map((line) => line.trimStart())
    .filter((line) => line.length > 0);
  if (lines.length === 0) return null;
  const start = source.indexOf(lines[0], position);
  if (start < 0 || start >= limit) return null;
  const last = lines[lines.length - 1];
  const lastAt = source.indexOf(last, start);
  if (lastAt < 0) return null;
  const end = Math.min(lastAt + last.length, limit);
  return end > start ? { start, end } : null;
}

/** End of the structural block that starts at or before `from`. */
function blockEndAt(source: string, from: number): number {
  for (let index = from; index < source.length; index++) {
    if (source[index] !== "\n") continue;
    if (source[index + 1] === "\n") return index;
    const next = source[index + 1];
    if (
      next === "#" ||
      next === ">" ||
      next === "|" ||
      next === "-" ||
      next === "*" ||
      next === "+"
    ) {
      return index;
    }
    if (/[0-9]/.test(next)) {
      const rest = source.slice(index + 1, index + 4);
      if (/^[0-9]{1,3}[.)]/.test(rest) || /^[0-9]{1,3} /.test(rest))
        return index;
    }
  }
  return source.length;
}

/**
 * Every `](` that never closes, excluding anything the renderer kept as code.
 * Quotes keep their `)` literal, a backslash escapes the next character, and
 * parentheses nest, so a plain "first `)` wins" scan misreads both cases.
 */
function unclosedLinkRanges(
  source: string,
  isProtected: (index: number) => boolean,
): SourceSpan[] {
  const found: SourceSpan[] = [];
  let bracket = -1;
  for (let index = 0; index < source.length; index++) {
    if (isProtected(index)) {
      bracket = -1;
      continue;
    }
    const character = source[index];
    if (character === "\\") {
      index++;
      continue;
    }
    if (character === "[") {
      bracket = index;
      continue;
    }
    if (character !== "]" || source[index + 1] !== "(" || bracket < 0) continue;

    let depth = 0;
    let quote: string | null = null;
    let closed = false;
    let cursor = index + 1;
    for (; cursor < source.length; cursor++) {
      const inner = source[cursor];
      if (inner === "\\") {
        cursor++;
        continue;
      }
      if (quote !== null) {
        if (inner === quote) quote = null;
        continue;
      }
      if (inner === '"' || inner === "'") {
        quote = inner;
        continue;
      }
      if (inner === "\n") {
        const next = source[cursor + 1];
        if (next === "\n" || next === "#" || next === ">" || next === "|") {
          break;
        }
      }
      if (inner === "(") depth++;
      else if (inner === ")") {
        depth--;
        if (depth === 0) {
          closed = true;
          break;
        }
      }
    }
    if (!closed) {
      found.push({ start: bracket, end: blockEndAt(source, bracket) });
      bracket = -1;
      continue;
    }
    bracket = -1;
    index = cursor;
  }
  return found;
}

/**
 * Each unclosed `[`, clipped to the block that contains it: a stray bracket in
 * one paragraph must not disable repairs in the next one, and it cannot cross a
 * heading, a list item or a table cell.
 */
function unclosedBracketRanges(
  source: string,
  isProtected: (index: number) => boolean,
): SourceSpan[] {
  const found: SourceSpan[] = [];
  const open: number[] = [];
  for (let index = 0; index < source.length; index++) {
    if (isProtected(index)) {
      continue;
    }
    const character = source[index];
    if (character === "\\") {
      index++;
      continue;
    }
    if (character === "\n") {
      const next = source[index + 1];
      if (
        next === undefined ||
        next === "\n" ||
        next === "#" ||
        next === ">" ||
        next === "|"
      ) {
        for (const start of open) {
          found.push({ start, end: index });
        }
        open.length = 0;
      }
      continue;
    }
    if (character === "[") open.push(index);
    else if (character === "]" && open.length > 0) open.pop();
  }
  for (const start of open) {
    found.push({ start, end: source.length });
  }
  return found;
}

/**
 * Collect the normalized-coordinate span of every region the repair may edit:
 * `text` tokens, plus the delimiter folds of `em`/`strong` nodes. Container
 * tokens recurse; every other leaf is skipped. `limit` is the end of the
 * enclosing container, and no token may be located past it.
 */
function collectEditableSpans(
  tokens: readonly Token[],
  source: string,
  cursor: number,
  limit: number,
  out: SourceSpan[],
): void {
  let position = cursor;

  for (const token of tokens) {
    const generic = token as Tokens.Generic;

    const raw = typeof generic.raw === "string" ? generic.raw : "";
    if (raw.length === 0) continue;

    // Tokens are lexed in source order, so a match at the cursor is the normal
    // case. `indexOf` only recovers whitespace the tokenizer swallowed between
    // blocks, and it must stop at the enclosing container: searching past it
    // would let a copy of this token's text inside a later code fence claim the
    // coordinates, and the fence would come out of the mask editable.
    const start = source.startsWith(raw, position)
      ? position
      : source.indexOf(raw, position);
    // A container's `raw` is a normalised copy of its children: `paragraph.raw`
    // drops `> ` prefixes and the text wrapper of a list item pads blank lines,
    // so neither has a position of its own. The children still do and must be
    // visited - skipping the subtree is exactly what left every blockquote and
    // list body unrepairable.
    const located = start >= 0 && start + raw.length <= limit;
    const end = located ? start + raw.length : position;
    const children = (generic.tokens ?? generic.items) as Token[] | undefined;

    if (!located) {
      // Rule 2: a container whose text the renderer normalised still has to be
      // reached. Locate it by its first and last non-blank line, then descend
      // with that range so its children map onto the same characters.
      const fallback = locateByLines(raw, source, position, limit);
      if (fallback === null) {
        if (children && children.length > 0) {
          collectEditableSpans(children, source, cursor, limit, out);
        }
        continue;
      }
      if (children && children.length > 0) {
        collectEditableSpans(
          children,
          source,
          fallback.start,
          fallback.end,
          out,
        );
      } else {
        out.push(fallback);
      }
      position = fallback.end;
      continue;
    }

    if (generic.type === "text") {
      // A `text` token that owns children is a container, not a run of literal
      // characters: it covers the whole list item, link destinations included.
      // Marking it editable wholesale is what let a label edit reach an `href`;
      // only the children decide, and a link or image child stays off limits.
      if (children && children.length > 0) {
        collectEditableSpans(children, source, start, end, out);
      } else {
        out.push({ start, end });
      }
    } else if (generic.type === "link" || generic.type === "image") {
      // A link keeps its destination inside `raw`, so moving a character in the
      // label can shift the label/destination boundary and rewrite the href.
      // Images carry a URL as their only meaningful payload. Both stay untouched.
    } else {
      // Only the delimiter folds of an emphasis node are editable. The interior
      // is reached through its children; opening the whole node would let a move
      // jump into a nested link destination or an inline code span.
      if (generic.type === "em" || generic.type === "strong") {
        const opening = /^[*_]+/.exec(raw)?.[0].length ?? 0;
        const closing = /[*_]+$/.exec(raw)?.[0].length ?? 0;
        if (opening > 0) out.push({ start, end: start + opening });
        if (closing > 0) out.push({ start: end - closing, end });
      }
      if (children && children.length > 0) {
        collectEditableSpans(children, source, start, end, out);
      }
    }

    position = end;
  }
}

/**
 * Rule 1: a region that must stay byte-identical is collected on its own and
 * subtracted from whatever the editable pass claimed. Ownership therefore runs
 * downhill - a parent that covers a link can no longer make its `href` editable,
 * because the link's own span is protected afterwards.
 *
 * Link labels are protected together with their destination: moving a character
 * inside `[label]` shifts the label/destination boundary and can rewrite the
 * `href`, which the review forbids outright.
 */
function collectProtectedSpans(
  tokens: readonly Token[],
  source: string,
  position: number,
  limit: number,
  out: SourceSpan[],
): void {
  let cursor = position;
  for (const token of tokens) {
    const generic = token as Tokens.Generic;
    const raw = typeof generic.raw === "string" ? generic.raw : "";
    if (raw.length === 0) continue;

    const start = source.startsWith(raw, cursor)
      ? cursor
      : source.indexOf(raw, cursor);
    const children = (generic.tokens ?? generic.items) as Token[] | undefined;
    const fallback =
      start < 0 || start + raw.length > limit
        ? locateByLines(raw, source, cursor, limit)
        : null;
    const span =
      start >= 0 && start + raw.length <= limit
        ? { start, end: start + raw.length }
        : fallback;

    if (span === null) {
      if (children && children.length > 0) {
        collectProtectedSpans(children, source, cursor, limit, out);
      }
      continue;
    }

    const atomic =
      generic.type === "link" ||
      generic.type === "image" ||
      generic.type === "code" ||
      generic.type === "codespan" ||
      generic.type === "html" ||
      generic.type === "table";
    if (atomic) {
      out.push(span);
      cursor = span.end;
      continue;
    }

    if (children && children.length > 0) {
      collectProtectedSpans(children, source, span.start, span.end, out);
    }
    cursor = span.end;
  }
}

/**
 * Produce the masks the repair pass consumes, with the editable region decided
 * by the renderer rather than by a hand-written scanner.
 */
export function buildRendererMasks(markdown: string): RendererMasks {
  const normalized = normalizeLineEndings(markdown);
  const source = normalized.text;
  const length = markdown.length;
  const protectedText = new Uint8Array(length).fill(1);
  const paragraphReset = new Uint8Array(length);

  const tokens = lexWithRenderer(source) as unknown as Token[];
  const spans: SourceSpan[] = [];
  collectEditableSpans(tokens, source, 0, source.length, spans);

  const protectedSpans: SourceSpan[] = [];
  collectProtectedSpans(tokens, source, 0, source.length, protectedSpans);

  // Rule 4: a construct that is still arriving re-interprets what follows, but
  // only inside its own block. Code is excluded from the scan entirely, so a
  // `[a](` shown as code cannot disable the paragraph after it.
  const protectedMask = new Uint8Array(source.length);
  for (const span of protectedSpans) {
    protectedMask.fill(
      1,
      Math.max(0, span.start),
      Math.min(span.end, source.length),
    );
  }
  const isProtected = (index: number) => protectedMask[index] === 1;

  const brackets = unclosedBracketRanges(source, isProtected);
  const links = unclosedLinkRanges(source, isProtected);
  const unclosed = [...brackets, ...links];

  for (const span of spans) {
    const text = source.slice(span.start, span.end);
    let cut = truncateAtUnfinishedConstruct(text);
    for (const range of unclosed) {
      if (span.start < range.end && span.end > range.start) {
        cut = Math.min(cut, Math.max(0, range.start - span.start));
      }
    }
    if (cut <= 0) continue;
    const start = normalized.toOriginal(span.start);
    const end = normalized.toOriginal(span.start + cut);
    if (end > start) protectedText.fill(0, start, end);
  }

  // Rule 1: protection wins over any editable range that contains it.
  for (const span of protectedSpans) {
    const start = normalized.toOriginal(span.start);
    const end = normalized.toOriginal(span.end);
    if (end > start) protectedText.fill(1, start, end);
  }

  // `\(...\)` and `\[...\]` never become LaTeX tokens in this renderer, so their
  // interior has to be reserved explicitly; a formula must not be repaired.
  for (const pattern of PAIRED_DELIMITERS) {
    pattern.lastIndex = 0;
    let match = pattern.exec(source);
    while (match) {
      const start = normalized.toOriginal(match.index);
      const end = normalized.toOriginal(match.index + match[0].length);
      if (end > start) protectedText.fill(1, start, end);
      match = pattern.exec(source);
    }
  }

  // Entering protected source closes the delimiter stack, so an opener can never
  // pair across a code span, a link, or another block structure.
  for (let index = 0; index < length; index++) {
    if (protectedText[index] && (index === 0 || !protectedText[index - 1])) {
      paragraphReset[index] = 1;
    }
  }

  return { protectedText, paragraphReset };
}

function countEmphasis(tokens: readonly Token[]): number {
  let total = 0;
  for (const token of tokens) {
    const generic = token as Tokens.Generic;
    if (generic.type === "em" || generic.type === "strong") total++;
    const children = (generic.tokens ?? generic.items) as Token[] | undefined;
    if (children && children.length > 0) total += countEmphasis(children);
  }
  return total;
}

/** Asterisks and underscores that still reach the reader as literal text. */
function countLiteralMarkers(tokens: readonly Token[]): number {
  let total = 0;
  for (const token of tokens) {
    const generic = token as Tokens.Generic;
    if (generic.type === "text" && typeof generic.raw === "string") {
      for (const character of generic.raw) {
        if (character === "*" || character === "_") total++;
      }
    }
    const children = (generic.tokens ?? generic.items) as Token[] | undefined;
    if (children && children.length > 0) total += countLiteralMarkers(children);
  }
  return total;
}

/**
 * Accept a rewrite only when the renderer itself reports a better result.
 *
 * Pairing, and therefore the validity of a moved punctuation run, is the
 * renderer's decision: a candidate that produces more emphasis nodes wins, one
 * that loses emphasis is discarded, and a tie is broken only by consuming
 * literal `*`/`_` that used to reach the reader as text. Candidates whose
 * validity depends on another block therefore stay unchanged.
 *
 * A rewrite that raises the total by turning punctuation into a node of its own
 * is rejected separately, because `**.**` renders as bold text with no content
 * and the count alone cannot tell that apart from a real improvement.
 *
 * Repairs are idempotent for the same reason. Once a span renders as emphasis it
 * belongs to an `em`/`strong` node whose text no longer holds the punctuation
 * that triggered the move.
 */
export function rewriteImprovesRendering(
  before: string,
  after: string,
): boolean {
  const beforeTokens = lexWithRenderer(normalizeLineEndings(before).text);
  const afterTokens = lexWithRenderer(normalizeLineEndings(after).text);

  const beforeEmphasis = countEmphasis(beforeTokens);
  const afterEmphasis = countEmphasis(afterTokens);

  // Losing a node means the delimiters stopped pairing, so the asterisks are
  // now visible to the reader.
  if (afterEmphasis < beforeEmphasis) return false;

  // A node whose content is nothing but punctuation shows up as a stray `**.**`.
  // Never let a rewrite manufacture one, no matter what the totals say.
  if (countEmptyEmphasis(afterTokens) > countEmptyEmphasis(beforeTokens)) {
    return false;
  }

  if (afterEmphasis > beforeEmphasis) return true;

  // Same node count, but the punctuation no longer sits inside a node. This is
  // the improvement the nested counterexample asks for, and it is invisible to
  // the counts above.
  if (
    countPunctuationEndedEmphasis(afterTokens) <
    countPunctuationEndedEmphasis(beforeTokens)
  ) {
    return true;
  }

  return countLiteralMarkers(afterTokens) < countLiteralMarkers(beforeTokens);
}

/**
 * Emphasis nodes whose body ends with punctuation, e.g. `<em>italic。</em>`.
 * Moving that punctuation past the closing run produces the same node count, so
 * the totals cannot tell the two apart; this counter can, and the review asks
 * for exactly that move in its nested-delimiter counterexample.
 */
function countPunctuationEndedEmphasis(tokens: readonly Token[]): number {
  let total = 0;
  for (const token of tokens) {
    const generic = token as Tokens.Generic;
    if (generic.type === "em" || generic.type === "strong") {
      const raw = typeof generic.raw === "string" ? generic.raw : "";
      const body = raw.replace(/^[*_]+/, "").replace(/[*_]+$/, "");
      if (body.length > 0 && /\p{P}$/u.test(body)) total++;
    }
    const children = (generic.tokens ?? generic.items) as Token[] | undefined;
    if (children && children.length > 0) {
      total += countPunctuationEndedEmphasis(children);
    }
  }
  return total;
}

/**
 * Emphasis nodes that hold no letter or digit, e.g. `**.**`. They render as a
 * bold fragment with no text, which is never what a repair is aiming for.
 */
function countEmptyEmphasis(tokens: readonly Token[]): number {
  let total = 0;
  for (const token of tokens) {
    const generic = token as Tokens.Generic;
    if (generic.type === "em" || generic.type === "strong") {
      const raw = typeof generic.raw === "string" ? generic.raw : "";
      const body = raw.replace(/^[*_]+/, "").replace(/[*_]+$/, "");
      if (body.length > 0 && !/[\p{L}\p{N}]/u.test(body)) total++;
    }
    const children = (generic.tokens ?? generic.items) as Token[] | undefined;
    if (children && children.length > 0) {
      total += countEmptyEmphasis(children);
    }
  }
  return total;
}

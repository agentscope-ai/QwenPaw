import {
  Marked,
  type MarkedExtension,
  type Token,
  type Tokens,
  type TokensList,
} from "marked";
import markedFootnote from "marked-footnote";
import Latex from "@ant-design/x-markdown/plugins/Latex";

/**
 * CJK emphasis repair must be bounded by the grammar the chat bubble actually
 * renders with, not by an approximation of it.
 *
 * The bubble renders through the `Markdown` component of `@agentscope-ai/chat`,
 * which constructs `new Marked()` with GFM on, `breaks` off, and registers the
 * `Latex` plugin together with `marked-footnote`. This module rebuilds exactly
 * that configuration and derives every editable region from its tokens, so the
 * repair pass can only touch source the renderer classified as inline text (or
 * as the delimiter folds of an existing emphasis node).
 *
 * Everything else is out of reach: fenced and inline code, HTML, tables, link
 * destinations and titles, LaTeX spans, footnote markers, and any source no
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

const FOOTNOTE_MARKER = /^\[\^[^\]]+\]:[ \t]*/;

export interface SourceSpan {
  start: number;
  end: number;
}

export interface RendererMasks {
  protectedText: Uint8Array;
  paragraphReset: Uint8Array;
}

export function buildRendererLexer(): Marked {
  return new Marked(
    { gfm: true },
    ...(Latex() as MarkedExtension[]),
    markedFootnote() as never,
  );
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

function firstUnclosedBracket(text: string): number {
  const open: number[] = [];
  for (let index = 0; index < text.length; index++) {
    if (text[index] === "[") open.push(index);
    else if (text[index] === "]" && open.length > 0) open.pop();
  }
  return open.length > 0 ? open[0] : -1;
}

/**
 * A link whose `](` never reaches a closing `)` is still streaming in, so its
 * label and the rest of its paragraph can still change meaning. Balancing `[`
 * against `]` misses this entirely: `[a](` has both brackets. A blank line ends
 * the paragraph, so an unterminated link cannot reach past it.
 */
function firstUnclosedLink(
  text: string,
): { start: number; end: number } | null {
  for (let index = 0; index < text.length - 1; index++) {
    if (text[index] !== "]" || text[index + 1] !== "(") continue;
    const bracket = text.lastIndexOf("[", index);
    if (bracket < 0) continue;
    let depth = 0;
    let closed = false;
    let blockEnd = text.length;
    for (let cursor = index + 1; cursor < text.length; cursor++) {
      const character = text[cursor];
      if (character === "\n" && text[cursor + 1] === "\n") {
        blockEnd = cursor;
        break;
      }
      if (character === "(") depth++;
      else if (character === ")") {
        depth--;
        if (depth === 0) {
          closed = true;
          break;
        }
      }
    }
    if (!closed) return { start: bracket, end: blockEnd };
  }
  return null;
}

function truncateAtUnfinishedConstruct(text: string): number {
  let cut = text.length;
  for (const pattern of UNFINISHED_CONSTRUCTS) {
    const match = pattern.exec(text);
    if (match && match.index < cut) cut = match.index;
  }
  const bracket = firstUnclosedBracket(text);
  if (bracket >= 0 && bracket < cut) cut = bracket;
  return cut;
}

/**
 * Collect the normalized-coordinate span of every region the repair may edit:
 * `text` tokens, and the full raw extent of `em`/`strong` nodes so their own
 * delimiter folds stay reachable. Container tokens recurse; every other leaf is
 * skipped.
 */
function collectEditableSpans(
  tokens: readonly Token[],
  source: string,
  cursor: number,
  out: SourceSpan[],
): void {
  let position = cursor;

  for (const token of tokens) {
    const generic = token as Tokens.Generic;

    // The `footnotes` container carries a synthetic raw value ("Footnotes") that
    // never appears in the source, so it must not advance the cursor.
    if (generic.type === "footnotes") {
      const items = (
        generic.tokens?.length ? generic.tokens : generic.items
      ) as Token[] | undefined;
      if (items) collectEditableSpans(items, source, position, out);
      continue;
    }

    const raw = typeof generic.raw === "string" ? generic.raw : "";
    if (raw.length === 0) continue;

    const start = source.startsWith(raw, position)
      ? position
      : source.indexOf(raw, position);
    if (start < 0) continue;
    const end = start + raw.length;

    if (generic.type === "footnote") {
      // A footnote body is its own pairing domain: a marker opened inside the
      // body must not consume a delimiter from the surrounding paragraph.
      const marker = /^\[\^[^\]]+\]:[ \t]*/.exec(raw);
      const bodyStart = start + (marker ? marker[0].length : 0);
      const body = source.slice(bodyStart, end);
      const collected = out.length;
      collectEditableSpans(lexWithRenderer(body) as Token[], body, 0, out);
      for (let index = collected; index < out.length; index++) {
        out[index].start += bodyStart;
        out[index].end += bodyStart;
      }
    } else if (generic.type === "text") {
      out.push({ start, end });
    } else if (generic.type === "link" || generic.type === "image") {
      // A link keeps its destination inside `raw`, so moving a character in the
      // label can shift the label/destination boundary and rewrite the href.
      // Images carry a URL as their only meaningful payload. Both stay untouched.
    } else {
      // Emphasis keeps its delimiter folds editable; anything else only lends
      // us its children.
      if (generic.type === "em" || generic.type === "strong") {
        out.push({ start, end });
      }
      const children = (generic.tokens ?? generic.items) as Token[] | undefined;
      if (children && children.length > 0) {
        collectEditableSpans(children, source, start, out);
      }
    }

    position = end;
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

  const spans: SourceSpan[] = [];
  collectEditableSpans(lexWithRenderer(source), source, 0, spans);

  // An unclosed `[` or an unterminated `](` means the rest is still arriving: a
  // link that closes later re-interprets everything after it, so nothing past
  // that point may be repaired. Scanning per span cannot see this, because
  // `**content.**` becomes its own `strong` token with no bracket inside it.
  const bracketLimit = firstUnclosedBracket(source);
  const limit = bracketLimit < 0 ? source.length : bracketLimit;
  const unclosedLink = firstUnclosedLink(source);

  for (const span of spans) {
    const text = source.slice(span.start, span.end);
    let cut = Math.min(truncateAtUnfinishedConstruct(text), limit - span.start);
    // A dangling link owns the text from its `[` to the end of its paragraph;
    // later blocks stay repairable.
    if (
      unclosedLink &&
      span.start < unclosedLink.end &&
      span.end > unclosedLink.start
    ) {
      cut = Math.min(cut, Math.max(0, unclosedLink.start - span.start));
    }
    if (cut <= 0) continue;
    const start = normalized.toOriginal(span.start);
    const end = normalized.toOriginal(span.start + cut);
    if (end > start) protectedText.fill(0, start, end);
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

/**
 * A footnote keeps its body in `raw` instead of child tokens, so it has to be
 * re-lexed for any count to see what the reader actually gets. Skipping this is
 * how a repaired footnote body used to look unchanged.
 */
function footnoteBody(token: Tokens.Generic): string | null {
  const raw = typeof token.raw === "string" ? token.raw : "";
  const marker = FOOTNOTE_MARKER.exec(raw);
  return marker ? raw.slice(marker[0].length) : null;
}

function countEmphasis(tokens: readonly Token[]): number {
  let total = 0;
  for (const token of tokens) {
    const generic = token as Tokens.Generic;
    if (generic.type === "em" || generic.type === "strong") total++;
    if (generic.type === "footnote") {
      const body = footnoteBody(generic);
      if (body) total += countEmphasis(lexWithRenderer(body) as Token[]);
    }
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
    if (generic.type === "footnote") {
      const body = footnoteBody(generic);
      if (body) {
        total += countLiteralMarkers(lexWithRenderer(body) as Token[]);
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
  if (afterEmphasis !== beforeEmphasis) return afterEmphasis > beforeEmphasis;
  return countLiteralMarkers(afterTokens) < countLiteralMarkers(beforeTokens);
}

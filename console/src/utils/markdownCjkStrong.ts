/**
 * CJK emphasis recovery.
 *
 * CommonMark only accepts a closing delimiter run that is right-flanking, so
 * ``**中文。**后`` never parses: the run is preceded by CJK punctuation and
 * followed by a CJK letter, so it is not right-flanking and cannot close. The
 * author's intent is unambiguous, so recover a `strong` token instead of
 * rewriting the source text.
 *
 * Recovery runs after the lexer and before the parser (`processAllTokens`).
 * That placement is what makes the cost small and the rule exact:
 *
 *   - whatever `**` survives inside a `text` token is, by definition, a
 *     delimiter stock did not consume, so the token tree itself answers
 *     "what did stock already pair" and no second lex pass is needed;
 *   - runs stock consumed became `strong` tokens, so they are structurally
 *     out of reach and cannot be re-paired — ``**甲。**乙**丙，**丁`` keeps
 *     the `乙` pair stock produced;
 *   - two independent spans in one paragraph still recover, because the guard
 *     is per delimiter run rather than per paragraph.
 *
 * Shape: on each inline token array, the raw strings are concatenated (with
 * codespan/link/image payloads masked one-for-one so their contents stay
 * literal), a delimiter scan runs once, and matched ranges are rebuilt into
 * `strong` tokens that keep any inline nodes they span.
 *
 * Scope (agreed with the reviewer):
 *   - double delimiters only (`**` and `__`); single `*` / `_` untouched
 *   - the character before the closing run must be CJK punctuation
 *   - the character after the closing run must be a CJK letter
 *   - the body must carry a letter or digit, one delimiter pair, no nested
 *     emphasis, and no unclosed code fence or bracket
 *   - complete inline code and links may occur inside the body
 * Anything else is left exactly as stock produced it.
 */

/**
 * PROTOTYPE — post-parse recovery, for feasibility measurement only.
 *
 * Hooks `processAllTokens` (runs after the lexer, before the parser) and
 * rewrites *inline token arrays*: whatever `**` survives inside a `text` token
 * is, by definition, a delimiter stock did not consume, so the tree itself
 * answers "what did stock pair" without a second lex pass.
 *
 * Cross-token recovery: `**甲 \`code\`。**后` is lexed into
 * `[text("**甲 "), codespan, text("。**后")]`. The opening and closing runs sit
 * in two different text tokens, so the match is found on the concatenated raw
 * of the array and the strong is rebuilt around the tokens in between.
 */

import { type MarkedExtension, type Token, type Tokens } from "marked";

/** Single CJK punctuation characters that may close a run. */
const PUNCT = "。，、；：！？…‥·—～「」『』（）〔〕【】《》〈〉“”‘’";

/** A closing run may also follow a sentence mark that sits before a bracket. */
const PUNCT_SEQ = `(?:[${PUNCT}]|[。！？；：，、…]］)`;

/**
 * CJK letters that may follow the closing run. Combining marks (U+3099/U+309A)
 * are excluded: they are not a following letter, they decorate the previous one.
 */
const CJK_LETTER =
  "\\u3400-\\u4DBF\\u4E00-\\u9FFF\\uF900-\\uFAFF\\u3040-\\u3096\\u309B-\\u30FF\\uAC00-\\uD7AF\\u{20000}-\\u{2A6DF}";

/** Body must carry at least one letter or digit, not bare punctuation. */
const HAS_WORD = /[\p{L}\p{N}]/u;

/** Inline token types a recovered body may span. Anything else is foreign
 * structure (math, HTML, strikethrough) that stock deliberately left alone. */
const SPANNABLE = new Set(["text", "codespan", "link", "image"]);

function textToken(raw: string): Tokens.Text {
  return { type: "text", raw, text: raw, escaped: false };
}

function markerPattern(marker: string): RegExp {
  const escaped = marker[0] === "*" ? "\\*" : "_";
  return new RegExp(
    `(?<![${escaped}])${escaped}${escaped}([^\\s*_][^*_\\n]*?)${PUNCT_SEQ}${escaped}${escaped}(?=[${CJK_LETTER}])`,
    "gu",
  );
}

const PATTERNS: ReadonlyArray<RegExp> = [
  markerPattern("**"),
  markerPattern("__"),
];

type Hit = { start: number; end: number };

function findHits(source: string): Hit[] {
  const hits: Hit[] = [];
  for (const pattern of PATTERNS) {
    pattern.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(source)) !== null) {
      const start = match.index;
      const end = start + match[0].length;
      if (hits.some((hit) => start < hit.end && end > hit.start)) continue;
      const body = source.slice(start + 2, end - 2);
      if (!HAS_WORD.test(body)) continue;
      hits.push({ start, end });
    }
  }
  hits.sort((left, right) => left.start - right.start);
  return hits;
}

type Span = { start: number; end: number };

function spansOf(tokens: Token[]): Span[] {
  let cursor = 0;
  return tokens.map((token) => {
    const raw = (token as Token & { raw?: string }).raw ?? "";
    const span = { start: cursor, end: cursor + raw.length };
    cursor += raw.length;
    return span;
  });
}

function rawOf(token: Token): string {
  return (token as Token & { raw?: string }).raw ?? "";
}

/** Tokens covering `[from, to)`, slicing partial text tokens and keeping the rest intact. */
function sliceTokens(
  tokens: Token[],
  spans: Span[],
  from: number,
  to: number,
): Token[] {
  const out: Token[] = [];
  for (let index = 0; index < tokens.length; index += 1) {
    const start = Math.max(spans[index].start, from);
    const end = Math.min(spans[index].end, to);
    if (end <= start) continue;
    const token = tokens[index];
    if (start === spans[index].start && end === spans[index].end) {
      out.push(token);
      continue;
    }
    const piece = rawOf(token).slice(
      start - spans[index].start,
      end - spans[index].start,
    );
    if (piece) out.push(textToken(piece));
  }
  return out;
}

function tokenIndexAt(spans: Span[], offset: number): number {
  for (let index = 0; index < spans.length; index += 1) {
    if (offset >= spans[index].start && offset < spans[index].end) return index;
  }
  return -1;
}

/** Rewrite one inline token array in place. Returns true when it changed. */
function rewriteInline(tokens: Token[]): boolean {
  if (tokens.length === 0) return false;
  const concat = tokens.map(rawOf).join("");
  if (!concat.includes("**") && !concat.includes("__")) return false;

  // Scan a same-length copy where codespan/link/image payloads are masked, so a
  // delimiter-like sequence inside them cannot start or close a match. Offsets
  // stay valid because every masked character is replaced one-for-one.
  //
  // Deliberately no `u` flag: with it the pattern matches whole code points,
  // so an astral character (emoji, U+1D11E) would collapse from two UTF-16 code
  // units to one mask character and every later offset would shift. Without it
  // each code unit is replaced individually and the length is preserved exactly.
  const masked = tokens
    .map((token) =>
      token.type === "text"
        ? rawOf(token)
        : rawOf(token).replace(/[^\n]/g, "\u0001"),
    )
    .join("");

  const hits = findHits(masked);
  if (!hits.length) return false;

  const spans = spansOf(tokens);
  const usable = hits.filter((hit) => {
    const openIndex = tokenIndexAt(spans, hit.start);
    const closeIndex = tokenIndexAt(spans, hit.end - 1);
    if (openIndex < 0 || closeIndex < 0) return false;
    // Both delimiter runs must live in plain text tokens, never inside a
    // codespan/link/HTML token where the characters are literal content.
    if (
      tokens[openIndex].type !== "text" ||
      tokens[closeIndex].type !== "text"
    ) {
      return false;
    }
    // Everything the body spans must be ordinary inline content; math, raw
    // HTML and strikethrough are structures stock left alone on purpose.
    for (let index = openIndex; index <= closeIndex; index += 1) {
      if (!SPANNABLE.has(tokens[index].type)) return false;
    }
    // A text token sitting between an opening and a *matching* closing raw-HTML
    // tag is the content of that element (`<kbd>**甲。**乙</kbd>`), which stock
    // leaves literal. Only a real tag pair counts: `<br>` is a void element, so
    // in `**甲。**乙<br>**丙。**丁<br>` the delimiters sit between two `<br>`
    // tokens and must still recover.
    if (
      tokens[openIndex - 1]?.type === "html" &&
      tokens[closeIndex + 1]?.type === "html"
    ) {
      const opening = /^<([a-zA-Z][a-zA-Z0-9-]*)(?:\s[^>]*)?>$/.exec(
        tokens[openIndex - 1].raw,
      );
      const closing = /^<\/([a-zA-Z][a-zA-Z0-9-]*)\s*>$/.exec(
        tokens[closeIndex + 1].raw,
      );
      if (
        opening &&
        closing &&
        opening[1].toLowerCase() === closing[1].toLowerCase()
      ) {
        return false;
      }
    }
    // An unclosed backtick inside the body means stock never produced a
    // codespan there; recovering across it would contradict stock.
    const body = concat.slice(hit.start + 2, hit.end - 2);
    const ticks = (body.match(/`/gu) ?? []).length;
    if (ticks % 2 === 1) return false;
    const opens = (body.match(/\[/gu) ?? []).length;
    const closes = (body.match(/\]/gu) ?? []).length;
    if (opens !== closes) return false;
    return true;
  });
  if (!usable.length) return false;

  const out: Token[] = [];
  let cursor = 0;
  for (const hit of usable) {
    if (hit.start < cursor) continue;
    out.push(...sliceTokens(tokens, spans, cursor, hit.start));
    const inner = sliceTokens(tokens, spans, hit.start + 2, hit.end - 2);
    out.push({
      type: "strong",
      raw: concat.slice(hit.start, hit.end),
      text: inner.map(rawOf).join(""),
      tokens: inner,
    } as Tokens.Strong);
    cursor = hit.end;
  }
  out.push(...sliceTokens(tokens, spans, cursor, concat.length));

  tokens.splice(0, tokens.length, ...out);
  return true;
}

/** Walk the block tree; every inline array is rewritten once. */
function walkBlocks(tokens: Token[] | undefined): void {
  if (!tokens) return;
  for (const token of tokens) {
    if (token.type === "link" || token.type === "image") continue;
    // Table cells carry their own inline token arrays; they are not reachable
    // through `tokens` or `items`, so they have to be walked explicitly. Each
    // cell array is already inline, so it goes straight to `rewriteInline`.
    if (token.type === "table") {
      const table = token as Tokens.Table;
      const rewriteCell = (cell: { tokens?: Token[] } | undefined) => {
        if (!cell?.tokens) return;
        if (!rewriteInline(cell.tokens)) walkBlocks(cell.tokens);
      };
      for (const cell of table.header) rewriteCell(cell);
      for (const row of table.rows) {
        for (const cell of row) rewriteCell(cell);
      }
      continue;
    }
    const nested = (token as Token & { tokens?: Token[] }).tokens;
    if (Array.isArray(nested)) {
      if (rewriteInline(nested)) continue;
      walkBlocks(nested);
    }
    const items = (token as Token & { items?: Token[] }).items;
    if (Array.isArray(items)) {
      for (const item of items) {
        const inner = (item as Token & { tokens?: Token[] }).tokens;
        if (Array.isArray(inner)) walkBlocks(inner);
      }
    }
  }
}

export function cjkStrongExtension(): MarkedExtension {
  return {
    hooks: {
      processAllTokens(tokens: Token[]) {
        walkBlocks(tokens);
        return tokens;
      },
    },
  } as MarkedExtension;
}

/**
 * Recovery only, without the scanner skip. Exported for the equivalence check
 * that proves the skip cannot change output; not used by the app.
 */
export function cjkRecoveryOnlyExtension(): MarkedExtension {
  return {
    hooks: {
      processAllTokens(tokens: Token[]) {
        walkBlocks(tokens);
        return tokens;
      },
    },
  } as MarkedExtension;
}

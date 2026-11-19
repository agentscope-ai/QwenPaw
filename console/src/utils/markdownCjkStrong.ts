import type { MarkedExtension, Tokenizer, Tokens } from "marked";

/**
 * CJK emphasis recovery.
 *
 * CommonMark only accepts a closing delimiter run that is right-flanking, so
 * ``**中文。**后`` never parses: the run is preceded by CJK punctuation and
 * followed by a CJK letter, so it is not right-flanking and cannot close.
 * The author's intent is unambiguous, so recover a `strong` token instead of
 * rewriting the source text.
 *
 * Recover only when the suffix index rules out a native close. Ambiguous
 * candidates always go to stock, regardless of paragraph length.
 *
 * Scope (agreed with the reviewer):
 *   - double delimiters only (`**` and `__`); single `*` / `_` untouched
 *   - the character before the closing run must be CJK punctuation
 *   - the character after the closing run must be a CJK letter
 *   - a body with a letter or number, one delimiter pair, no nested emphasis
 *   - complete inline code and links may occur inside the body
 * Anything else is handed to the stock tokenizer unchanged, so the rendered
 * output stays identical to stock marked.
 */

const CJK_PUNCT_BEFORE =
  /[。，、；：！？…‥·—～「」『』（）〔〕【】《》〈〉“”‘’]/u;
const CJK_SENTENCE_BEFORE_BRACKET = /[。！？；：，、…]］/u;
const CJK_LETTER_AFTER =
  /(?=\p{L})[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7a3\uf900-\ufaff]/u;
const SUPPLEMENTARY_HAN_LETTER = /(?=\p{L})\p{Script=Han}/u;

/** Upper bound of an emphasis body this recovery is willing to look at. */
const MAX_BODY = 4096;
const POSSIBLE_PROTECTED_INLINE = /[`$<~]|\[|\\\(|(?:https?|ftp):\/\/|www\./iu;

type Delimiter = "**" | "__";
type Candidate = {
  delimiter: Delimiter;
  offset: number;
  closingEnd: number;
  content: string;
  maySkipOpening: boolean;
};

function isCjkFollower(src: string, offset: number): boolean {
  const codePoint = src.codePointAt(offset);
  if (codePoint === undefined) return false;
  const character = String.fromCodePoint(codePoint);
  return codePoint > 0xffff
    ? SUPPLEMENTARY_HAN_LETTER.test(character)
    : CJK_LETTER_AFTER.test(character);
}

/**
 * Record the minimum native delimiter balance after each double opener.
 * Use marked's mask here, even if recovery has a more precise code boundary.
 */
function indexSuffixBalance(masked: string, rule: RegExp): Map<number, number> {
  const suffixBalance = new Map<number, number>();

  // Start at index 1 to bypass the anchored alternative. The space at index 1
  // supplies the left context for a run at the start of the masked source.
  const scan = new RegExp(rule);
  scan.lastIndex = 1;
  const runs = Array.from(`  ${masked}`.matchAll(scan)).filter(
    ([, closePunct, closeText, open, openPunct, bothPunct, bothText]) =>
      closePunct || closeText || open || openPunct || bothPunct || bothText,
  );
  let minimum = 0;
  for (let i = runs.length - 1; i >= 0; i -= 1) {
    const run = runs[i];
    const opening = run[3] || run[4];
    const ambiguous = run[5] || run[6];
    const width = (opening || ambiguous || run[1] || run[2]).length;
    if (width === 2) {
      suffixBalance.set(run.index + run[0].length - width - 2, minimum);
    }

    if (opening) {
      minimum = Math.min(0, minimum + width);
    } else if (!ambiguous || (2 + width) % 3 !== 0) {
      // A two-character opener is subject to marked's rule of three.
      minimum -= width;
    }
  }
  return suffixBalance;
}

/**
 * Walk only the bounded recovery window for candidates containing inline nodes.
 * Skip complete code and explicit links using marked's tokenizers. Stop at
 * unsupported syntax or the first run outside those nodes.
 */
function findCloserAroundInlineNodes(
  tokenizer: Tokenizer,
  src: string,
): number {
  const boundary = /[`[*_]/gu;
  let foundNode = false;
  let position = 2;
  boundary.lastIndex = position;
  for (let match = boundary.exec(src); match; match = boundary.exec(src)) {
    const gap = src.slice(position, match.index);
    if (gap.includes("\\") || POSSIBLE_PROTECTED_INLINE.test(gap)) return -1;
    if (match[0] === "*" || match[0] === "_") {
      return foundNode ? match.index : -1;
    }
    if (match[0] === "[" && src.charAt(match.index - 1) === "!") return -1;
    const remainder = src.slice(match.index);
    const { state } = tokenizer.lexer;
    const { inLink, inRawBlock } = state;
    let token: Tokens.Codespan | Tokens.Link | Tokens.Image | undefined;
    try {
      token =
        match[0] === "`"
          ? tokenizer.codespan(remainder)
          : tokenizer.link(remainder);
    } finally {
      // The link probe parses the label; probing must not change lexer state.
      state.inLink = inLink;
      state.inRawBlock = inRawBlock;
    }
    if (!token || (token.type !== "codespan" && token.type !== "link")) {
      return -1;
    }
    foundNode = true;
    position = match.index + token.raw.length;
    boundary.lastIndex = position;
  }
  return -1;
}

/**
 * The agreed shape, or `null`.
 *
 * This runs on every inline position marked offers us, so it stays cheap: the
 * delimiter and prefix checks reject almost everything before any scan, and
 * only the first following run is ever inspected.
 */
function findCandidate(
  tokenizer: Tokenizer,
  src: string,
  maskedSrc: string,
  prevChar: string,
): Candidate | null {
  const delimiter = src.slice(0, 2);
  if (delimiter !== "**" && delimiter !== "__") return null;
  // Link labels and image alt text are parsed with `inLink` set; leaving them
  // to the stock tokenizer keeps `alt`, `href` and `title` byte-identical.
  if (tokenizer.lexer.state.inLink || tokenizer.lexer.state.inRawBlock) {
    return null;
  }
  const marker = delimiter.charAt(0);
  if (src.charAt(2) === marker) return null;
  const offset = maskedSrc.length - src.length;
  // The lexer can retry after consuming part of a longer run. Escaped
  // punctuation is masked as `++` and can also hide an adjacent marker.
  if (
    offset < 0 ||
    !maskedSrc.startsWith(delimiter, offset) ||
    maskedSrc.charAt(offset - 1) === marker ||
    (!prevChar && offset >= 2 && maskedSrc.startsWith("++", offset - 2))
  ) {
    return null;
  }

  // Reuse marked's opening conditions, including whitespace and intraword `_`.
  const opener = tokenizer.rules.inline.emStrongLDelim.exec(src);
  if (
    !opener ||
    (opener[3] && tokenizer.rules.other.unicodeAlphaNumeric.test(prevChar)) ||
    ((opener[1] || opener[2]) &&
      prevChar &&
      !tokenizer.rules.inline.punctuation.test(prevChar))
  ) {
    return null;
  }
  // Limit the actual search, not just the distance of a successful match.
  const window = maskedSrc.slice(offset + 2, offset + 4 + MAX_BODY);
  const hit = window.search(/[*_]/u);
  if (hit <= 0) return null;
  const hasInlineNodes = POSSIBLE_PROTECTED_INLINE.test(src.slice(2, hit + 2));
  const closingStart = hasInlineNodes
    ? findCloserAroundInlineNodes(tokenizer, src.slice(0, MAX_BODY + 4))
    : hit + 2;
  if (closingStart <= 2) return null;
  const closingEnd = closingStart + 2;
  // A fullwidth bracket is only eligible after CJK sentence punctuation.
  const hasCjkPunctuation =
    CJK_PUNCT_BEFORE.test(src.charAt(closingStart - 1)) ||
    CJK_SENTENCE_BEFORE_BRACKET.test(src.slice(closingStart - 2, closingStart));
  if (
    !src.startsWith(delimiter, closingStart) ||
    src.charAt(closingEnd) === marker ||
    !hasCjkPunctuation ||
    !isCjkFollower(src, closingEnd)
  ) {
    return null;
  }
  const content = src.slice(2, closingStart);
  if (content.includes("\n\n") || !/[\p{L}\p{N}]/u.test(content)) return null;
  // Marked's anchored alternative can skip a single marker only when the
  // first run in its mask is the opposite double delimiter.
  const opposite = delimiter === "**" ? "__" : "**";
  const maySkipOpening = window.startsWith(opposite, hit);
  return { delimiter, offset, closingEnd, content, maySkipOpening };
}

export function cjkStrongExtension(): MarkedExtension {
  // A lexer is created per parse. Reuse the index while it is consuming the
  // same long inline source, including after nested inline parses return.
  const indexes = new WeakMap<
    Tokenizer["lexer"],
    Record<Delimiter, Map<string, Map<number, number>>>
  >();
  return {
    tokenizer: {
      emStrong(this: Tokenizer, src: string, maskedSrc: string, prevChar = "") {
        const candidate = findCandidate(this, src, maskedSrc, prevChar);
        if (!candidate || this.options.pedantic) return false;

        let byDelimiter = indexes.get(this.lexer);
        if (!byDelimiter) {
          byDelimiter = { "**": new Map(), __: new Map() };
          indexes.set(this.lexer, byDelimiter);
        }
        const index = byDelimiter[candidate.delimiter];
        let suffixBalance = index.get(maskedSrc);
        if (!suffixBalance) {
          const rule =
            candidate.delimiter === "**"
              ? this.rules.inline.emStrongRDelimAst
              : this.rules.inline.emStrongRDelimUnd;
          suffixBalance = indexSuffixBalance(maskedSrc, rule);
          index.set(maskedSrc, suffixBalance);
        }
        const minimum = suffixBalance.get(candidate.offset);
        // Skipping one opening marker can reduce the balance by one. Let
        // stock handle every case where a native close cannot be ruled out.
        if (
          minimum === undefined ||
          minimum <= (candidate.maySkipOpening ? -1 : -2)
        ) {
          return false;
        }

        const token: Tokens.Strong = {
          type: "strong",
          raw: src.slice(0, candidate.closingEnd),
          text: candidate.content,
          tokens: this.lexer.inlineTokens(candidate.content),
        };
        return token;
      },
    },
  } as unknown as MarkedExtension;
}

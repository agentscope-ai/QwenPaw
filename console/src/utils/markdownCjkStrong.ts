import { Tokenizer, type MarkedExtension, type Tokens } from "marked";

/**
 * CJK emphasis recovery.
 *
 * CommonMark only accepts a closing delimiter run that is right-flanking, so
 * ``**中文。**后`` never parses: the run is preceded by CJK punctuation and
 * followed by a CJK letter, so it is not right-flanking and cannot close.
 * The author's intent is unambiguous, so recover a `strong` token instead of
 * rewriting the source text.
 *
 * Stock parsing always wins at the same opener. Recovery requires either a
 * failed stock lookup or proof that stock cannot close this delimiter run.
 *
 * Scope (agreed with the reviewer):
 *   - double delimiters only (`**` and `__`); single `*` / `_` untouched
 *   - the character before the closing run must be CJK punctuation
 *   - the character after the closing run must be a CJK letter
 *   - one delimiter pair, no nested runs
 * Anything else is handed to the stock tokenizer unchanged, so the rendered
 * output stays identical to stock marked.
 */

const CJK_PUNCT_BEFORE =
  /[。，、；：！？…‥·—～「」『』（）〔〕【】《》〈〉“”‘’]/u;
const CJK_SENTENCE_BEFORE_BRACKET = /[。！？；：，、…]］/u;
const CJK_LETTER_AFTER =
  /[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7a3\uf900-\ufaff]/u;
const SUPPLEMENTARY_HAN_LETTER = /(?=\p{L})\p{Script=Han}/u;

/** Upper bound of an emphasis body this recovery is willing to look at. */
const MAX_BODY = 4096;
/** Cap the stock probe on recovery misses; stock itself is never truncated. */
const MAX_STOCK_PROBE = 1024;
const POSSIBLE_PROTECTED_INLINE = /[`$<~]|\[|\\\(|(?:https?|ftp):\/\/|www\./iu;

/**
 * The tokenizer's own implementation, used for bounded probes when the
 * index cannot prove a miss. Return its token untouched if it finds one.
 */
const stockEmStrong = Tokenizer.prototype.emStrong;

type Delimiter = "**" | "__";
type Candidate = {
  delimiter: Delimiter;
  offset: number;
  closingEnd: number;
  content: string;
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
 * Index double openers whose native delimiter balance stays above zero.
 * Only look these up for candidates with no intervening markers, so stock's
 * anchored alternative for an opposite delimiter cannot match their suffix.
 */
function indexUnclosable(masked: string, rule: RegExp): Set<number> {
  const unclosable = new Set<number>();

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
    if (width === 2 && minimum > -2) {
      unclosable.add(run.index + run[0].length - width - 2);
    }

    if (opening) {
      minimum = Math.min(0, minimum + width);
    } else if (!ambiguous || (2 + width) % 3 !== 0) {
      // A two-character opener is subject to marked's rule of three.
      minimum -= width;
    }
  }
  return unclosable;
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
  const hit = window.indexOf(delimiter);
  if (hit <= 0 || /[*_]/u.test(window.slice(0, hit))) return null;
  const closingStart = hit + 2;
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
  // The mask is not a complete map of inline nodes (e.g. multi-backtick
  // spans, nested links and bare URLs). Leave ambiguous boundaries to the
  // normal lexer instead of cutting its input at the candidate.
  if (content.includes("\n\n") || POSSIBLE_PROTECTED_INLINE.test(content)) {
    return null;
  }
  return { delimiter, offset, closingEnd, content };
}

export function cjkStrongExtension(): MarkedExtension {
  // A lexer is created per parse. Reuse the index while it is consuming the
  // same long inline source, including after nested inline parses return.
  const indexes = new WeakMap<
    Tokenizer["lexer"],
    Record<Delimiter, Map<string, Set<number>>>
  >();
  return {
    tokenizer: {
      emStrong(this: Tokenizer, src: string, maskedSrc: string, prevChar = "") {
        const candidate = findCandidate(this, src, maskedSrc, prevChar);
        if (!candidate) return false;

        let stockCannotClose = false;
        if (maskedSrc.length > MAX_STOCK_PROBE && !this.options.pedantic) {
          let byDelimiter = indexes.get(this.lexer);
          if (!byDelimiter) {
            byDelimiter = { "**": new Map(), __: new Map() };
            indexes.set(this.lexer, byDelimiter);
          }
          const index = byDelimiter[candidate.delimiter];
          let unclosable = index.get(maskedSrc);
          if (!unclosable) {
            const rule =
              candidate.delimiter === "**"
                ? this.rules.inline.emStrongRDelimAst
                : this.rules.inline.emStrongRDelimUnd;
            unclosable = indexUnclosable(maskedSrc, rule);
            index.set(maskedSrc, unclosable);
          }
          stockCannotClose = unclosable.has(candidate.offset);
        }
        if (!stockCannotClose) {
          if (src.length > MAX_STOCK_PROBE) return false;
          const stock = stockEmStrong.call(this, src, maskedSrc, prevChar);
          if (stock) return stock;
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

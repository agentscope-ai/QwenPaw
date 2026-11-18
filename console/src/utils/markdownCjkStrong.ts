import { Tokenizer, type MarkedExtension, type Tokens } from "marked";

/**
 * CJK emphasis recovery.
 *
 * CommonMark only accepts a closing delimiter run that is right-flanking, so
 * ``**中文。**后`` never parses: the run is preceded by CJK punctuation and
 * followed by a CJK letter, which is neither right- nor left-flanking.
 * The author's intent is unambiguous, so recover a `strong` token instead of
 * rewriting the source text.
 *
 * Stock parsing always wins: a candidate is only handed to recovery after the
 * stock `emStrong` returned nothing, so an input marked already understands
 * keeps its exact original structure.
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
const CJK_LETTER_AFTER =
  /[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7a3\uf900-\ufaff]/u;

/** Upper bound of an emphasis body this recovery is willing to look at. */
const MAX_BODY = 4096;

/**
 * The tokenizer's own implementation, captured before any extension is
 * registered. Recovery asks it first so an input it already parses is never
 * replaced by a different tree.
 */
const stockEmStrong = Tokenizer.prototype.emStrong;

/**
 * Which kind of formula run is still open after ``at`` characters, if any.
 *
 * The configured Latex plugin accepts `$…$`, `$$…$$`, `\(…\)` and `\[…\]`.
 * Two sources are needed because marked masks them differently: ``$`` is
 * passed through untouched in ``masked`` (so a `$` inside an inline code span
 * has already been blanked out), while ``\(`` and ``\[`` are replaced with
 * `++` placeholders and only survive in ``src``. Reading `$` from ``masked``
 * and the backslash forms from ``src`` keeps both families honest.
 */
type MathKind = "$" | "$$" | "(" | "[";

function openMathAt(
  src: string,
  masked: string,
  offset: number,
  at: number,
): MathKind | null {
  let open: MathKind | null = null;
  let i = 0;
  while (i < at) {
    const ch = src.charAt(i);
    if (ch === "\\") {
      const next = src.charAt(i + 1);
      if (next === "(") {
        if (open === null) open = "(";
        i += 2;
        continue;
      }
      if (next === "[") {
        if (open === null) open = "[";
        i += 2;
        continue;
      }
      if (next === ")" && open === "(") {
        open = null;
        i += 2;
        continue;
      }
      if (next === "]" && open === "[") {
        open = null;
        i += 2;
        continue;
      }
      // Any other escape is ordinary text.
      i += 2;
      continue;
    }
    if (masked.charAt(offset + i) === "$") {
      let run = 1;
      while (masked.charAt(offset + i + run) === "$") run += 1;
      const kind: MathKind = run >= 2 ? "$$" : "$";
      if (open === null) open = kind;
      else if (open === kind) open = null;
      i += run;
      continue;
    }
    i += 1;
  }
  return open;
}

function isInsideMath(
  src: string,
  masked: string,
  offset: number,
  at: number,
): boolean {
  return openMathAt(src, masked, offset, at) !== null;
}

function isEscaped(src: string, at: number): boolean {
  let backslashes = 0;
  for (let i = at - 1; i >= 0 && src.charAt(i) === "\\"; i -= 1) {
    backslashes += 1;
  }
  return backslashes % 2 === 1;
}

type Candidate = { closingEnd: number; content: string };

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
  if (tokenizer.lexer.state.inLink) return null;
  // Nested or unbalanced runs (`***`, `___`) are out of scope.
  if (src.charAt(2) === delimiter.charAt(0)) return null;
  // Keep the stock intra-word restriction for underscores.
  if (
    delimiter === "__" &&
    prevChar &&
    tokenizer.rules.other.unicodeAlphaNumeric.test(prevChar)
  ) {
    return null;
  }
  // Indexing by offset avoids copying the whole paragraph on every attempt.
  const offset =
    maskedSrc.length >= src.length ? maskedSrc.length - src.length : 0;
  // Only the first following run is considered. If it is not the agreed
  // shape, the stock tokenizer owns the span: it may still parse a valid
  // emphasis, and looking further would both merge independent spans and
  // cost a full scan per candidate.
  const hit = maskedSrc.indexOf(delimiter, offset + 2);
  if (hit === -1) return null;
  const closingStart = hit - offset;
  const closingEnd = closingStart + 2;
  if (closingStart < 2 || closingStart > 2 + MAX_BODY) return null;
  // A run that belongs to a longer marker sequence is ambiguous: bail out.
  if (
    src.charAt(closingStart - 1) === delimiter.charAt(0) ||
    src.charAt(closingEnd) === delimiter.charAt(0)
  ) {
    return null;
  }
  const content = src.slice(2, closingStart);
  if (content.length === 0 || content.includes("\n\n")) return null;
  if (isEscaped(src, closingStart)) return null;
  if (!CJK_PUNCT_BEFORE.test(src.charAt(closingStart - 1))) return null;
  if (!CJK_LETTER_AFTER.test(src.charAt(closingEnd))) return null;
  // A closer inside a formula would split its source and destroy the node,
  // so give the whole span back to the stock tokenizer.
  if (isInsideMath(src, maskedSrc, offset, closingStart)) return null;
  return { closingEnd, content };
}

export function cjkStrongExtension(): MarkedExtension {
  return {
    tokenizer: {
      // Stock parsing has precedence. The extension only asks it about spans
      // that match the agreed shape, and returns its result untouched when it
      // succeeds; every other position is delegated without any extra work.
      emStrong(this: Tokenizer, src: string, maskedSrc: string, prevChar = "") {
        const candidate = findCandidate(this, src, maskedSrc, prevChar);
        if (!candidate) {
          return (
            stockEmStrong.call(this, src, maskedSrc, prevChar) || undefined
          );
        }
        const stock = stockEmStrong.call(this, src, maskedSrc, prevChar);
        if (stock) return stock;
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

/*
 * 流式 markdown 自愈（对齐 QwenCode 的 packages/cli/src/ui/opentui/markdown-heal.ts，
 * 它基于 remend（vercel/streamdown 的 termination 处理）实现）。
 *
 * 为什么需要：流式期间末段的标记还没等到收尾（例如 `1. **聚合` 后面的 `**` 尚未到达），
 * 这一段会在「字面量标记」与「已渲染样式」之间逐帧翻转 —— 密集中文文档上观感就是"一直在闪"。
 * 自愈 = 渲染前把未闭合的标记补上，末段始终按 markdown 渲染；流结束后用原文
 *（落盘的文本才是事实，不再改动）。
 *
 * 覆盖的处理器与 remend 1.3.1 逐条对齐：内联 HTML 残尾 / setext 标题歧义 / 链接与图片
 * （text-only：未完成的链接只留文字）/ 粗斜体 / 粗体 / 双下划线斜体 / 单星斜体 / 单下划线斜体 /
 * 行内代码 / 删除线。未覆盖 singleTilde 与 comparisonOperators（对话文本里几乎不出现），
 * 也未覆盖 KaTeX（本工程 markdown 渲染器不渲染数学公式）。
 *
 * 纯函数、无副作用；入参是"直到当前这一刻收到的整段文本"。
 */

// 仅由空白与标记字符组成的尾段：这种"空标记"不补闭合（否则 `**` 会变成 `****`）
const BLANK_TAIL: RegExp = /^[\s_~*`]*$/;
// 列表项标记行（`- ` / `* ` / `+ ` / `1. `）：这类行里的标记不作为正文标记处理
const LIST_MARKER_LINE: RegExp = /^[\s]*[-*+][\s]+$/;
// setext 标题的两条下划线形态（`===` 与 `---`）
const SETEXT_DASH: RegExp = /^-{1,2}$/;
const SETEXT_EQ: RegExp = /^={1,2}$/;
const SETEXT_DASH_ITEM: RegExp = /^[\s]*-{1,2}[\s]+$/;
const SETEXT_EQ_ITEM: RegExp = /^[\s]*={1,2}[\s]+$/;
// 结尾处未闭合的内联 HTML 开标签
const HTML_TAIL: RegExp = /<[a-zA-Z/][^>]*$/;
// 四个及以上连续星号：视为分隔线，不补标记
const STAR_RUN_ONLY: RegExp = /^\*{4,}$/;
// 整行只有 ``` 加可选的一段无换行内容（单行围栏）
const SINGLE_LINE_FENCE: RegExp = /^```[^`\n]*```?$/;
const FENCE_NEWLINE: RegExp = /\n/;

// Unicode 字母/数字（remend 用 /\p{L}\p{N}_/u；ArkTS 的 RegExp 不支持属性转义，改按码点区间判断）。
// 区间覆盖：拉丁扩展 / 希腊 / 西里尔 / 希伯来 / 阿拉伯 / 印度诸文 / 泰文 / 假名 / 汉字 / 谚文 /
// 全角字母数字 / 兼容汉字；代理对（星辰面字母）一并按字母处理。
const WORD_RANGES: number[] = [
  0x00C0, 0x02AF, 0x0370, 0x052F, 0x0590, 0x06FF, 0x0900, 0x0DFF, 0x0E00, 0x0EFF,
  0x1E00, 0x1FFF, 0x3041, 0x3096, 0x30A1, 0x30FA, 0x30FC, 0x30FF, 0x3400, 0x4DBF,
  0x4E00, 0x9FFF, 0xA000, 0xA4CF, 0xAC00, 0xD7A3, 0xF900, 0xFAFF, 0xFF10, 0xFF19,
  0xFF21, 0xFF3A, 0xFF41, 0xFF5A, 0xFF66, 0xFF9F, 0xD800, 0xDFFF
];

function isWordChar(ch: string): boolean {
  if (ch.length === 0) {
    return false;
  }
  const c: number = ch.charCodeAt(0);
  if ((c >= 0x30 && c <= 0x39) || (c >= 0x41 && c <= 0x5A) || (c >= 0x61 && c <= 0x7A) || c === 0x5F) {
    return true;
  }
  for (let i = 0; i < WORD_RANGES.length; i += 2) {
    if (c >= WORD_RANGES[i] && c <= WORD_RANGES[i + 1]) {
      return true;
    }
  }
  return false;
}

function isSpaceChar(ch: string): boolean {
  return ch === ' ' || ch === '\t' || ch === '\n';
}

function charAt(text: string, index: number): string {
  return index >= 0 && index < text.length ? text.charAt(index) : '';
}

// 逐位置标记「是否处于代码区」（行内代码 `x` 或围栏块 ``` 内）——对齐 remend 的 lookup 表。
// mask[i] 表示"读完第 i 个字符后是否仍在代码区"；用法统一为 mask[min(index, len)]。
function codeMask(text: string): boolean[] {
  const mask: boolean[] = [];
  let inCode: boolean = false;
  let inFence: boolean = false;
  let i: number = 0;
  while (i < text.length) {
    if (text.charAt(i) === '\\' && i + 1 < text.length && text.charAt(i + 1) === '`') {
      const s: boolean = inCode || inFence;
      mask[i + 1] = s;
      mask[i + 2] = s;
      i += 2;
      continue;
    }
    if (text.substring(i, i + 3) === '```') {
      inFence = !inFence;
      const s: boolean = inCode || inFence;
      const end: number = Math.min(i + 3, text.length);
      for (let a = i + 1; a <= end; a += 1) {
        mask[a] = s;
      }
      i = end;
      continue;
    }
    if (!inFence && text.charAt(i) === '`') {
      inCode = !inCode;
    }
    mask[i + 1] = inCode || inFence;
    i += 1;
  }
  return mask;
}

function inCodeAt(mask: boolean[], text: string, index: number): boolean {
  const at: number = Math.min(index, text.length);
  return mask[at] === true;
}

// 位置 r 是否落在链接/图片的 URL 括号内
function inLinkUrl(text: string, r: number): boolean {
  for (let i = r - 1; i >= 0; i -= 1) {
    if (text.charAt(i) === ')') {
      return false;
    }
    if (text.charAt(i) === '(') {
      if (i > 0 && text.charAt(i - 1) === ']') {
        for (let j = r; j < text.length; j += 1) {
          if (text.charAt(j) === ')') {
            return true;
          }
          if (text.charAt(j) === '\n') {
            return false;
          }
        }
      }
      return false;
    }
    if (text.charAt(i) === '\n') {
      return false;
    }
  }
  return false;
}

// 位置 r 所在行是否只由 >= 3 个字符 c（可夹空白）组成
function lineOnlyChar(text: string, r: number, c: string): boolean {
  let start: number = 0;
  for (let i = r - 1; i >= 0; i -= 1) {
    if (text.charAt(i) === '\n') {
      start = i + 1;
      break;
    }
  }
  let end: number = text.length;
  for (let i = r; i < text.length; i += 1) {
    if (text.charAt(i) === '\n') {
      end = i;
      break;
    }
  }
  const line: string = text.substring(start, end);
  let n: number = 0;
  for (let i = 0; i < line.length; i += 1) {
    const ch: string = line.charAt(i);
    if (ch === c) {
      n += 1;
    } else if (ch !== ' ' && ch !== '\t') {
      return false;
    }
  }
  return n >= 3;
}

function lineSegmentBefore(text: string, at: number): string {
  const nl: number = text.substring(0, at).lastIndexOf('\n');
  const start: number = nl === -1 ? 0 : nl + 1;
  return text.substring(start, at);
}

// `**` 计数（跳过围栏块）
function countStarPairs(text: string): number {
  let n: number = 0;
  let inFence: boolean = false;
  for (let i = 0; i < text.length; i += 1) {
    if (text.substring(i, i + 3) === '```') {
      inFence = !inFence;
      i += 2;
      continue;
    }
    if (!inFence && text.charAt(i) === '*' && text.charAt(i + 1) === '*') {
      n += 1;
      i += 1;
    }
  }
  return n;
}

// `__` 计数（跳过围栏块）
function countUnderscorePairs(text: string): number {
  let n: number = 0;
  let inFence: boolean = false;
  for (let i = 0; i < text.length; i += 1) {
    if (text.substring(i, i + 3) === '```') {
      inFence = !inFence;
      i += 2;
      continue;
    }
    if (!inFence && text.charAt(i) === '_' && text.charAt(i + 1) === '_') {
      n += 1;
      i += 1;
    }
  }
  return n;
}

// 三个及以上连续星号段的个数（`***` 计 1）
function countStarRuns(text: string): number {
  let n: number = 0;
  let run: number = 0;
  let inFence: boolean = false;
  for (let i = 0; i < text.length; i += 1) {
    if (text.substring(i, i + 3) === '```') {
      if (run >= 3) {
        n += Math.floor(run / 3);
      }
      run = 0;
      inFence = !inFence;
      i += 2;
      continue;
    }
    if (!inFence) {
      if (text.charAt(i) === '*') {
        run += 1;
      } else {
        if (run >= 3) {
          n += Math.floor(run / 3);
        }
        run = 0;
      }
    }
  }
  if (run >= 3) {
    n += Math.floor(run / 3);
  }
  return n;
}

function isMathContext(text: string): boolean {
  return text.includes('$') || text.includes('\\(') || text.includes('\\[');
}

function transMath(state: string, ch: string): string {
  if (ch === '[' && state === 'none') {
    return 'blockLatex';
  }
  if (ch === ']' && state === 'blockLatex') {
    return 'none';
  }
  if (ch === '(' && state === 'none') {
    return 'inlineLatex';
  }
  if (ch === ')' && state === 'inlineLatex') {
    return 'none';
  }
  return '';
}

function dashMath(state: string, dbl: boolean): string {
  if (dbl) {
    return state === 'blockDollar' ? 'none' : 'blockDollar';
  }
  if (state === 'blockDollar') {
    return 'blockDollar';
  }
  return state === 'inlineDollar' ? 'none' : 'inlineDollar';
}

// 位置 r 之前是否处于 $...$（数学）上下文
function inMath(text: string, r: number): boolean {
  let state: string = 'none';
  for (let i = 0; i < text.length && i < r; i += 1) {
    if (text.charAt(i) === '\\' && text.charAt(i + 1) === '$') {
      i += 1;
      continue;
    }
    if (text.charAt(i) === '\\') {
      const t: string = transMath(state, text.charAt(i + 1));
      if (t.length > 0) {
        state = t;
        i += 1;
        continue;
      }
    }
    if (text.charAt(i) === '$' && state !== 'inlineLatex' && state !== 'blockLatex') {
      const dbl: boolean = text.charAt(i + 1) === '$';
      state = dashMath(state, dbl);
      if (dbl) {
        i += 1;
      }
    }
  }
  return state !== 'none';
}

// 该位置的 `*` 是否不参与斜体计数（转义 / 数学上下文 / 成对星号 / 首尾空白规则）
function skippableStar(text: string, i: number, before: string, after: string): boolean {
  if (before === '\\') {
    return true;
  }
  if (isMathContext(text) && inMath(text, i)) {
    return true;
  }
  if (before !== '*' && after === '*') {
    return charAt(text, i + 2) !== '*';
  }
  return before === '*' || ((!before || isSpaceChar(before)) && (!after || isSpaceChar(after)));
}

// 单词内 `*`（如 2*3）不算斜体标记
function countStarAt(before: string, after: string, n: number, prevChain: boolean): boolean {
  const inWordChain: boolean = before.length > 0 && after.length > 0
    && isWordChar(before) && isWordChar(after);
  const afterNotSpace: boolean = after.length > 0 && !isSpaceChar(after);
  const beforeNotSpace: boolean = before.length > 0 && !isSpaceChar(before);
  if (inWordChain && n % 2 === 0 && !prevChain) {
    return false;
  }
  if (beforeNotSpace && n % 2 === 1) {
    return true;
  }
  return afterNotSpace;
}

// 单个 `*`（非 `**`）的计数
function countSingleStar(text: string): number {
  let n: number = 0;
  let prevChain: boolean = false;
  let inFence: boolean = false;
  for (let i = 0; i < text.length; i += 1) {
    if (text.charAt(i) === '`' && i + 2 < text.length && text.charAt(i + 1) === '`'
      && text.charAt(i + 2) === '`') {
      inFence = !inFence;
      i += 2;
      continue;
    }
    if (inFence) {
      continue;
    }
    if (text.charAt(i) !== '*') {
      if (!isWordChar(text.charAt(i))) {
        prevChain = false;
      }
      continue;
    }
    const before: string = charAt(text, i - 1);
    const after: string = charAt(text, i + 1);
    if (skippableStar(text, i, before, after)) {
      continue;
    }
    if (countStarAt(before, after, n, prevChain)) {
      n += 1;
      prevChain = before.length > 0 && after.length > 0 && isWordChar(before) && isWordChar(after);
    }
  }
  return n;
}

// 单个 `_`（非 `__`）的计数；字符前后都是词内字符（如 snake_case）不算标记
function countSingleUnderscore(text: string): number {
  let n: number = 0;
  let inFence: boolean = false;
  for (let i = 0; i < text.length; i += 1) {
    if (text.charAt(i) === '`' && i + 2 < text.length && text.charAt(i + 1) === '`'
      && text.charAt(i + 2) === '`') {
      inFence = !inFence;
      i += 2;
      continue;
    }
    if (inFence || text.charAt(i) !== '_') {
      continue;
    }
    const before: string = charAt(text, i - 1);
    const after: string = charAt(text, i + 1);
    const skip: boolean = before === '\\' || (isMathContext(text) && inMath(text, i))
      || inLinkUrl(text, i) || before === '_' || after === '_'
      || (before.length > 0 && after.length > 0 && isWordChar(before) && isWordChar(after));
    if (!skip) {
      n += 1;
    }
  }
  return n;
}

// 最后一段未闭合的单个 `*` 的位置（无则 -1）
function lastUnmatchedStar(text: string): number {
  let inFence: boolean = false;
  for (let i = 0; i < text.length; i += 1) {
    if (text.charAt(i) === '`' && i + 2 < text.length && text.charAt(i + 1) === '`'
      && text.charAt(i + 2) === '`') {
      inFence = !inFence;
      i += 2;
      continue;
    }
    if (!inFence && text.charAt(i) === '*' && charAt(text, i - 1) !== '*' && charAt(text, i + 1) !== '*'
      && charAt(text, i - 1) !== '\\' && !inMath(text, i)) {
      const before: string = charAt(text, i - 1);
      const after: string = charAt(text, i + 1);
      const beforeSp: boolean = before.length === 0 || isSpaceChar(before);
      const afterSp: boolean = after.length === 0 || isSpaceChar(after);
      if ((beforeSp && afterSp)
        || (before.length > 0 && after.length > 0 && isWordChar(before) && isWordChar(after))
        || afterSp) {
        continue;
      }
      return i;
    }
  }
  return -1;
}

function lastUnmatchedUnderscore(text: string): number {
  let inFence: boolean = false;
  for (let i = 0; i < text.length; i += 1) {
    if (text.charAt(i) === '`' && i + 2 < text.length && text.charAt(i + 1) === '`'
      && text.charAt(i + 2) === '`') {
      inFence = !inFence;
      i += 2;
      continue;
    }
    if (!inFence && text.charAt(i) === '_' && charAt(text, i - 1) !== '_' && charAt(text, i + 1) !== '_'
      && charAt(text, i - 1) !== '\\' && !inMath(text, i) && !inLinkUrl(text, i)) {
      const before: string = charAt(text, i - 1);
      const after: string = charAt(text, i + 1);
      if (before.length > 0 && after.length > 0 && isWordChar(before) && isWordChar(after)) {
        continue;
      }
      return i;
    }
  }
  return -1;
}

function countFencesOdd(text: string): boolean {
  const m: RegExpMatchArray | null = text.match(/```/g);
  return (m !== null ? m.length : 0) % 2 === 1;
}

function countBackticks(text: string): number {
  let n: number = 0;
  for (let i = 0; i < text.length; i += 1) {
    if (text.charAt(i) === '\\' && i + 1 < text.length && text.charAt(i + 1) === '`') {
      i += 1;
      continue;
    }
    if (text.charAt(i) === '`' && !fenceNear(text, i)) {
      n += 1;
    }
  }
  return n;
}

function fenceNear(text: string, i: number): boolean {
  return (i > 0 && text.substring(i - 1, i + 2) === '```')
    || (i > 1 && text.substring(i - 2, i + 1) === '```')
    || (i <= text.length - 3 && text.substring(i, i + 3) === '```');
}

// ============ 各处理器（顺序 = remend 的优先级）============

// 结尾处未闭合的 HTML 标签整段丢掉（它渲染不出东西，留着只会在"文本 / 标签"之间翻）
function healHtmlTags(text: string): string {
  const m: RegExpMatchArray | null = text.match(HTML_TAIL);
  if (m === null || m.index === undefined) {
    return text;
  }
  const at: number = m.index;
  if (inCodeAt(codeMask(text), text, at)) {
    return text;
  }
  return text.substring(0, at).replace(/\s+$/, '');
}

// `---` / `===` 单独一行时会被当成 setext 标题下划线，把上一行整行变成标题 → 补零宽字符断开
function healSetextHeadings(text: string): string {
  const lastNl: number = text.lastIndexOf('\n');
  if (lastNl === -1) {
    return text;
  }
  const line: string = text.substring(lastNl + 1);
  const prev: string = text.substring(0, lastNl);
  const t: string = line.trim();
  const isDash: boolean = SETEXT_DASH.test(t) && !SETEXT_DASH_ITEM.test(line);
  const isEq: boolean = SETEXT_EQ.test(t) && !SETEXT_EQ_ITEM.test(line);
  if (isDash || isEq) {
    const pl: string[] = prev.split('\n');
    const last: string = pl.length > 0 ? pl[pl.length - 1] : '';
    if (last.length > 0 && last.trim().length > 0) {
      return `${text}\u200B`;
    }
  }
  return text;
}

function findOpenBracket(text: string, from: number): number {
  let depth: number = 1;
  for (let i = from - 1; i >= 0; i -= 1) {
    if (text.charAt(i) === ']') {
      depth += 1;
    } else if (text.charAt(i) === '[') {
      depth -= 1;
      if (depth === 0) {
        return i;
      }
    }
  }
  return -1;
}

function findCloseBracket(text: string, from: number): number {
  let depth: number = 1;
  for (let i = from + 1; i < text.length; i += 1) {
    if (text.charAt(i) === '[') {
      depth += 1;
    } else if (text.charAt(i) === ']') {
      depth -= 1;
      if (depth === 0) {
        return i;
      }
    }
  }
  return -1;
}

// 图片（`![...`）未完成：整段丢掉；普通链接未完成：text-only 模式只留链接文字。
// 返回 null = 此处无需自愈（注意自愈结果本身可能是空串，不能拿空串当哨兵）
function healLinkAt(text: string, r: number, textOnly: boolean): string | null {
  if (text.substring(r + 2).includes(')')) {
    return null;
  }
  const open: number = findOpenBracket(text, r);
  if (open === -1 || inCodeAt(codeMask(text), text, open)) {
    return null;
  }
  const isImg: boolean = open > 0 && text.charAt(open - 1) === '!';
  const start: number = isImg ? open - 1 : open;
  const head: string = text.substring(0, start);
  if (isImg) {
    return head;
  }
  const label: string = text.substring(open + 1, r);
  return textOnly ? `${head}${label}` : `${head}[${label}](streamdown:incomplete-link)`;
}

function healOpenBracket(text: string, r: number, textOnly: boolean): string | null {
  const isImg: boolean = r > 0 && text.charAt(r - 1) === '!';
  const at: number = isImg ? r - 1 : r;
  const noClose: boolean = !text.substring(r + 1).includes(']');
  if (noClose || findCloseBracket(text, r) === -1) {
    const head: string = text.substring(0, at);
    if (isImg) {
      return head;
    }
    if (textOnly) {
      let before: number = r;
      for (let i = 0; i < r; i += 1) {
        if (text.charAt(i) === '[' && !inCodeAt(codeMask(text), text, i)) {
          if (i > 0 && text.charAt(i - 1) === '!') {
            continue;
          }
          const close: number = findCloseBracket(text, i);
          if (close === -1) {
            before = i;
            break;
          }
          if (close + 1 < text.length && text.charAt(close + 1) === '(') {
            const rp: number = text.indexOf(')', close + 2);
            if (rp !== -1) {
              i = rp;
            }
          }
        }
      }
      return text.substring(0, before) + text.substring(before + 1);
    }
    return `${text}](streamdown:incomplete-link)`;
  }
  return null;
}

function healLinks(text: string, textOnly: boolean): string {
  const idx: number = text.lastIndexOf('](');
  if (idx !== -1 && !inCodeAt(codeMask(text), text, idx)) {
    const fixed: string | null = healLinkAt(text, idx, textOnly);
    if (fixed !== null) {
      return fixed;
    }
  }
  for (let i = text.length - 1; i >= 0; i -= 1) {
    if (text.charAt(i) === '[' && !inCodeAt(codeMask(text), text, i)) {
      const fixed: string | null = healOpenBracket(text, i, textOnly);
      if (fixed !== null) {
        return fixed;
      }
    }
  }
  return text;
}

// `***粗斜体` → 补 `***`
function healBoldItalic(text: string): string {
  if (STAR_RUN_ONLY.test(text)) {
    return text;
  }
  const m: RegExpMatchArray | null = text.match(/(\*\*\*)([^*]*?)$/);
  if (m === null) {
    return text;
  }
  const tail: string = m[2];
  const at: number = text.lastIndexOf(m[1]);
  if (tail.length === 0 || BLANK_TAIL.test(tail) || inCodeAt(codeMask(text), text, at)) {
    return text;
  }
  const nl: number = text.substring(0, at).lastIndexOf('\n');
  const start: number = nl === -1 ? 0 : nl + 1;
  if (LIST_MARKER_LINE.test(text.substring(start, at)) && tail.includes('\n')) {
    return text;
  }
  if (countStarRuns(text) % 2 !== 1) {
    return text;
  }
  const balanced: boolean = countStarPairs(text) % 2 === 0 && countSingleStar(text) % 2 === 0;
  return balanced ? text : `${text}***`;
}

// `**粗体` → 补 `**`（尾段以 `*` 结尾时只补一个，避免变成 `***`）
function healBold(text: string): string {
  const m: RegExpMatchArray | null = text.match(/(\*\*)([^*]*\*?)$/);
  if (m === null) {
    return text;
  }
  const tail: string = m[2];
  const at: number = text.lastIndexOf(m[1]);
  if (!safeMarkerPosition(text, tail, at, '*')) {
    return text;
  }
  if (countStarPairs(text) % 2 !== 1) {
    return text;
  }
  return tail.endsWith('*') ? `${text}*` : `${text}**`;
}

// 标记位置是否"可安全补闭合"：尾段非空标记、不在代码/链接里、所在行不是列表标记行/分隔线行
function safeMarkerPosition(text: string, tail: string, at: number, ch: string): boolean {
  if (tail.length === 0 || BLANK_TAIL.test(tail)) {
    return false;
  }
  if (inCodeAt(codeMask(text), text, at)) {
    return false;
  }
  if (LIST_MARKER_LINE.test(lineSegmentBefore(text, at)) && tail.includes('\n')) {
    return false;
  }
  return !lineOnlyChar(text, at, ch);
}

// `__粗体斜体` → 补 `__`
function healItalicDoubleUnderscore(text: string): string {
  const m: RegExpMatchArray | null = text.match(/(__)([^_]*?)$/);
  if (m === null) {
    const single: RegExpMatchArray | null = text.match(/(__)([^_]+)_$/);
    if (single !== null) {
      const at: number = text.lastIndexOf(single[1]);
      if (!inCodeAt(codeMask(text), text, at) && countUnderscorePairs(text) % 2 === 1) {
        return `${text}_`;
      }
    }
    return text;
  }
  const tail: string = m[2];
  const at: number = text.lastIndexOf(m[1]);
  if (safeMarkerPosition(text, tail, at, '_')) {
    return countUnderscorePairs(text) % 2 === 1 ? `${text}__` : text;
  }
  return text;
}

// `*斜体` → 补 `*`
function healItalicAsterisk(text: string): string {
  const m: RegExpMatchArray | null = text.match(/(\*)([^*]*?)$/);
  if (m === null) {
    return text;
  }
  const at: number = lastUnmatchedStar(text);
  if (at === -1) {
    return text;
  }
  if (inCodeAt(codeMask(text), text, at)) {
    return text;
  }
  const tail: string = text.substring(at + 1);
  if (tail.length === 0 || BLANK_TAIL.test(tail)) {
    return text;
  }
  return countSingleStar(text) % 2 === 1 ? `${text}*` : text;
}

// `_斜体` → 补 `_`
function healItalicUnderscore(text: string): string {
  const m: RegExpMatchArray | null = text.match(/(_)([^_]*?)$/);
  if (m === null) {
    return text;
  }
  const at: number = lastUnmatchedUnderscore(text);
  if (at === -1) {
    return text;
  }
  const tail: string = text.substring(at + 1);
  if (tail.length === 0 || BLANK_TAIL.test(tail) || inCodeAt(codeMask(text), text, at)) {
    return text;
  }
  if (countSingleUnderscore(text) % 2 !== 1) {
    return text;
  }
  // 结尾是 `**` 时把 `_` 插在星号之前（`..._**`），否则插在最后一段换行之前
  if (text.endsWith('**')) {
    const body: string = text.substring(0, text.length - 2);
    const firstStar: number = body.indexOf('**');
    const u: number = lastUnmatchedUnderscore(body);
    if (countStarPairs(body) % 2 === 1 && firstStar !== -1 && u !== -1 && firstStar < u) {
      return `${body}_**`;
    }
  }
  let r: number = text.length;
  while (r > 0 && text.charAt(r - 1) === '\n') {
    r -= 1;
  }
  return r < text.length ? `${text.substring(0, r)}_${text.substring(r)}` : `${text}_`;
}

// 单行围栏（```ts```）与未闭合的行内代码
function healInlineCode(text: string): string {
  const single: string | null = healSingleLineFence(text);
  if (single !== null) {
    return single;
  }
  const m: RegExpMatchArray | null = text.match(/(`)([^`]*?)$/);
  if (m !== null && !countFencesOdd(text)) {
    const tail: string = m[2];
    if (tail.length === 0 || BLANK_TAIL.test(tail)) {
      return text;
    }
    if (countBackticks(text) % 2 === 1) {
      return `${text}\``;
    }
  }
  return text;
}

function healSingleLineFence(text: string): string | null {
  if (!SINGLE_LINE_FENCE.test(text) || FENCE_NEWLINE.test(text)) {
    return null;
  }
  if (text.endsWith('``') && !text.endsWith('```')) {
    return `${text}\``;
  }
  return text;
}

// `~~删除线` → 补 `~~`
function healStrikethrough(text: string): string {
  const m: RegExpMatchArray | null = text.match(/(~~)([^~]*?)$/);
  if (m !== null) {
    const tail: string = m[2];
    if (tail.length === 0 || BLANK_TAIL.test(tail)) {
      return text;
    }
    const at: number = text.lastIndexOf(m[1]);
    if (inCodeAt(codeMask(text), text, at)) {
      return text;
    }
    if (countTildes(text) % 2 === 1) {
      return `${text}~~`;
    }
    return text;
  }
  const single: RegExpMatchArray | null = text.match(/(~~)([^~]+)~$/);
  if (single !== null) {
    const at: number = text.lastIndexOf(single[0].substring(0, 2));
    if (inCodeAt(codeMask(text), text, at)) {
      return text;
    }
    if (countTildes(text) % 2 === 1) {
      return `${text}~`;
    }
  }
  return text;
}

function countTildes(text: string): number {
  const m: RegExpMatchArray | null = text.match(/~~/g);
  return m !== null ? m.length : 0;
}

// 流式渲染用文本：把未闭合的标记补上（流结束后请直接用原文）
export function healStreamingMarkdown(raw: string, textOnlyLinks: boolean = true): string {
  if (raw.length === 0) {
    return raw;
  }
  // 结尾单个空格会让 `**粗 **` 退化成字面量（remend：先去掉这种尾空格）
  let out: string = raw.endsWith(' ') && !raw.endsWith('  ')
    ? raw.substring(0, raw.length - 1) : raw;
  out = healHtmlTags(out);
  out = healSetextHeadings(out);
  out = healLinks(out, textOnlyLinks);
  out = healBoldItalic(out);
  out = healBold(out);
  out = healItalicDoubleUnderscore(out);
  out = healItalicAsterisk(out);
  out = healItalicUnderscore(out);
  out = healInlineCode(out);
  out = healStrikethrough(out);
  return out;
}

// ============ 滚动里程碑标题行剥离 ============
// 移植 console/src/pages/Chat/headlineFilter.ts 的 stripScrollHeadlines（含正则原文）。
// 来源：服务端提示词（src/qwenpaw/agents/context/scroll/prompt.py）要求模型把执行里程碑
// 输出为单行围栏标题（`⟦ … ⟧`，含 CJK 变体 `〚 … 〛` 与 legacy `<!-- ⟦ … ⟧ -->` 形态）。
// SSE 侧剥离（服务端 _strip_event_headlines）不彻底——console 同样在客户端剥离；
// 漏到客户端的标题行在本工程有两种破坏：注释形态被 markdown vendor 吞成隐形 html token
// （0 高块却占一个块间缝位，观感为正文中间凭空多出一段空白）；独占一条 message 时
// 空内容守卫按"非空文本"放行，渲染成一张只有卡片底色的空白卡。
// 渲染前对整文剥离：本工程每次解析都重归一化整段文本（无 chunk 级 delta 流），
// 不需要 console 的逐 chunk 状态机（filterHeadlineDelta）；TRAILING 正则覆盖
// "帧尾进行中的标题行未闭合"（流式期间最后一行停在 `⟦ …` 中间）。
// `\n{3,}` 收敛用于填平被整行移除的标题行留下的空行。
const HEADLINE_LINE_RE: RegExp =
  /^[ \t]*(?:<!--)?[ \t]*[⟦〚][ \t]*(.+?)[ \t]*[⟧〛][ \t]*(?:-->)?[ \t]*$/gm;
const TRAILING_HEADLINE_RE: RegExp = /(?:<!--[ \t]*[⟦〚]|(?:^|\n)[ \t]*[⟦〚])[^\r\n]*$/;

export function stripScrollHeadlines(text: string): string {
  return text
    .replace(HEADLINE_LINE_RE, '')
    .replace(TRAILING_HEADLINE_RE, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

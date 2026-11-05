import { Lexer } from "marked";

export const HISTORY_MARKDOWN_CHUNK_CHARS = 32 * 1024;

export interface MarkdownSegments {
  source: string;
  chunks: string[];
  stableLength: number;
}

/** Keep document-wide references and math in the vendor's single parse scope. */
function requiresDocumentScope(content: string): boolean {
  return /\[\^|(?:^|\n) {0,3}\[[^\]\n]+\]:|\$|\\\[|\\\(/.test(content);
}

/** Segment complete top-level tokens; never cut a fence, list or table in half. */
export function segmentMarkdown(
  content: string,
  limit = HISTORY_MARKDOWN_CHUNK_CHARS,
  previous?: MarkdownSegments,
): MarkdownSegments {
  if (content.length <= limit || requiresDocumentScope(content))
    return { source: content, chunks: [content], stableLength: 0 };
  const reusable = previous && content.startsWith(previous.source);
  const stableLength = reusable ? previous.stableLength : 0;
  const chunks = reusable ? previous.chunks.slice(0, -1) : [];
  const tail = content.slice(stableLength);
  const tokens = Lexer.lex(tail, { gfm: true });
  // Definitions are omitted from raw tokens. Keep their original parse scope.
  if (tokens.map((token) => token.raw).join("") !== tail)
    return { source: content, chunks: [content], stableLength: 0 };
  let pending = "";
  let committed = stableLength;
  tokens.forEach((token, index) => {
    pending += token.raw;
    // Retain the final tokens: another delta can continue a paragraph/list.
    if (pending.length >= limit && index < tokens.length - 2) {
      chunks.push(pending);
      committed += pending.length;
      pending = "";
    }
  });
  chunks.push(pending);
  return { source: content, chunks, stableLength: committed };
}

export function splitHistoryMarkdown(
  content: string,
  limit = HISTORY_MARKDOWN_CHUNK_CHARS,
): string[] {
  return segmentMarkdown(content, limit).chunks;
}

export function latestHistoryMarkdownChunk(
  content: string,
  limit = HISTORY_MARKDOWN_CHUNK_CHARS,
): string {
  const chunks = splitHistoryMarkdown(content, limit);
  return chunks[chunks.length - 1] ?? "";
}

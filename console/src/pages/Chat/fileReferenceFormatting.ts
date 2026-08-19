export interface FileReferenceSegment {
  text: string;
  reference: ParsedFileReference | null;
}

export interface ParsedFileReference {
  kind: "file" | "editor";
  path: string;
  startLine?: number;
  endLine?: number;
}

export type RichComposerSegment =
  | {
      kind: "text";
      raw: string;
    }
  | {
      kind: "file";
      raw: string;
      reference: ParsedFileReference;
    }
  | {
      kind: "code";
      raw: string;
      language: string;
      code: string;
    };

export function compactFileReferenceLabel(
  reference: ParsedFileReference,
): string {
  const filename =
    reference.path.split(/[\\/]/).filter(Boolean).pop() || reference.path;
  if (reference.kind === "file") {
    return filename;
  }
  const startLine = reference.startLine ?? 1;
  const endLine = reference.endLine ?? startLine;
  const lineRange =
    startLine === endLine ? `${startLine}` : `${startLine}–${endLine}`;
  return `${filename} · ${lineRange}`;
}

interface ParsedFileReferenceRange {
  start: number;
  end: number;
  reference: ParsedFileReference;
}

const FILE_MENTION_PATTERN = /@ ([^\s\n]+)/g;
const EDITOR_LINE_SUFFIX_PATTERN = /:(\d+)(?:-(\d+))?$/;

function looksLikeEditorPath(path: string): boolean {
  const name = path.split(/[\\/]/).pop() ?? path;
  return (
    path.includes("/") ||
    path.includes("\\") ||
    name.includes(".") ||
    /^[A-Z][A-Z0-9_.-]*$/.test(name)
  );
}

function fileReferenceRanges(value: string): ParsedFileReferenceRange[] {
  const ranges: ParsedFileReferenceRange[] = [];
  for (const match of value.matchAll(FILE_MENTION_PATTERN)) {
    const start = match.index ?? 0;
    ranges.push({
      start,
      end: start + match[0].length,
      reference: {
        kind: "file",
        path: match[1],
      },
    });
  }
  let lineStart = 0;
  while (lineStart < value.length) {
    const newline = value.indexOf("\n", lineStart);
    const lineEnd = newline < 0 ? value.length : newline;
    const rawLine = value.slice(lineStart, lineEnd).replace(/\r$/, "");
    const leadingWhitespace = rawLine.length - rawLine.trimStart().length;
    const referenceText = rawLine.trim();
    const match = referenceText.match(EDITOR_LINE_SUFFIX_PATTERN);
    if (match?.index !== undefined) {
      const path = referenceText.slice(0, match.index);
      const start = lineStart + leadingWhitespace;
      const end = start + referenceText.length;
      if (
        looksLikeEditorPath(path) &&
        !ranges.some((range) => start < range.end && end > range.start)
      ) {
        ranges.push({
          start,
          end,
          reference: {
            kind: "editor",
            path,
            startLine: Number(match[1]),
            endLine: Number(match[2] ?? match[1]),
          },
        });
      }
    }
    if (newline < 0) break;
    lineStart = newline + 1;
  }
  return ranges.sort((left, right) => left.start - right.start);
}

export function splitFileReferences(value: string): FileReferenceSegment[] {
  const segments: FileReferenceSegment[] = [];
  let offset = 0;
  for (const range of fileReferenceRanges(value)) {
    if (range.start > offset) {
      segments.push({
        text: value.slice(offset, range.start),
        reference: null,
      });
    }
    segments.push({
      text: value.slice(range.start, range.end),
      reference: range.reference,
    });
    offset = range.end;
  }
  if (offset < value.length || segments.length === 0) {
    segments.push({
      text: value.slice(offset),
      reference: null,
    });
  }
  return segments;
}

const LEADING_CODE_FENCE_PATTERN =
  /^(\r?\n```([^\r\n`]*)\r?\n([\s\S]*?)\r?\n```)(?=\r?\n|$)/;

/**
 * Split the raw sender value into the atomic items shown by the rich composer.
 * A fenced block becomes a code chip only when it immediately follows an
 * editor line reference, matching the format produced by Coding mode.
 */
export function splitRichComposerValue(value: string): RichComposerSegment[] {
  const result: RichComposerSegment[] = [];

  for (const segment of splitFileReferences(value)) {
    if (segment.reference) {
      result.push({
        kind: "file",
        raw: segment.text,
        reference: segment.reference,
      });
      continue;
    }

    let raw = segment.text;
    const previous = result[result.length - 1];
    if (previous?.kind === "file" && previous.reference.kind === "editor") {
      const match = raw.match(LEADING_CODE_FENCE_PATTERN);
      if (match) {
        result.push({
          kind: "code",
          raw: match[1],
          language: match[2] || "plaintext",
          code: match[3],
        });
        raw = raw.slice(match[1].length);
      }
    }

    if (raw) {
      result.push({ kind: "text", raw });
    }
  }

  return result;
}

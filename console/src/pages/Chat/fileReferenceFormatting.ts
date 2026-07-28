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

export interface FileReferenceRange {
  start: number;
  end: number;
}

interface ParsedFileReferenceRange extends FileReferenceRange {
  reference: ParsedFileReference;
}

const FILE_MENTION_PATTERN = /@ ([^\s\n]+)/g;
const EDITOR_REFERENCE_PATTERN =
  /((?:[a-zA-Z]:[\\/]|\/)?(?:[^\s\n:]+[\\/])*[^\s\n:]+):(\d+)(?:-(\d+))?/g;

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
  for (const match of value.matchAll(EDITOR_REFERENCE_PATTERN)) {
    const start = match.index ?? 0;
    const end = start + match[0].length;
    if (
      !looksLikeEditorPath(match[1]) ||
      ranges.some((range) => start < range.end && end > range.start)
    ) {
      continue;
    }
    ranges.push({
      start,
      end,
      reference: {
        kind: "editor",
        path: match[1],
        startLine: Number(match[2]),
        endLine: Number(match[3] ?? match[2]),
      },
    });
  }
  return ranges.sort((left, right) => left.start - right.start);
}

export function atomicDeletionRange(
  value: string,
  selectionStart: number,
  selectionEnd: number,
  key: "Backspace" | "Delete",
): FileReferenceRange | null {
  const ranges = fileReferenceRanges(value);
  if (selectionStart === selectionEnd) {
    const range =
      ranges.find((range) =>
        key === "Backspace"
          ? selectionStart > range.start && selectionStart <= range.end
          : selectionStart >= range.start && selectionStart < range.end,
      ) ?? null;
    return range ? { start: range.start, end: range.end } : null;
  }

  const touched = ranges.filter(
    (range) => selectionStart < range.end && selectionEnd > range.start,
  );
  if (touched.length === 0) return null;
  return {
    start: Math.min(selectionStart, touched[0].start),
    end: Math.max(selectionEnd, touched[touched.length - 1].end),
  };
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

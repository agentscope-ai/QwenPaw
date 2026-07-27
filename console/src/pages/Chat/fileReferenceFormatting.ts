export interface FileReferenceSegment {
  text: string;
  reference: boolean;
}

export interface FileReferenceRange {
  start: number;
  end: number;
}

const FILE_REFERENCE_PATTERN =
  /@ (?:(?:[a-zA-Z]:[\\/])|\/)[^\s\n]+|(?:(?:[a-zA-Z]:[\\/]|\/)?(?:[^\s\n:]+[\\/])*[^\s\n:]+\.[a-zA-Z0-9_-]+):\d+(?:-\d+)?/g;

export function fileReferenceRanges(value: string): FileReferenceRange[] {
  return Array.from(value.matchAll(FILE_REFERENCE_PATTERN), (match) => ({
    start: match.index ?? 0,
    end: (match.index ?? 0) + match[0].length,
  }));
}

export function atomicDeletionRange(
  value: string,
  selectionStart: number,
  selectionEnd: number,
  key: "Backspace" | "Delete",
): FileReferenceRange | null {
  const ranges = fileReferenceRanges(value);
  if (selectionStart === selectionEnd) {
    return (
      ranges.find((range) =>
        key === "Backspace"
          ? selectionStart > range.start && selectionStart <= range.end
          : selectionStart >= range.start && selectionStart < range.end,
      ) ?? null
    );
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
  for (const match of value.matchAll(FILE_REFERENCE_PATTERN)) {
    const index = match.index ?? 0;
    if (index > offset) {
      segments.push({
        text: value.slice(offset, index),
        reference: false,
      });
    }
    segments.push({ text: match[0], reference: true });
    offset = index + match[0].length;
  }
  if (offset < value.length || segments.length === 0) {
    segments.push({
      text: value.slice(offset),
      reference: false,
    });
  }
  return segments;
}

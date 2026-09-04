export interface ParsedSseData {
  events: string[];
  rest: string;
}

function findEventBoundary(
  value: string,
): { index: number; length: number } | null {
  const boundaries = ["\r\n\r\n", "\n\n", "\r\r"]
    .map((separator) => ({
      index: value.indexOf(separator),
      length: separator.length,
    }))
    .filter((candidate) => candidate.index >= 0)
    .sort((left, right) => left.index - right.index);
  return boundaries[0] ?? null;
}

function dataFromBlock(block: string): string | null {
  const values: string[] = [];
  for (const line of block.split(/\r\n|\r|\n/)) {
    if (!line.startsWith("data:")) continue;
    const value = line.slice(5);
    values.push(value.startsWith(" ") ? value.slice(1) : value);
  }
  return values.length > 0 ? values.join("\n") : null;
}

/** Incrementally extract SSE data fields while retaining an incomplete tail. */
export function parseSseDataEvents(
  buffer: string,
  flush = false,
): ParsedSseData {
  const events: string[] = [];
  let rest = buffer;
  for (;;) {
    const boundary = findEventBoundary(rest);
    if (!boundary) break;
    const data = dataFromBlock(rest.slice(0, boundary.index));
    if (data !== null) events.push(data);
    rest = rest.slice(boundary.index + boundary.length);
  }

  if (flush && rest.length > 0) {
    const data = dataFromBlock(rest);
    if (data !== null) events.push(data);
    rest = "";
  }
  return { events, rest };
}

/** Keep HTTP input frames small without splitting UTF-16 surrogate pairs. */
export function* terminalInputChunks(data: string): Generator<string> {
  for (let start = 0; start < data.length; ) {
    let end = Math.min(start + 4096, data.length);
    const last = data.charCodeAt(end - 1);
    if (end < data.length && last >= 0xd800 && last <= 0xdbff) end -= 1;
    yield data.slice(start, end);
    start = end;
  }
}

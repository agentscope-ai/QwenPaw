import { describe, expect, it } from "vitest";

import { parseSseDataEvents } from "./sse";

describe("parseSseDataEvents", () => {
  it("retains a split CRLF boundary until the next chunk arrives", () => {
    const first = parseSseDataEvents('data: {"part":1}\r\n\r');
    expect(first.events).toEqual([]);

    const second = parseSseDataEvents(`${first.rest}\ndata: next\r\n\r\n`);
    expect(second.events).toEqual(['{"part":1}', "next"]);
    expect(second.rest).toBe("");
  });

  it("joins multiple data fields and emits an unterminated tail on flush", () => {
    const parsed = parseSseDataEvents("data: first\ndata: second", true);
    expect(parsed.events).toEqual(["first\nsecond"]);
    expect(parsed.rest).toBe("");
  });

  it("ignores comments and events without data fields", () => {
    const parsed = parseSseDataEvents(": heartbeat\n\nevent: ping\n\n");
    expect(parsed.events).toEqual([]);
    expect(parsed.rest).toBe("");
  });
});

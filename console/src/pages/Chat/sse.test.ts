import { describe, expect, it } from "vitest";

import { parseSseDataEvents } from "./sse";

describe("parseSseDataEvents", () => {
  it("extracts data fields from LF-separated events", () => {
    const parsed = parseSseDataEvents('data: {"a":1}\n\ndata: {"b":2}\n\n');
    expect(parsed.events).toEqual(['{"a":1}', '{"b":2}']);
    expect(parsed.rest).toBe("");
  });

  it("accepts CRLF-separated events from a normalizing proxy", () => {
    const parsed = parseSseDataEvents(
      'data: {"a":1}\r\n\r\ndata: {"b":2}\r\n\r\n',
    );
    expect(parsed.events).toEqual(['{"a":1}', '{"b":2}']);
    expect(parsed.rest).toBe("");
  });

  it("accepts CR-separated events", () => {
    const parsed = parseSseDataEvents('data: {"a":1}\r\rdata: {"b":2}\r\r');
    expect(parsed.events).toEqual(['{"a":1}', '{"b":2}']);
  });

  it("accepts data fields without the optional space", () => {
    const parsed = parseSseDataEvents('data:{"a":1}\n\n');
    expect(parsed.events).toEqual(['{"a":1}']);
  });

  it("joins multiple data lines of one event", () => {
    const parsed = parseSseDataEvents('data: {"a":\ndata: 1}\n\n');
    expect(parsed.events).toEqual(['{"a":\n1}']);
  });

  it("ignores non-data fields and keeps the incomplete tail", () => {
    const parsed = parseSseDataEvents(
      'event: ping\ndata: {"a":1}\n\ndata: {"b"',
    );
    expect(parsed.events).toEqual(['{"a":1}']);
    expect(parsed.rest).toBe('data: {"b"');
  });

  it("flushes a trailing event that never saw its boundary", () => {
    const parsed = parseSseDataEvents('data: {"b":2}', true);
    expect(parsed.events).toEqual(['{"b":2}']);
    expect(parsed.rest).toBe("");
  });
});

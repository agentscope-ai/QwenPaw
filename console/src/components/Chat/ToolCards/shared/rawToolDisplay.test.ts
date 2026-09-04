import { describe, expect, it } from "vitest";
import { formatRawToolValue } from "./rawToolDisplay";

describe("formatRawToolValue", () => {
  it("pretty-prints JSON strings", () => {
    expect(formatRawToolValue('[{"type":"text","text":"done"}]')).toBe(
      '[\n  {\n    "type": "text",\n    "text": "done"\n  }\n]',
    );
  });

  it("replaces large base64 data while preserving its JSON structure", () => {
    const payload = "A".repeat(5_000);
    const output = JSON.stringify([
      {
        type: "data",
        source: { type: "base64", data: payload },
      },
    ]);

    const formatted = formatRawToolValue(output);
    const parsed = JSON.parse(formatted);

    expect(parsed).toEqual([
      {
        type: "data",
        source: {
          type: "base64",
          data: "[base64 data omitted: 5000 characters]",
        },
      },
    ]);
    expect(formatted).not.toContain(payload);
  });

  it("does not truncate ordinary large text fields", () => {
    const text = "plain text ".repeat(500);
    const formatted = formatRawToolValue({ type: "text", data: text });

    expect(JSON.parse(formatted)).toEqual({ type: "text", data: text });
  });

  it("omits large image payloads from common unannotated fields", () => {
    const payload = "A".repeat(5_000);
    const formatted = formatRawToolValue({
      image_data: payload,
      screenshot: payload,
      thumbnail: payload,
    });

    expect(JSON.parse(formatted)).toEqual({
      image_data: "[base64 data omitted: 5000 characters]",
      screenshot: "[base64 data omitted: 5000 characters]",
      thumbnail: "[base64 data omitted: 5000 characters]",
    });
  });

  it("stops formatting excessively deep structures", () => {
    const root: Record<string, unknown> = {};
    let current = root;
    for (let depth = 0; depth < 40; depth += 1) {
      const child: Record<string, unknown> = {};
      current.child = child;
      current = child;
    }

    expect(formatRawToolValue(root)).toContain(
      "[maximum display depth exceeded]",
    );
  });

  it("keeps non-JSON strings unchanged", () => {
    expect(formatRawToolValue("command completed")).toBe("command completed");
  });
});

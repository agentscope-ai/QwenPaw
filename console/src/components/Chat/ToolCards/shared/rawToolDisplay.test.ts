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

  it("replaces a top-level base64 data URL", () => {
    const value = `data:image/png;base64,${"A".repeat(5_000)}`;

    expect(formatRawToolValue(value)).toBe(
      `[base64 data omitted: ${value.length} characters]`,
    );
  });

  it("replaces a base64 data URL stored in image_url", () => {
    const imageUrl = `data:image/png;base64,${"A".repeat(5_000)}`;
    const formatted = formatRawToolValue({ image_url: imageUrl });

    expect(JSON.parse(formatted)).toEqual({
      image_url: `[base64 data omitted: ${imageUrl.length} characters]`,
    });
    expect(formatted).not.toContain(imageUrl);
  });

  it("replaces a large b64_json field", () => {
    const payload = "A".repeat(5_000);
    const formatted = formatRawToolValue({ b64_json: payload });

    expect(JSON.parse(formatted)).toEqual({
      b64_json: "[base64 data omitted: 5000 characters]",
    });
    expect(formatted).not.toContain(payload);
  });

  it("does not truncate ordinary large text fields", () => {
    const text = "plain text ".repeat(500);
    const formatted = formatRawToolValue({ type: "text", data: text });

    expect(JSON.parse(formatted)).toEqual({ type: "text", data: text });
  });

  it("keeps non-JSON strings unchanged", () => {
    expect(formatRawToolValue("command completed")).toBe("command completed");
  });
});

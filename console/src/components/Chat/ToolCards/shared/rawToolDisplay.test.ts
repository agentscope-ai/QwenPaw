import { describe, expect, it, vi } from "vitest";
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

  it("truncates oversized JSON strings before parsing them", () => {
    const parseSpy = vi.spyOn(JSON, "parse");
    const value = `{"data":"${"x".repeat(100_001)}"}`;

    const formatted = formatRawToolValue(value);
    const parseCalls = parseSpy.mock.calls.length;
    parseSpy.mockRestore();

    expect(parseCalls).toBe(0);
    expect(formatted.length).toBeLessThanOrEqual(100_500);
    expect(formatted).toContain("Raw value truncated");
    expect(formatted.match(/Raw value truncated/g) ?? []).toHaveLength(1);
    expect(formatted).not.toContain("…[truncated");
    expect(formatted).toContain("Switch to Current view for the full value");
  });

  it("keeps structure while truncating oversized object graphs", () => {
    const value = {
      head: "small",
      blob: "y".repeat(120_000),
      tail: { nested: "z".repeat(60_000) },
    };

    const formatted = formatRawToolValue(value);
    const parsed = JSON.parse(formatted) as {
      head: string;
      blob: string;
      tail: { nested: string };
    };

    expect(parsed.head).toBe("small");
    expect(parsed.blob.startsWith("y")).toBe(true);
    expect(parsed.blob).toContain("[truncated");
    expect(parsed.tail.nested).toContain("[truncated");
    expect(formatted.length).toBeLessThanOrEqual(100_500);
  });

  it("rejects oversized object graphs before copying or stringifying", () => {
    const stringifySpy = vi.spyOn(JSON, "stringify");
    const value = Array.from({ length: 2_001 }, () => null);

    const formatted = formatRawToolValue(value);
    const stringifyCalls = stringifySpy.mock.calls.length;
    stringifySpy.mockRestore();

    expect(stringifyCalls).toBe(0);
    expect(formatted).toContain("Raw value omitted");
    expect(formatted).toContain("node display budget");
  });

  it.each([1, 5, 20])(
    "bounds synchronous formatting for a %dMB fixture",
    (sizeMb) => {
      const value = "x".repeat(sizeMb * 1024 * 1024);
      let calls = 0;
      const startedAt = performance.now();
      calls += 1;
      const formatted = formatRawToolValue(value);
      const elapsedMs = performance.now() - startedAt;

      console.info(
        `raw-format-benchmark size=${sizeMb}MB calls=${calls} ` +
          `elapsedMs=${elapsedMs.toFixed(3)}`,
      );
      expect(calls).toBe(1);
      expect(formatted).toContain("Raw value truncated");
      expect(formatted.length).toBeLessThanOrEqual(100_500);
    },
  );
});

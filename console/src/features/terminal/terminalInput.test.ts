import { describe, expect, it } from "vitest";
import { terminalInputChunks } from "./terminalInput";

describe("terminal paste framing", () => {
  it("keeps supplementary Unicode intact at the frame boundary", () => {
    const input = "a".repeat(4095) + "𠮷" + "中".repeat(10000);
    const chunks = [...terminalInputChunks(input)];
    expect(chunks.join("")).toBe(input);
    expect(chunks.every((chunk) => chunk.length <= 4096)).toBe(true);
    expect(chunks[0]).toHaveLength(4095);
    expect(chunks[1].startsWith("𠮷")).toBe(true);
  });
});

import { afterEach, describe, expect, it, vi } from "vitest";
import { createSecureRandomHex } from "../secureRandom";

describe("createSecureRandomHex", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("uses the browser cryptographic random source", () => {
    const mathRandom = vi.spyOn(Math, "random").mockImplementation(() => {
      throw new Error("Math.random must not generate security-sensitive ids");
    });

    const value = createSecureRandomHex();

    expect(value).toMatch(/^[0-9a-f]{32}$/);
    expect(mathRandom).not.toHaveBeenCalled();
  });

  it("preserves the requested byte length", () => {
    expect(createSecureRandomHex(8)).toMatch(/^[0-9a-f]{16}$/);
  });
});

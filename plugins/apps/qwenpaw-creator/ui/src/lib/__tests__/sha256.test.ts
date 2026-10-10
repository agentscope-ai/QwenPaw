import { describe, expect, it } from "vitest";
import { sha256Bytes } from "@/lib/sha256";

function hex(bytes: Uint8Array): string {
  return Array.from(bytes)
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

describe("sha256Bytes", () => {
  it("matches the FIPS 180-4 test vectors", () => {
    const vectors: Array<[string, string]> = [
      ["", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"],
      [
        "abc",
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
      ],
      [
        "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq",
        "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1",
      ],
    ];
    for (const [input, expected] of vectors) {
      expect(hex(sha256Bytes(new TextEncoder().encode(input)))).toBe(expected);
    }
  });

  it("matches crypto.subtle for multi-byte UTF-8 and block boundaries", async () => {
    const samples = [
      "MISSING",
      JSON.stringify({ span: { start_tick: 0, end_tick: 120 } }),
      "字幕与时间线调整".repeat(9),
      "x".repeat(55),
      "x".repeat(64),
      "x".repeat(1000),
    ];
    for (const sample of samples) {
      const bytes = new TextEncoder().encode(sample);
      const expected = new Uint8Array(
        await globalThis.crypto.subtle.digest("SHA-256", bytes),
      );
      expect(hex(sha256Bytes(bytes))).toBe(hex(expected));
    }
  });
});

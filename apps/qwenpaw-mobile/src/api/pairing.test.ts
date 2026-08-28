import assert from "node:assert/strict";
import test from "node:test";

import { normalizeBaseUrl, parsePairingUri } from "./pairing";

test("normalizes a QwenPaw base URL", () => {
  assert.equal(normalizeBaseUrl("https://paw.example.com/"),
    "https://paw.example.com");
});

test("parses a version one pairing URI", () => {
  const ticket = "a".repeat(43);
  const payload = parsePairingUri(
    `qwenpaw://pair?v=1&base_url=https%3A%2F%2Fpaw.example.com&ticket=${ticket}`,
  );
  assert.equal(payload.baseUrl, "https://paw.example.com");
  assert.equal(payload.ticket, ticket);
});

test("rejects non-QwenPaw schemes", () => {
  assert.throws(() => parsePairingUri("https://example.com"));
});

import assert from "node:assert/strict";
import test from "node:test";

import { normalizeBaseUrl, parsePairingUri } from "./pairing";

test("normalizes a QwenPaw base URL", () => {
  assert.equal(
    normalizeBaseUrl("https://paw.example.com/"),
    "https://paw.example.com",
  );
});

test("parses a version one pairing URI", () => {
  const ticket = "a".repeat(43);
  const payload = parsePairingUri(
    `qwenpaw://pair?v=1&base_url=https%3A%2F%2Fpaw.example.com&ticket=${ticket}`,
  );
  assert.equal(payload.kind, "direct");
  if (payload.kind !== "direct") throw new Error("Expected direct pairing");
  assert.equal(payload.baseUrl, "https://paw.example.com");
  assert.equal(payload.ticket, ticket);
});

test("parses a version two Relay QR without putting its ticket in a URL", () => {
  const payload = parsePairingUri(
    JSON.stringify({
      type: "qwenpaw.relay.pairing",
      v: 2,
      issuer: "https://platform.agentscope.io",
      node_id: "a9a34d17-66d7-4604-b8e8-35e514e3ea10",
      qwenpaw_id: "e7d7813a-7c87-4e4a-9d47-b524c3c1d6df",
      pairing_ticket: `qprt_v1_${"a".repeat(43)}`,
      node_public_key_thumbprint: "b".repeat(43),
      dpop_nonce: "c".repeat(32),
      protocol_version: 1,
    }),
  );

  assert.equal(payload.kind, "relay");
  if (payload.kind !== "relay") throw new Error("Expected Relay pairing");
  assert.equal(payload.nodeId, "a9a34d17-66d7-4604-b8e8-35e514e3ea10");
  assert.equal(payload.pairingTicket.startsWith("qprt_v1_"), true);
});

test("rejects non-QwenPaw schemes", () => {
  assert.throws(() => parsePairingUri("https://example.com"));
});

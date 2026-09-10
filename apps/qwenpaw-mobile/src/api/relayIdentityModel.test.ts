import assert from "node:assert/strict";
import test from "node:test";

import {
  createRelayProof,
  relayDeviceKeyFromSecret,
  relayPublicJwk,
  relayPublicJwkThumbprint,
} from "./relayIdentityModel";

test("creates deterministic Ed25519 JWK and a token-bound proof", () => {
  const key = relayDeviceKeyFromSecret(
    Uint8Array.from({ length: 32 }, (_, i) => i),
  );
  const proof = createRelayProof({
    accessToken: "platform-token",
    key,
    method: "POST",
    nonce: "pairing-nonce",
    proofId: "proof-1",
    target: "https://platform.agentscope.io/api/v1/test?ignored=yes",
    issuedAt: 1_700_000_000,
  });
  const [header, payload, signature] = proof.split(".");

  assert.equal(relayPublicJwk(key).kty, "OKP");
  assert.equal(relayPublicJwkThumbprint(key).length, 43);
  assert.ok(header && payload && signature);
  assert.equal(proof.split(".").length, 3);
});

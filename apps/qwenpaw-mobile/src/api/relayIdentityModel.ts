import * as ed25519 from "@noble/ed25519";
import { sha256, sha512 } from "@noble/hashes/sha2.js";

ed25519.hashes.sha512 = sha512;
ed25519.hashes.sha512Async = async (message) => sha512(message);

export interface RelayDeviceKey {
  secretKey: Uint8Array;
  publicKey: Uint8Array;
}

export interface RelayPublicJwk {
  crv: "Ed25519";
  kty: "OKP";
  x: string;
}

export function relayDeviceKeyFromSecret(
  secretKey: Uint8Array,
): RelayDeviceKey {
  if (secretKey.length !== 32) throw new Error("Relay device key is invalid.");
  return {
    secretKey,
    publicKey: ed25519.getPublicKey(secretKey),
  };
}

export function relayPublicJwk(key: RelayDeviceKey): RelayPublicJwk {
  return {
    crv: "Ed25519",
    kty: "OKP",
    x: base64UrlEncode(key.publicKey),
  };
}

export function relayPublicJwkThumbprint(key: RelayDeviceKey): string {
  return base64UrlEncode(sha256(utf8(JSON.stringify(relayPublicJwk(key)))));
}

export function createRelayProof(input: {
  accessToken: string;
  key: RelayDeviceKey;
  method: string;
  nonce: string;
  proofId: string;
  target: string;
  issuedAt?: number;
}): string {
  const header = {
    alg: "EdDSA",
    jwk: relayPublicJwk(input.key),
    typ: "dpop+jwt",
  };
  const payload = {
    ath: base64UrlEncode(sha256(utf8(input.accessToken))),
    htm: input.method.toUpperCase(),
    htu: canonicalTarget(input.target),
    iat: input.issuedAt ?? Math.floor(Date.now() / 1000),
    jti: input.proofId,
    nonce: input.nonce,
  };
  const signingInput = `${encodeJson(header)}.${encodeJson(payload)}`;
  const signature = ed25519.sign(utf8(signingInput), input.key.secretKey);
  return `${signingInput}.${base64UrlEncode(signature)}`;
}

export function base64UrlEncode(value: Uint8Array): string {
  let binary = "";
  for (const byte of value) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
}

export function base64UrlDecode(value: string): Uint8Array {
  const padding = "=".repeat((4 - (value.length % 4)) % 4);
  const binary = atob(value.replace(/-/g, "+").replace(/_/g, "/") + padding);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

function encodeJson(value: unknown): string {
  return base64UrlEncode(utf8(JSON.stringify(value)));
}

function utf8(value: string): Uint8Array {
  return new TextEncoder().encode(value);
}

function canonicalTarget(value: string): string {
  const target = new URL(value);
  if (!["https:", "wss:", "http:", "ws:"].includes(target.protocol)) {
    throw new Error("Relay proof target is invalid.");
  }
  if (target.username || target.password || target.hash) {
    throw new Error("Relay proof target is invalid.");
  }
  const defaultPort =
    target.protocol === "https:" || target.protocol === "wss:" ? "443" : "80";
  const port =
    target.port && target.port !== defaultPort ? `:${target.port}` : "";
  return `${target.protocol}//${target.hostname.toLowerCase()}${port}${
    target.pathname || "/"
  }`;
}

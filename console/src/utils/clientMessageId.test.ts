/**
 * createClientMessageId / attachClientMessageId give every outbound
 * chat message a client-side id stored under metadata, used to correlate
 * optimistic UI entries with server-assigned ids after streaming starts.
 */
import { describe, it, expect, afterEach } from "vitest";
import {
  QWENPAW_CLIENT_MESSAGE_ID_KEY,
  createClientMessageId,
  attachClientMessageId,
} from "./clientMessageId";

const originalRandomUUID = crypto.randomUUID;
const originalGetRandomValues = crypto.getRandomValues;

afterEach(() => {
  // Restore whatever the environment provided (jsdom may define or not)
  Object.defineProperty(crypto, "randomUUID", {
    value: originalRandomUUID,
    configurable: true,
    writable: true,
  });
  Object.defineProperty(crypto, "getRandomValues", {
    value: originalGetRandomValues,
    configurable: true,
    writable: true,
  });
});

describe("createClientMessageId", () => {
  it("uses crypto.randomUUID when available", () => {
    Object.defineProperty(crypto, "randomUUID", {
      value: () => "uuid-fixed",
      configurable: true,
      writable: true,
    });
    expect(createClientMessageId()).toBe("uuid-fixed");
  });

  it("falls back to timestamp + random base36 when randomUUID is absent", () => {
    Object.defineProperty(crypto, "randomUUID", {
      value: undefined,
      configurable: true,
      writable: true,
    });
    Object.defineProperty(crypto, "getRandomValues", {
      value: (bytes: Uint8Array) => {
        bytes.fill(7);
        return bytes;
      },
      configurable: true,
      writable: true,
    });
    const id = createClientMessageId();
    // Format: "<timestamp>-<16 chars>"
    expect(id).toMatch(/^\d+-[0-9a-z]{16}$/);
  });

  it("generates distinct ids across calls", () => {
    const a = createClientMessageId();
    const b = createClientMessageId();
    expect(a).not.toBe(b);
  });
});

describe("attachClientMessageId", () => {
  it("stores the id under metadata using the reserved key", () => {
    const out = attachClientMessageId({ role: "user" }, "id-1");
    expect(out.metadata).toEqual({
      [QWENPAW_CLIENT_MESSAGE_ID_KEY]: "id-1",
    });
    // Original top-level fields survive
    expect(out.role).toBe("user");
  });

  it("preserves existing metadata fields", () => {
    const out = attachClientMessageId({ metadata: { foo: "bar" } }, "id-2") as {
      metadata: Record<string, unknown>;
    };
    expect(out.metadata.foo).toBe("bar");
    expect(out.metadata[QWENPAW_CLIENT_MESSAGE_ID_KEY]).toBe("id-2");
  });

  it("overwrites a previous client message id", () => {
    const first = attachClientMessageId({}, "id-old");
    const second = attachClientMessageId(first, "id-new");
    expect(
      (second.metadata as Record<string, unknown>)[
        QWENPAW_CLIENT_MESSAGE_ID_KEY
      ],
    ).toBe("id-new");
  });

  it("replaces non-object metadata instead of crashing", () => {
    const out = attachClientMessageId({ metadata: "garbage" }, "id-3");
    expect(out.metadata).toEqual({
      [QWENPAW_CLIENT_MESSAGE_ID_KEY]: "id-3",
    });
  });

  it("does not mutate the input message", () => {
    const input: Record<string, unknown> = { role: "user" };
    const out = attachClientMessageId(input, "id-4");
    expect(out).not.toBe(input);
    expect(input.metadata).toBeUndefined();
  });
});

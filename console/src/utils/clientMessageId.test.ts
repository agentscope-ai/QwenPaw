import { afterEach, describe, expect, it } from "vitest";

import {
  QWENPAW_CLIENT_MESSAGE_ID_KEY,
  attachClientMessageId,
  createClientMessageId,
  latestUserMessageId,
} from "./clientMessageId";

const originalRandomUUID = crypto.randomUUID;
const originalGetRandomValues = crypto.getRandomValues;

afterEach(() => {
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

describe("client message identity", () => {
  it("uses crypto.randomUUID when available", () => {
    Object.defineProperty(crypto, "randomUUID", {
      value: () => "uuid-fixed",
      configurable: true,
      writable: true,
    });
    expect(createClientMessageId()).toBe("uuid-fixed");
  });

  it("falls back when randomUUID is absent", () => {
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
    expect(createClientMessageId()).toMatch(/^\d+-[0-9a-z]{16}$/);
  });

  it("stores the id without mutating existing metadata", () => {
    const input = { role: "user", metadata: { foo: "bar" } };
    const output = attachClientMessageId(input, "id-1");
    expect(output).not.toBe(input);
    expect(output.metadata).toEqual({
      foo: "bar",
      [QWENPAW_CLIENT_MESSAGE_ID_KEY]: "id-1",
    });
    expect(input.metadata).toEqual({ foo: "bar" });
  });

  it("replaces malformed metadata", () => {
    expect(
      attachClientMessageId({ metadata: "invalid" }, "id-2").metadata,
    ).toEqual({
      [QWENPAW_CLIENT_MESSAGE_ID_KEY]: "id-2",
    });
  });

  it("uses the SDK-owned latest optimistic user message identity", () => {
    expect(
      latestUserMessageId([
        { id: "user-1", role: "user" },
        { id: "assistant-1", role: "assistant" },
        { id: "user-2", role: "user" },
      ]),
    ).toBe("user-2");
  });

  it("returns undefined when the latest user message has no identity", () => {
    expect(latestUserMessageId([{ role: "user" }])).toBeUndefined();
  });
});

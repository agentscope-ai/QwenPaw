import assert from "node:assert/strict";
import test from "node:test";

import {
  decodeRelayFrame,
  encodeRelayFrame,
  type RelayFrame,
} from "@qwenpaw/api-contract";

test("relay binary frame preserves its payload", () => {
  const frame: RelayFrame = {
    header: {
      v: 1,
      type: "data",
      stream_id: "stream-1",
      request_id: "request-1",
      sequence: 3,
      metadata: { content_type: "image/png" },
    },
    payload: Uint8Array.from([0, 1, 112, 110, 103]),
  };

  assert.deepEqual(decodeRelayFrame(encodeRelayFrame(frame)), frame);
});

test("relay session event requires stable identity fields", () => {
  assert.throws(
    () =>
      encodeRelayFrame({
        header: {
          v: 1,
          type: "session_event",
          sequence: 1,
          metadata: { session_id: "session-1" },
        },
        payload: new Uint8Array(),
      }),
    /event_id/,
  );
});

test("relay open only accepts a fixed operation id", () => {
  assert.doesNotThrow(() =>
    encodeRelayFrame({
      header: {
        v: 1,
        type: "open",
        stream_id: "stream-1",
        request_id: "request-1",
        metadata: {
          operation_id: "message.send",
          schema_version: 1,
        },
      },
      payload: new Uint8Array(),
    }),
  );
  assert.throws(
    () =>
      encodeRelayFrame({
        header: {
          v: 1,
          type: "open",
          stream_id: "stream-1",
          request_id: "request-1",
          metadata: {
            operation_id: "http.proxy",
            schema_version: 1,
          },
        },
        payload: new Uint8Array(),
      }),
    /operation_id/,
  );
});

test("relay rejects truncated input", () => {
  assert.throws(
    () => decodeRelayFrame(Uint8Array.from([0, 0, 0, 20, 123, 125])),
    /truncated/,
  );
});

import assert from "node:assert/strict";
import test from "node:test";

import { decodeRelayFrame, encodeRelayFrame } from "@qwenpaw/api-contract";

import { RelayMultiplexer } from "./relayMultiplexer";

class FakeSocket {
  binaryType = "";
  sent: (ArrayBuffer | Uint8Array)[] = [];
  private readonly listeners = new Map<
    string,
    ((event: { data?: unknown }) => void)[]
  >();

  addEventListener(
    type: string,
    listener: (event: { data?: unknown }) => void,
  ): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  close(): void {
    this.emit("close", {});
  }

  send(data: ArrayBuffer | Uint8Array): void {
    this.sent.push(data);
  }

  emit(type: string, event: { data?: unknown }): void {
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

test("mobile multiplexer sends a fixed operation and joins response chunks", async () => {
  const socket = new FakeSocket();
  const relay = new RelayMultiplexer(socket);
  const result = relay.request("agent.list", new TextEncoder().encode("{}"));
  assert.equal(socket.sent.length, 3);
  const open = decodeRelayFrame(socket.sent[0] as Uint8Array);
  const streamId = open.header.stream_id as string;
  assert.equal(open.header.metadata?.operation_id, "agent.list");

  socket.emit("message", {
    data: encodeRelayFrame({
      header: { v: 1, type: "data", stream_id: streamId },
      payload: new TextEncoder().encode('{"agents":'),
    }),
  });
  socket.emit("message", {
    data: encodeRelayFrame({
      header: { v: 1, type: "data", stream_id: streamId },
      payload: new TextEncoder().encode("[]}"),
    }),
  });
  socket.emit("message", {
    data: encodeRelayFrame({
      header: { v: 1, type: "end", stream_id: streamId },
      payload: new Uint8Array(),
    }),
  });

  assert.equal(new TextDecoder().decode(await result), '{"agents":[]}');
});

test("closed mobile multiplexer invalidates its cached connection", async () => {
  const socket = new FakeSocket();
  let closed = 0;
  const relay = new RelayMultiplexer(socket, undefined, () => {
    closed += 1;
  });

  socket.emit("error", {});
  socket.emit("close", {});

  assert.equal(closed, 1);
  await assert.rejects(
    relay.request("agent.list", new Uint8Array()),
    /安全中转已断开/,
  );
  assert.equal(socket.sent.length, 0);
});

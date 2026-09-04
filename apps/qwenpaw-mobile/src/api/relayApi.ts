import type { RelayOperation } from "@qwenpaw/api-contract";

import { connectRelayMobile } from "./relayConnection";
import type { RelayMultiplexer } from "./relayMultiplexer";
import { loadRelayBinding } from "../storage/relayIdentity";

const connections = new Map<string, Promise<RelayMultiplexer>>();
const encoder = new TextEncoder();
const decoder = new TextDecoder();

export async function relayJsonRequest<T>(
  nodeId: string,
  operation: RelayOperation,
  payload: Record<string, unknown>,
): Promise<T> {
  const relay = await relayForNode(nodeId);
  const result = await relay.request(
    operation,
    encoder.encode(JSON.stringify(payload)),
  );
  if (result.byteLength === 0) return undefined as T;
  return JSON.parse(decoder.decode(result)) as T;
}

export async function relayBytesRequest(
  nodeId: string,
  operation: RelayOperation,
  payload: Record<string, unknown>,
): Promise<Uint8Array> {
  const relay = await relayForNode(nodeId);
  return relay.request(operation, encoder.encode(JSON.stringify(payload)));
}

async function relayForNode(nodeId: string): Promise<RelayMultiplexer> {
  let pending = connections.get(nodeId);
  if (!pending) {
    pending = loadRelayBinding(nodeId)
      .then((binding) => {
        if (!binding) throw new Error("这只 QwenPaw 尚未完成安全配对");
        return connectRelayMobile(binding, () => {
          if (connections.get(nodeId) === pending) {
            connections.delete(nodeId);
          }
        });
      })
      .catch((error) => {
        connections.delete(nodeId);
        throw error;
      });
    connections.set(nodeId, pending);
  }
  return pending;
}

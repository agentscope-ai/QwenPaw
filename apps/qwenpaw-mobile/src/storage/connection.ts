import * as SecureStore from "expo-secure-store";

import type { Connection } from "../api/types";
import {
  connectionKey,
  type ConnectionRegistry,
  upsertConnection,
} from "./connectionModel";

export {
  connectionKey,
  type ConnectionRegistry,
  upsertConnection,
  withoutConnection,
} from "./connectionModel";

const LEGACY_CONNECTION_KEY = "qwenpaw.mobile.connection.v1";
const CONNECTIONS_KEY = "qwenpaw.mobile.connections.v2";

export async function loadConnectionRegistry(): Promise<ConnectionRegistry> {
  const stored = await SecureStore.getItemAsync(CONNECTIONS_KEY);
  if (stored) {
    const parsed = parseRegistry(stored);
    if (parsed) return parsed;
    await SecureStore.deleteItemAsync(CONNECTIONS_KEY);
  }

  const legacy = await SecureStore.getItemAsync(LEGACY_CONNECTION_KEY);
  if (!legacy) return { activeKey: null, connections: [] };
  try {
    const connection = JSON.parse(legacy) as Connection;
    const registry = upsertConnection(
      { activeKey: null, connections: [] },
      connection,
    );
    await saveConnectionRegistry(registry);
    await SecureStore.deleteItemAsync(LEGACY_CONNECTION_KEY);
    return registry;
  } catch {
    await SecureStore.deleteItemAsync(LEGACY_CONNECTION_KEY);
    return { activeKey: null, connections: [] };
  }
}

export async function saveConnectionRegistry(
  registry: ConnectionRegistry,
): Promise<void> {
  await SecureStore.setItemAsync(CONNECTIONS_KEY, JSON.stringify(registry), {
    keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
  });
}

function parseRegistry(value: string): ConnectionRegistry | null {
  try {
    const parsed = JSON.parse(value) as Partial<ConnectionRegistry>;
    if (!Array.isArray(parsed.connections)) return null;
    const connections = parsed.connections.filter(isConnection);
    const requestedKey = typeof parsed.activeKey === "string"
      ? parsed.activeKey
      : null;
    const activeKey = connections.some(
      (connection) => connectionKey(connection) === requestedKey,
    )
      ? requestedKey
      : connections[0] ? connectionKey(connections[0]) : null;
    return { activeKey, connections };
  } catch {
    return null;
  }
}

function isConnection(value: unknown): value is Connection {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const connection = value as Partial<Connection>;
  return typeof connection.baseUrl === "string" &&
    typeof connection.token === "string" &&
    typeof connection.username === "string" &&
    typeof connection.agentId === "string";
}

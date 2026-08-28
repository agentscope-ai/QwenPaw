import type { Connection } from "../api/types";

export interface ConnectionRegistry {
  activeKey: string | null;
  connections: Connection[];
}

export function connectionKey(connection: Connection): string {
  const source = connection.source ?? "private";
  const baseUrl = connection.baseUrl.trim().replace(/\/+$/, "");
  return `${source}:${baseUrl}`;
}

export function findConnectionByBaseUrl(
  connections: Connection[],
  source: NonNullable<Connection["source"]>,
  baseUrl: string,
): Connection | null {
  const normalized = baseUrl.trim().replace(/\/+$/, "");
  return connections.find((connection) =>
    (connection.source ?? "private") === source &&
    connection.baseUrl.trim().replace(/\/+$/, "") === normalized
  ) ?? null;
}

export function upsertConnection(
  registry: ConnectionRegistry,
  connection: Connection,
  activate = true,
): ConnectionRegistry {
  const key = connectionKey(connection);
  const connections = registry.connections.some(
    (item) => connectionKey(item) === key,
  )
    ? registry.connections.map((item) =>
      connectionKey(item) === key ? connection : item)
    : [...registry.connections, connection];
  return {
    activeKey: activate ? key : registry.activeKey,
    connections,
  };
}

export function withoutConnection(
  registry: ConnectionRegistry,
  key: string,
): ConnectionRegistry {
  const connections = registry.connections.filter(
    (connection) => connectionKey(connection) !== key,
  );
  return {
    activeKey: registry.activeKey === key
      ? connections[0] ? connectionKey(connections[0]) : null
      : registry.activeKey,
    connections,
  };
}

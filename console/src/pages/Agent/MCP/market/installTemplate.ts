import type { MCPClientInfo } from "../../../../api/types";
import type { MCPMarketTemplate } from "./mcpTemplates";
import { formatMarketDescription } from "./clientMeta";

const ARG_ONLY_FIELD_KEYS = new Set([
  "allowed_directories",
  "redis_url",
  "sqlite_path",
]);

export type MCPTransport = "stdio" | "streamable_http" | "sse";

export interface MCPClientCreatePayload {
  name: string;
  description?: string;
  command: string;
  transport?: MCPTransport;
  url?: string;
  headers?: Record<string, string>;
  args?: string[];
  env?: Record<string, string>;
  cwd?: string;
}

function parseBearerToken(headerValue: string): string {
  const trimmed = headerValue.trim();
  const match = trimmed.match(/^bearer\s+(.+)$/i);
  return match ? match[1].trim() : trimmed;
}

export function isClientKeyTaken(key: string, existingKeys: string[]): boolean {
  const normalized = key.trim().toLowerCase();
  return existingKeys.some((k) => k.toLowerCase() === normalized);
}

export function validateTemplateFields(
  template: MCPMarketTemplate,
  fieldValues: Record<string, string>,
): { valid: boolean; missingKeys: string[] } {
  const missingKeys: string[] = [];
  for (const field of template.fields) {
    if (!field.required) continue;
    const value = (fieldValues[field.key] ?? "").trim();
    if (!value) missingKeys.push(field.key);
  }
  return { valid: missingKeys.length === 0, missingKeys };
}

function extraArgsAfterTemplate(
  clientArgs: string[],
  template: MCPMarketTemplate,
): string[] {
  const base = template.args ?? [];
  if (clientArgs.length <= base.length) return [];
  for (let i = 0; i < base.length; i++) {
    if (clientArgs[i] !== base[i]) {
      return clientArgs.slice(i);
    }
  }
  return clientArgs.slice(base.length);
}

function readFieldFromClient(
  template: MCPMarketTemplate,
  client: MCPClientInfo,
  field: MCPMarketTemplate["fields"][number],
): string | undefined {
  if (field.headerKey) {
    const headerVal =
      client.headers?.[field.headerKey] ??
      client.headers?.[field.headerKey.toLowerCase()];
    if (headerVal) {
      const prefix = field.headerPrefix ?? "";
      if (prefix && headerVal.startsWith(prefix)) {
        return headerVal.slice(prefix.length).trim();
      }
      return parseBearerToken(headerVal);
    }
    return undefined;
  }
  const envKey = field.envKey ?? field.key;
  const fromClient = client.env?.[envKey];
  if (fromClient !== undefined && fromClient !== "") {
    return fromClient;
  }
  return template.envDefaults?.[envKey];
}

/** Reverse `buildClientPayload` for market client edit forms. */
export function extractFieldValuesFromClient(
  template: MCPMarketTemplate,
  client: MCPClientInfo,
): Record<string, string> {
  const values: Record<string, string> = {};
  const isHttp =
    template.transport === "streamable_http" || template.transport === "sse";

  if (isHttp) {
    if (client.url?.trim()) values.url = client.url.trim();
    else if (template.url) values.url = template.url;
  }

  const suffix = extraArgsAfterTemplate(client.args ?? [], template);

  for (const field of template.fields) {
    if (ARG_ONLY_FIELD_KEYS.has(field.key)) {
      if (field.key === "allowed_directories") {
        values.allowed_directories = suffix.join("\n");
      } else if (field.key === "redis_url") {
        values.redis_url = suffix[0] ?? "";
      } else if (field.key === "sqlite_path") {
        values.sqlite_path = suffix[0] ?? "";
      }
      continue;
    }
    const v = readFieldFromClient(template, client, field);
    if (v !== undefined) {
      values[field.key] = v;
    }
  }

  return values;
}

export function buildClientPayload(
  template: MCPMarketTemplate,
  fieldValues: Record<string, string>,
  clientKey: string,
  displayName: string,
  userNote?: string,
): MCPClientCreatePayload {
  const name = displayName.trim() || clientKey.trim();
  const description = formatMarketDescription(template.id, userNote);

  const isHttp =
    template.transport === "streamable_http" || template.transport === "sse";

  if (isHttp) {
    const url = (fieldValues.url ?? "").trim() || (template.url ?? "").trim();
    const headers: Record<string, string> = {};
    for (const field of template.fields) {
      if (!field.headerKey) continue;
      const raw = (fieldValues[field.key] ?? "").trim();
      if (!raw) continue;
      const prefix = field.headerPrefix ?? "";
      headers[field.headerKey] = `${prefix}${raw}`;
    }
    return {
      name,
      description,
      transport: template.transport,
      command: "",
      url,
      headers,
      args: [],
      env: {},
    };
  }

  const env: Record<string, string> = { ...(template.envDefaults ?? {}) };

  for (const field of template.fields) {
    const raw = (fieldValues[field.key] ?? "").trim();
    if (!raw || ARG_ONLY_FIELD_KEYS.has(field.key) || field.headerKey) continue;
    const envKey = field.envKey ?? field.key;
    env[envKey] = raw;
  }

  if (!env.MYSQL_PORT && template.id === "mysql") {
    env.MYSQL_PORT = "3306";
  }

  const args = [...(template.args ?? [])];
  if (fieldValues.allowed_directories?.trim()) {
    const dirs = fieldValues.allowed_directories
      .split(/[\n,]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    args.push(...dirs);
  }
  if (fieldValues.redis_url?.trim()) {
    args.push(fieldValues.redis_url.trim());
  }
  if (fieldValues.sqlite_path?.trim()) {
    args.push(fieldValues.sqlite_path.trim());
  }

  return {
    name,
    description,
    transport: "stdio",
    command: template.command ?? "npx",
    args,
    env,
    url: "",
    headers: {},
  };
}

export type MCPClientUpdatePayload = Omit<MCPClientCreatePayload, "name"> & {
  name: string;
};

/** Build PUT body for editing an installed market client. */
export function buildClientUpdatePayload(
  template: MCPMarketTemplate,
  fieldValues: Record<string, string>,
  clientKey: string,
  displayName: string,
  userNote?: string,
): MCPClientUpdatePayload {
  const created = buildClientPayload(
    template,
    fieldValues,
    clientKey,
    displayName,
    userNote,
  );
  return {
    name: created.name,
    description: created.description,
    transport: created.transport,
    command: created.command,
    url: created.url,
    headers: created.headers,
    args: created.args,
    env: created.env,
  };
}

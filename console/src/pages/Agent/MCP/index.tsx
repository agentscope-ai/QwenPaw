import { useMemo, useState } from "react";
import { Button, Empty, Modal, Input, message } from "@agentscope-ai/design";
import type { MCPClientInfo } from "../../../api/types";
import { MCPClientCard } from "./components";
import { useMCP } from "./useMCP";
import { useTranslation } from "react-i18next";

type MCPTransport = "stdio" | "streamable_http" | "sse";

type RawMCPClientData = {
  name?: unknown;
  title?: unknown;
  description?: unknown;
  desc?: unknown;
  remark?: unknown;
  enabled?: unknown;
  isActive?: unknown;
  transport?: unknown;
  type?: unknown;
  url?: unknown;
  baseUrl?: unknown;
  headers?: unknown;
  command?: unknown;
  args?: unknown;
  env?: unknown;
  cwd?: unknown;
};

const STANDARD_FORMAT_TEMPLATE = `{
  "mcpServers": {
    "example-client": {
      "name": "Example Client",
      "description": "Optional client description",
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@example/mcp-server"],
      "env": {
        "API_KEY": "<YOUR_API_KEY>"
      },
      "cwd": ""
    }
  }
}`;

const DIRECT_FORMAT_TEMPLATE = `{
  "example-client": {
    "name": "Example Client",
    "description": "Optional client description",
    "transport": "stdio",
    "command": "npx",
    "args": ["-y", "@example/mcp-server"],
    "env": {
      "API_KEY": "<YOUR_API_KEY>"
    }
  }
}`;

const SINGLE_FORMAT_TEMPLATE = `{
  "key": "example-client",
  "name": "Example Client",
  "description": "Optional client description",
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "@example/mcp-server"],
  "env": {
    "API_KEY": "<YOUR_API_KEY>"
  }
}`;

const STREAMABLE_HTTP_TEMPLATE = `{
  "mcpServers": {
    "example_mcp": {
      "name": "Example Mcp Server",
      "description": "Remote MCP endpoint over HTTP",
      "transport": "streamable_http",
      "url": "http://127.0.0.1:8585/mcp",
      "headers": {
        "Authorization": "Bearer <YOUR_TOKEN>"
      }
    }
  }
}`;

const DEFAULT_MCP_IMPORT_JSON = STANDARD_FORMAT_TEMPLATE;

function normalizeTransport(raw?: unknown): MCPTransport | undefined {
  if (typeof raw !== "string") return undefined;
  const value = raw.trim().toLowerCase();
  switch (value) {
    case "stdio":
      return "stdio";
    case "sse":
      return "sse";
    case "streamablehttp":
    case "streamable_http":
    case "streamable-http":
    case "http":
      return "streamable_http";
    default:
      return undefined;
  }
}

function normalizeClientData(key: string, rawData: RawMCPClientData) {
  const normalizedName = rawData.name ?? rawData.title ?? key;
  const normalizedDescription =
    rawData.description ?? rawData.desc ?? rawData.remark ?? "";

  const hasUrl = Boolean(rawData.url || rawData.baseUrl);
  const transport =
    normalizeTransport(rawData.transport ?? rawData.type) ??
    (hasUrl || !rawData.command ? "streamable_http" : "stdio");

  const command =
    transport === "stdio" ? (rawData.command ?? "").toString() : "";

  return {
    name: String(normalizedName),
    description: String(normalizedDescription),
    enabled: Boolean(rawData.enabled ?? rawData.isActive ?? true),
    transport,
    url: String(rawData.url ?? rawData.baseUrl ?? ""),
    headers:
      rawData.headers && typeof rawData.headers === "object"
        ? (rawData.headers as Record<string, string>)
        : {},
    command,
    args: Array.isArray(rawData.args) ? rawData.args : [],
    env:
      rawData.env && typeof rawData.env === "object"
        ? (rawData.env as Record<string, string>)
        : {},
    cwd: String(rawData.cwd ?? ""),
  };
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function slugifyClientKey(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function inferSingleClientKey(payload: Record<string, unknown>): string {
  const explicitKey = typeof payload.key === "string" ? payload.key.trim() : "";
  if (explicitKey) {
    return explicitKey;
  }

  const nameCandidate =
    typeof payload.name === "string"
      ? payload.name
      : typeof payload.title === "string"
      ? payload.title
      : "";

  const inferred = slugifyClientKey(nameCandidate);
  return inferred || "mcp-client";
}

function validateClientBeforeCreate(
  key: string,
  data: ReturnType<typeof normalizeClientData>,
) {
  if (!key.trim()) {
    throw new Error("Client key cannot be empty");
  }

  if (!data.name.trim()) {
    throw new Error(`Client '${key}' requires a non-empty name`);
  }

  if (data.transport === "stdio") {
    if (!data.command.trim()) {
      throw new Error(`Client '${key}' with stdio transport requires command`);
    }
    return;
  }

  if (!data.url.trim()) {
    throw new Error(
      `Client '${key}' with ${data.transport} transport requires url`,
    );
  }

  try {
    const parsedUrl = new URL(data.url);
    if (!["http:", "https:"].includes(parsedUrl.protocol)) {
      throw new Error();
    }
  } catch {
    throw new Error(
      `Client '${key}' url must be a valid http(s) URL for ${data.transport} transport`,
    );
  }
}

function parseClientsFromImportJson(newClientJson: string) {
  const parsed: unknown = JSON.parse(newClientJson);

  const clientsToCreate: Array<{
    key: string;
    data: ReturnType<typeof normalizeClientData>;
  }> = [];

  if (isPlainObject(parsed) && isPlainObject(parsed.mcpServers)) {
    Object.entries(parsed.mcpServers).forEach(
      ([key, data]: [string, unknown]) => {
        clientsToCreate.push({
          key,
          data: normalizeClientData(key, data as RawMCPClientData),
        });
      },
    );
  } else if (
    isPlainObject(parsed) &&
    (parsed.command || parsed.url || parsed.baseUrl)
  ) {
    const key = inferSingleClientKey(parsed);
    const { key: _ignored, ...clientData } = parsed;
    clientsToCreate.push({
      key,
      data: normalizeClientData(key, clientData as RawMCPClientData),
    });
  } else if (isPlainObject(parsed)) {
    Object.entries(parsed).forEach(([key, data]: [string, unknown]) => {
      const candidate =
        data && typeof data === "object" ? (data as RawMCPClientData) : null;
      if (
        candidate &&
        (candidate.command || candidate.url || candidate.baseUrl)
      ) {
        clientsToCreate.push({
          key,
          data: normalizeClientData(key, candidate),
        });
      }
    });
  }

  return clientsToCreate;
}

function MCPPage() {
  const { t } = useTranslation();
  const {
    clients,
    loading,
    refreshStatuses,
    queuedRefreshKeys,
    refreshingKeys,
    toggleEnabled,
    deleteClient,
    createClient,
    updateClient,
  } = useMCP();
  const [hoverKey, setHoverKey] = useState<string | null>(null);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [newClientJson, setNewClientJson] = useState(DEFAULT_MCP_IMPORT_JSON);

  const importPreview = useMemo(() => {
    try {
      const clientsToCreate = parseClientsFromImportJson(newClientJson);
      if (clientsToCreate.length === 0) {
        return {
          valid: false,
          clients: [] as Array<{
            key: string;
            data: ReturnType<typeof normalizeClientData>;
          }>,
          error: t("mcp.importNoClientFound"),
        };
      }

      clientsToCreate.forEach(({ key, data }) => {
        validateClientBeforeCreate(key, data);
      });

      return {
        valid: true,
        clients: clientsToCreate,
        error: "",
      };
    } catch (error) {
      if (error instanceof SyntaxError) {
        return {
          valid: false,
          clients: [] as Array<{
            key: string;
            data: ReturnType<typeof normalizeClientData>;
          }>,
          error: t("mcp.invalidJson"),
        };
      }

      return {
        valid: false,
        clients: [] as Array<{
          key: string;
          data: ReturnType<typeof normalizeClientData>;
        }>,
        error: error instanceof Error ? error.message : t("mcp.createError"),
      };
    }
  }, [newClientJson, t]);

  const handleFillTemplate = (template: string) => {
    setNewClientJson(template);
  };

  const handleToggleEnabled = async (
    client: MCPClientInfo,
    e?: React.MouseEvent,
  ) => {
    e?.stopPropagation();
    await toggleEnabled(client);
  };

  const handleDelete = async (client: MCPClientInfo, e?: React.MouseEvent) => {
    e?.stopPropagation();
    await deleteClient(client);
  };

  const handleCreateClient = async () => {
    try {
      const clientsToCreate = parseClientsFromImportJson(newClientJson);

      if (clientsToCreate.length === 0) {
        throw new Error(t("mcp.importNoClientFound"));
      }

      clientsToCreate.forEach(({ key, data }) => {
        validateClientBeforeCreate(key, data);
      });

      // Create all clients
      let allSuccess = true;
      for (const { key, data } of clientsToCreate) {
        const success = await createClient(key, data);
        if (!success) allSuccess = false;
      }

      if (allSuccess) {
        setCreateModalOpen(false);
        setNewClientJson(DEFAULT_MCP_IMPORT_JSON);
      }
    } catch (error) {
      if (error instanceof SyntaxError) {
        message.error(t("mcp.invalidJson"));
        return;
      }
      const text =
        error instanceof Error ? error.message : t("mcp.createError");
      message.error(text);
    }
  };

  return (
    <div style={{ padding: 24 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 16,
        }}
      >
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 600, marginBottom: 4 }}>
            {t("mcp.title")}
          </h1>
          <p style={{ margin: 0, color: "#999", fontSize: 14 }}>
            {t("mcp.description")}
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Button
            onClick={() => void refreshStatuses()}
            loading={refreshingKeys.length > 0 || queuedRefreshKeys.length > 0}
          >
            {t("mcp.refreshStatus")}
          </Button>
          <Button type="primary" onClick={() => setCreateModalOpen(true)}>
            {t("mcp.create")}
          </Button>
        </div>
      </div>

      {loading ? (
        <div style={{ textAlign: "center", padding: 60 }}>
          <p style={{ color: "#999" }}>{t("common.loading")}</p>
        </div>
      ) : clients.length === 0 ? (
        <Empty description={t("mcp.emptyState")} />
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))",
            gap: 20,
          }}
        >
          {clients.map((client) => (
            <MCPClientCard
              key={client.key}
              client={client}
              onToggle={handleToggleEnabled}
              onDelete={handleDelete}
              onUpdate={updateClient}
              runtimeStateOverride={
                refreshingKeys.includes(client.key)
                  ? "checking"
                  : queuedRefreshKeys.includes(client.key)
                  ? "queued"
                  : undefined
              }
              isHovered={hoverKey === client.key}
              onMouseEnter={() => setHoverKey(client.key)}
              onMouseLeave={() => setHoverKey(null)}
            />
          ))}
        </div>
      )}

      <Modal
        title={t("mcp.create")}
        open={createModalOpen}
        onCancel={() => setCreateModalOpen(false)}
        footer={
          <div style={{ textAlign: "right" }}>
            <Button
              onClick={() => setCreateModalOpen(false)}
              style={{ marginRight: 8 }}
            >
              {t("common.cancel")}
            </Button>
            <Button type="primary" onClick={handleCreateClient}>
              {t("common.create")}
            </Button>
          </div>
        }
        width={800}
      >
        <div style={{ marginBottom: 12 }}>
          <p style={{ margin: 0, fontSize: 13, color: "#666" }}>
            {t("mcp.formatSupport")}:
          </p>
          <ul
            style={{
              margin: "8px 0",
              padding: "0 0 0 20px",
              fontSize: 12,
              color: "#999",
            }}
          >
            <li>
              Standard format:{" "}
              <code>{`{ "mcpServers": { "key": {...} } }`}</code>
              <button
                type="button"
                onClick={() => handleFillTemplate(STANDARD_FORMAT_TEMPLATE)}
                style={{
                  marginLeft: 8,
                  border: "1px solid #d9d9d9",
                  borderRadius: 4,
                  background: "#fff",
                  color: "#555",
                  fontSize: 12,
                  lineHeight: "20px",
                  padding: "0 8px",
                  cursor: "pointer",
                }}
              >
                Fill
              </button>
            </li>
            <li>
              Direct format: <code>{`{ "key": {...} }`}</code>
              <button
                type="button"
                onClick={() => handleFillTemplate(DIRECT_FORMAT_TEMPLATE)}
                style={{
                  marginLeft: 8,
                  border: "1px solid #d9d9d9",
                  borderRadius: 4,
                  background: "#fff",
                  color: "#555",
                  fontSize: 12,
                  lineHeight: "20px",
                  padding: "0 8px",
                  cursor: "pointer",
                }}
              >
                Fill
              </button>
            </li>
            <li>
              Single format:{" "}
              <code>{`{ "key": "...", "name": "...", "command": "..." }`}</code>
              <button
                type="button"
                onClick={() => handleFillTemplate(SINGLE_FORMAT_TEMPLATE)}
                style={{
                  marginLeft: 8,
                  border: "1px solid #d9d9d9",
                  borderRadius: 4,
                  background: "#fff",
                  color: "#555",
                  fontSize: 12,
                  lineHeight: "20px",
                  padding: "0 8px",
                  cursor: "pointer",
                }}
              >
                Fill
              </button>
            </li>
            <li>
              streamable_http example:{" "}
              <code>{`{ "mcpServers": { "key": { "transport": "streamable_http", "url": "..." } } }`}</code>
              <button
                type="button"
                onClick={() => handleFillTemplate(STREAMABLE_HTTP_TEMPLATE)}
                style={{
                  marginLeft: 8,
                  border: "1px solid #d9d9d9",
                  borderRadius: 4,
                  background: "#fff",
                  color: "#555",
                  fontSize: 12,
                  lineHeight: "20px",
                  padding: "0 8px",
                  cursor: "pointer",
                }}
              >
                Fill
              </button>
            </li>
          </ul>
        </div>
        <Input.TextArea
          value={newClientJson}
          onChange={(e) => setNewClientJson(e.target.value)}
          autoSize={{ minRows: 15, maxRows: 25 }}
          style={{
            fontFamily: "Monaco, Courier New, monospace",
            fontSize: 13,
          }}
        />
        <div
          style={{
            marginTop: 12,
            border: "1px solid #f0f0f0",
            borderRadius: 8,
            padding: 12,
            background: "#fafafa",
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 8,
            }}
          >
            <strong>{t("mcp.importPreview")}</strong>
            <span style={{ color: "#666", fontSize: 12 }}>
              {t("mcp.importPreviewCount", {
                count: importPreview.clients.length,
              })}
            </span>
          </div>

          {!importPreview.valid ? (
            <div style={{ color: "#cf1322", fontSize: 12 }}>
              {importPreview.error}
            </div>
          ) : (
            <div
              style={{
                maxHeight: 220,
                overflowY: "auto",
                display: "grid",
                gap: 8,
              }}
            >
              {importPreview.clients.map(({ key, data }) => (
                <div
                  key={key}
                  style={{
                    border: "1px solid #e8e8e8",
                    borderRadius: 6,
                    padding: "8px 10px",
                    background: "#fff",
                    fontSize: 12,
                  }}
                >
                  <div style={{ fontWeight: 600, marginBottom: 2 }}>{key}</div>
                  <div style={{ color: "#595959", marginBottom: 2 }}>
                    {data.name} | {data.transport}
                  </div>
                  <div style={{ color: "#8c8c8c" }}>
                    {data.transport === "stdio"
                      ? `${t("mcp.importPreviewCommand")}: ${data.command}`
                      : `${t("mcp.importPreviewUrl")}: ${data.url}`}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </Modal>
    </div>
  );
}

export default MCPPage;

import { useState } from "react";
import { Button, Empty, Modal } from "@agentscope-ai/design";
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

function MCPPage() {
  const { t } = useTranslation();
  const {
    clients,
    loading,
    toggleEnabled,
    deleteClient,
    createClient,
    updateClient,
  } = useMCP();
  const [hoverKey, setHoverKey] = useState<string | null>(null);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [newClientJson, setNewClientJson] = useState(DEFAULT_MCP_IMPORT_JSON);

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
      const parsed = JSON.parse(newClientJson);

      // Support two formats:
      // Format 1: { "mcpServers": { "key": { "command": "...", ... } } }
      // Format 2: { "key": { "command": "...", ... } }
      // Format 3: { "key": "...", "name": "...", "command": "...", ... } (direct)

      const clientsToCreate: Array<{
        key: string;
        data: ReturnType<typeof normalizeClientData>;
      }> = [];

      if (parsed.mcpServers) {
        // Format 1: nested mcpServers
        Object.entries(parsed.mcpServers).forEach(
          ([key, data]: [string, unknown]) => {
            clientsToCreate.push({
              key,
              data: normalizeClientData(key, data as RawMCPClientData),
            });
          },
        );
      } else if (
        parsed.key &&
        (parsed.command || parsed.url || parsed.baseUrl)
      ) {
        // Format 3: direct format with key field
        const { key, ...clientData } = parsed;
        clientsToCreate.push({
          key,
          data: normalizeClientData(key, clientData as RawMCPClientData),
        });
      } else {
        // Format 2: direct client objects with keys
        Object.entries(parsed).forEach(([key, data]: [string, unknown]) => {
          const candidate =
            data && typeof data === "object"
              ? (data as RawMCPClientData)
              : null;
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
    } catch {
      alert("Invalid JSON format");
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
        <Button type="primary" onClick={() => setCreateModalOpen(true)}>
          {t("mcp.create")}
        </Button>
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
        <textarea
          value={newClientJson}
          onChange={(e) => setNewClientJson(e.target.value)}
          style={{
            width: "100%",
            minHeight: 400,
            fontFamily: "Monaco, Courier New, monospace",
            fontSize: 13,
            padding: 16,
            border: "1px solid #d9d9d9",
            borderRadius: 4,
            resize: "vertical",
          }}
        />
      </Modal>
    </div>
  );
}

export default MCPPage;

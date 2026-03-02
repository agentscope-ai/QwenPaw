import { useState } from "react";
import { Button, Empty, Modal } from "@agentscope-ai/design";
import type { MCPClientInfo } from "../../../api/types";
import { MCPClientCard } from "./components";
import { useMCP } from "./useMCP";
import { useTranslation } from "react-i18next";

type MCPTransport = "stdio" | "streamable_http" | "sse";

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
    case "http":
      return "streamable_http";
    default:
      return undefined;
  }
}

function normalizeClientData(key: string, rawData: any) {
  const transport =
    normalizeTransport(rawData.transport ?? rawData.type) ??
    (rawData.url || rawData.baseUrl || !rawData.command
      ? "streamable_http"
      : "stdio");

  const command =
    transport === "stdio" ? (rawData.command ?? "").toString() : "";

  return {
    name: rawData.name || key,
    description: rawData.description || "",
    enabled: rawData.enabled ?? rawData.isActive ?? true,
    transport,
    url: (rawData.url || rawData.baseUrl || "").toString(),
    headers: rawData.headers || {},
    command,
    args: Array.isArray(rawData.args) ? rawData.args : [],
    env: rawData.env || {},
    cwd: (rawData.cwd || "").toString(),
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
  const [newClientJson, setNewClientJson] = useState(`{
  "mcpServers": {
    "example-client": {
      "command": "npx",
      "args": ["-y", "@example/mcp-server"],
      "env": {
        "API_KEY": "<YOUR_API_KEY>"
      }
    }
  }
}`);

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

      let clientsToCreate: Array<{ key: string; data: any }> = [];

      if (parsed.mcpServers) {
        // Format 1: nested mcpServers
        Object.entries(parsed.mcpServers).forEach(
          ([key, data]: [string, any]) => {
            clientsToCreate.push({
              key,
              data: normalizeClientData(key, data),
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
          data: normalizeClientData(key, clientData),
        });
      } else {
        // Format 2: direct client objects with keys
        Object.entries(parsed).forEach(([key, data]: [string, any]) => {
          if (
            typeof data === "object" &&
            (data.command || data.url || data.baseUrl)
          ) {
            clientsToCreate.push({
              key,
              data: normalizeClientData(key, data),
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
        setNewClientJson(`{
  "mcpServers": {
    "example-client": {
      "command": "npx",
      "args": ["-y", "@example/mcp-server"],
      "env": {
        "API_KEY": "<YOUR_API_KEY>"
      }
    }
  }
}`);
      }
    } catch (error) {
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
            </li>
            <li>
              Direct format: <code>{`{ "key": {...} }`}</code>
            </li>
            <li>
              Single format:{" "}
              <code>{`{ "key": "...", "name": "...", "command": "..." }`}</code>
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

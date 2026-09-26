import { Cascade } from "@/components/interaction/Cascade";
import { SharedModal as Modal } from "@/components/interaction/SharedModal";
import { useState, useCallback } from "react";
import { Button, Empty, Input, Select } from "@agentscope-ai/design";
import { Tabs, Alert, Segmented } from "antd";
import InlineHelp from "@/components/InlineHelp";
import { LockKeyhole, Plus, Server, Search } from "lucide-react";
import type { MCPClientInfo } from "../../../api/types";
import { MCPClientCard } from "./components";
import { useMCP } from "./useMCP";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import styles from "./index.module.less";

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
    case "streamable-http":
    case "http":
      return "streamable_http";
    default:
      return undefined;
  }
}

function normalizeClientData(key: string, rawData: Record<string, unknown>) {
  const transport =
    normalizeTransport(
      (rawData.transport as string) ?? (rawData.type as string),
    ) ??
    (rawData.url || rawData.baseUrl || !rawData.command
      ? "streamable_http"
      : "stdio");

  const command =
    transport === "stdio" ? ((rawData.command ?? "") as string) : "";

  return {
    name: (rawData.name as string) || key,
    description: (rawData.description as string) || "",
    enabled:
      (rawData.enabled as boolean) ?? (rawData.isActive as boolean) ?? true,
    transport,
    url: (rawData.url || rawData.baseUrl || "") as string,
    headers: (rawData.headers as Record<string, string>) || {},
    command,
    args: Array.isArray(rawData.args) ? (rawData.args as string[]) : [],
    env: (rawData.env as Record<string, string>) || {},
    cwd: (rawData.cwd || "") as string,
  };
}

// ---------------------------------------------------------------------------
// Form-mode state defaults
// ---------------------------------------------------------------------------

const defaultForm = {
  key: "",
  name: "",
  description: "",
  transport: "streamable_http" as MCPTransport,
  url: "",
  command: "",
  args: "",
  env: "",
  cwd: "",
};

function MCPPage() {
  const { t } = useTranslation();
  const {
    clients,
    providerServers,
    loading,
    toggleEnabled,
    deleteClient,
    createClient,
    updateClient,
    updatePolicy,
    refreshClients,
  } = useMCP();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const visibleClients = clients.filter(
    (client) =>
      (filter === "all" || client.enabled === (filter === "enabled")) &&
      `${client.name} ${client.description ?? ""} ${client.key}`
        .toLocaleLowerCase()
        .includes(query.toLocaleLowerCase().trim()),
  );
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<"json" | "form">("form");
  const [createError, setCreateError] = useState<string | null>(null);

  // JSON-import state
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

  // Form state
  const [form, setForm] = useState({ ...defaultForm });

  const setField = useCallback(
    <K extends keyof typeof defaultForm>(k: K, v: (typeof defaultForm)[K]) => {
      setForm((prev) => ({ ...prev, [k]: v }));
    },
    [],
  );

  const resetModal = useCallback(() => {
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
    setForm({ ...defaultForm });
    setActiveTab("form");
    setCreateError(null);
  }, []);

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

  // ---------- JSON import ----------
  const handleCreateFromJson = async () => {
    setCreateError(null);
    try {
      const parsed = JSON.parse(newClientJson) as Record<string, unknown>;
      const clientsToCreate: Array<{
        key: string;
        data: ReturnType<typeof normalizeClientData>;
      }> = [];

      if (parsed.mcpServers) {
        Object.entries(parsed.mcpServers as Record<string, unknown>).forEach(
          ([key, data]) => {
            clientsToCreate.push({
              key,
              data: normalizeClientData(key, data as Record<string, unknown>),
            });
          },
        );
      } else if (
        parsed.key &&
        (parsed.command || parsed.url || parsed.baseUrl)
      ) {
        const { key, ...clientData } = parsed as Record<string, unknown>;
        clientsToCreate.push({
          key: key as string,
          data: normalizeClientData(key as string, clientData),
        });
      } else {
        Object.entries(parsed).forEach(([key, data]) => {
          if (
            typeof data === "object" &&
            data !== null &&
            ((data as Record<string, unknown>).command ||
              (data as Record<string, unknown>).url ||
              (data as Record<string, unknown>).baseUrl)
          ) {
            clientsToCreate.push({
              key,
              data: normalizeClientData(key, data as Record<string, unknown>),
            });
          }
        });
      }

      if (clientsToCreate.length === 0) {
        setCreateError(t("mcp.invalidJson"));
        return;
      }
      let allSuccess = true;
      for (const { key, data } of clientsToCreate) {
        const success = await createClient(key, data);
        if (!success) allSuccess = false;
      }

      if (allSuccess) {
        setCreateModalOpen(false);
        resetModal();
      }
    } catch {
      setCreateError(t("mcp.invalidJson"));
    }
  };

  // ---------- Form create ----------
  const handleCreateFromForm = async () => {
    setCreateError(null);
    const key = form.key.trim();
    const name = form.name.trim();
    if (!key) {
      setCreateError(t("mcp.form.keyRequired"));
      return;
    }
    if (!name) {
      setCreateError(t("mcp.form.nameRequired"));
      return;
    }

    const isHttp =
      form.transport === "streamable_http" || form.transport === "sse";

    if (isHttp && !form.url.trim()) {
      setCreateError(t("mcp.form.urlRequired"));
      return;
    }
    if (form.transport === "stdio" && !form.command.trim()) {
      setCreateError(t("mcp.form.commandRequired"));
      return;
    }

    // Parse args: split on newlines, commas, or spaces
    const args = form.args
      .split(/[\n, ]+/)
      .map((s) => s.trim())
      .filter(Boolean);

    // Parse env (KEY=VALUE lines)
    const env: Record<string, string> = {};
    form.env
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean)
      .forEach((line) => {
        const idx = line.indexOf("=");
        if (idx > 0) {
          env[line.slice(0, idx).trim()] = line.slice(idx + 1).trim();
        }
      });

    const clientData = {
      name,
      description: form.description,
      transport: form.transport,
      url: isHttp ? form.url.trim() : "",
      command: form.transport === "stdio" ? form.command.trim() : "",
      args,
      env,
      cwd: form.cwd.trim(),
    };

    const success = await createClient(key, clientData);
    if (success) {
      setCreateModalOpen(false);
      resetModal();
    }
  };

  const isHttpTransport =
    form.transport === "streamable_http" || form.transport === "sse";

  return (
    <div className={styles.mcpPage}>
      <PageHeader
        items={[{ title: t("nav.agent") }, { title: t("mcp.title") }]}
        extra={
          <Button
            type="primary"
            icon={<Plus size={14} />}
            onClick={() => setCreateModalOpen(true)}
          >
            {t("mcp.create")}
          </Button>
        }
      />

      <div className={styles.collectionToolbar}>
        <Input
          aria-label={t("common.search")}
          placeholder={t("common.search")}
          prefix={<Search size={16} />}
          value={query}
          allowClear
          onChange={(event) => setQuery(event.target.value)}
        />
        <Segmented
          value={filter}
          onChange={(value) => setFilter(String(value))}
          options={[
            { value: "all", label: t("common.all") },
            { value: "enabled", label: t("common.enabled") },
            { value: "disabled", label: t("common.disabled") },
          ]}
        />
      </div>
      {loading ? (
        <div className={styles.loading}>
          <p>{t("common.loading")}</p>
        </div>
      ) : clients.length === 0 && providerServers.length === 0 ? (
        <div className={styles.emptyState}>
          <Empty description={t("mcp.emptyState")} />
        </div>
      ) : (
        <div className={styles.mcpSections}>
          <section className={styles.mcpSection}>
            <div className={styles.sectionHeader}>
              <div className={styles.sectionIcon}>
                <Server size={17} />
              </div>
              <div>
                <h2>{t("mcp.qwenpawManaged")}</h2>
                <InlineHelp>{t("mcp.qwenpawManagedHint")}</InlineHelp>
              </div>
            </div>
            {visibleClients.length === 0 ? (
              <div className={styles.sectionEmpty}>{t("mcp.emptyState")}</div>
            ) : (
              <div className={styles.mcpGrid}>
                {visibleClients.map((client, index) => (
                  <Cascade key={client.key} index={index}>
                    <MCPClientCard
                      client={client}
                      onToggle={handleToggleEnabled}
                      onDelete={handleDelete}
                      onUpdate={updateClient}
                      onUpdatePolicy={updatePolicy}
                      onRefresh={refreshClients}
                    />
                  </Cascade>
                ))}
              </div>
            )}
          </section>

          {providerServers.length > 0 && (
            <section className={styles.mcpSection}>
              <div className={styles.sectionHeader}>
                <div className={styles.sectionIcon}>
                  <LockKeyhole size={17} />
                </div>
                <div>
                  <h2>
                    {t("mcp.providerManaged", {
                      provider: providerServers[0].provider_id,
                    })}
                  </h2>
                  <InlineHelp>{t("mcp.providerManagedHint")}</InlineHelp>
                </div>
              </div>
              <div className={styles.providerGrid}>
                {providerServers.map((server) => (
                  <article
                    className={styles.providerCard}
                    key={`${server.provider_id}:${server.name}`}
                  >
                    <div className={styles.providerCardHeader}>
                      <strong>{server.name}</strong>
                      <span
                        className={
                          server.enabled
                            ? styles.providerEnabled
                            : styles.providerDisabled
                        }
                      >
                        {server.enabled
                          ? t("common.enabled")
                          : t("common.disabled")}
                      </span>
                    </div>
                    <div className={styles.providerMeta}>
                      <span>{server.transport}</span>
                      <span>{t("mcp.providerOnly")}</span>
                      <span>{t("mcp.readOnly")}</span>
                    </div>
                  </article>
                ))}
              </div>
            </section>
          )}
        </div>
      )}

      <Modal
        centered
        title={t("mcp.create")}
        open={createModalOpen}
        onCancel={() => {
          setCreateModalOpen(false);
          resetModal();
        }}
        footer={
          <div className={styles.modalFooter}>
            <Button
              onClick={() => {
                setCreateModalOpen(false);
                resetModal();
              }}
              style={{ marginRight: 8 }}
            >
              {t("common.cancel")}
            </Button>
            <Button
              type="primary"
              onClick={
                activeTab === "json"
                  ? handleCreateFromJson
                  : handleCreateFromForm
              }
            >
              {t("common.create")}
            </Button>
          </div>
        }
        width={800}
      >
        {createError && (
          <Alert
            type="error"
            showIcon
            message={createError}
            style={{ marginBottom: 16 }}
          />
        )}
        <Tabs
          activeKey={activeTab}
          onChange={(k) => setActiveTab(k as "json" | "form")}
          items={[
            {
              key: "json",
              label: t("mcp.tab.json"),
              children: (
                <div>
                  <div className={styles.importHint}>
                    <p className={styles.importHintTitle}>
                      {t("mcp.formatSupport")}:
                    </p>
                    <ul className={styles.importHintList}>
                      <li>
                        {t("mcp.standardFormat")}:{" "}
                        <code>{`{ "mcpServers": { "key": {...} } }`}</code>
                      </li>
                      <li>
                        {t("mcp.directFormat")}:{" "}
                        <code>{`{ "key": {...} }`}</code>
                      </li>
                      <li>
                        {t("mcp.singleFormat")}:{" "}
                        <code>{`{ "key": "...", "name": "...", "command": "..." }`}</code>
                      </li>
                    </ul>
                  </div>
                  <Input.TextArea
                    value={newClientJson}
                    onChange={(e) => setNewClientJson(e.target.value)}
                    autoSize={{ minRows: 15, maxRows: 25 }}
                    className={styles.jsonTextArea}
                  />
                </div>
              ),
            },
            {
              key: "form",
              label: t("mcp.tab.form"),
              children: (
                <div
                  style={{ display: "flex", flexDirection: "column", gap: 10 }}
                >
                  {/* Key + Name */}
                  <div style={rowStyle}>
                    <div style={fieldStyle}>
                      <label style={labelStyle}>
                        {t("mcp.form.key")}
                        <span style={{ color: "#c0392b" }}> *</span>
                      </label>
                      <Input
                        placeholder={t("mcp.form.keyPlaceholder")}
                        value={form.key}
                        onChange={(e) => setField("key", e.target.value)}
                      />
                    </div>
                    <div style={fieldStyle}>
                      <label style={labelStyle}>
                        {t("mcp.form.name")}
                        <span style={{ color: "#c0392b" }}> *</span>
                      </label>
                      <Input
                        placeholder={t("mcp.form.namePlaceholder")}
                        value={form.name}
                        onChange={(e) => setField("name", e.target.value)}
                      />
                    </div>
                  </div>

                  {/* Transport */}
                  <div>
                    <label style={labelStyle}>{t("mcp.form.transport")}</label>
                    <Select
                      value={form.transport}
                      onChange={(v) => setField("transport", v as MCPTransport)}
                      style={{ width: "100%" }}
                      options={[
                        {
                          label: "Streamable HTTP",
                          value: "streamable_http",
                        },
                        { label: "SSE", value: "sse" },
                        { label: "Stdio", value: "stdio" },
                      ]}
                    />
                  </div>

                  {/* URL (HTTP/SSE) or Command (stdio) */}
                  {isHttpTransport ? (
                    <div>
                      <label style={labelStyle}>
                        {t("mcp.form.url")}
                        <span style={{ color: "#c0392b" }}> *</span>
                      </label>
                      <Input
                        placeholder="https://mcp.example.com/mcp"
                        value={form.url}
                        onChange={(e) => setField("url", e.target.value)}
                      />
                    </div>
                  ) : (
                    <>
                      <div>
                        <label style={labelStyle}>
                          {t("mcp.form.command")}
                          <span style={{ color: "#c0392b" }}> *</span>
                        </label>
                        <Input
                          placeholder="npx"
                          value={form.command}
                          onChange={(e) => setField("command", e.target.value)}
                        />
                      </div>
                      <div>
                        <label style={labelStyle}>{t("mcp.form.args")}</label>
                        <Input
                          placeholder="-y @example/mcp-server"
                          value={form.args}
                          onChange={(e) => setField("args", e.target.value)}
                        />
                      </div>
                    </>
                  )}

                  {/* Description */}
                  <div>
                    <label style={labelStyle}>
                      {t("mcp.form.description")}
                    </label>
                    <Input
                      placeholder={t("mcp.form.descriptionPlaceholder")}
                      value={form.description}
                      onChange={(e) => setField("description", e.target.value)}
                    />
                  </div>

                  {/* Env (only for stdio) */}
                  {form.transport === "stdio" && (
                    <div>
                      <label style={labelStyle}>{t("mcp.form.env")}</label>
                      <Input.TextArea
                        placeholder={t("mcp.form.envPlaceholder")}
                        value={form.env}
                        onChange={(e) => setField("env", e.target.value)}
                        autoSize={{ minRows: 2, maxRows: 5 }}
                      />
                    </div>
                  )}
                </div>
              ),
            },
          ]}
        />
      </Modal>
    </div>
  );
}

const rowStyle: React.CSSProperties = {
  display: "flex",
  gap: 12,
};

const fieldStyle: React.CSSProperties = {
  flex: 1,
  display: "flex",
  flexDirection: "column",
  gap: 4,
};

const labelStyle: React.CSSProperties = {
  fontSize: 12,
  color: "#555",
  fontWeight: 500,
};

export default MCPPage;

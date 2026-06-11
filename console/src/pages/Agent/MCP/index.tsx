import { useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Plus } from "lucide-react";
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
    loading,
    toggleEnabled,
    deleteClient,
    createClient,
    updateClient,
    refreshClients,
  } = useMCP();
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<"json" | "form">("json");

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
    setActiveTab("json");
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

  const handleCreateFromJson = async () => {
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
      alert("Invalid JSON format");
    }
  };

  const handleCreateFromForm = async () => {
    const key = form.key.trim();
    const name = form.name.trim();
    if (!key) {
      alert(t("mcp.form.keyRequired"));
      return;
    }
    if (!name) {
      alert(t("mcp.form.nameRequired"));
      return;
    }

    const isHttp =
      form.transport === "streamable_http" || form.transport === "sse";

    if (isHttp && !form.url.trim()) {
      alert(t("mcp.form.urlRequired"));
      return;
    }
    if (form.transport === "stdio" && !form.command.trim()) {
      alert(t("mcp.form.commandRequired"));
      return;
    }

    const args = form.args
      .split(/[\n, ]+/)
      .map((s) => s.trim())
      .filter(Boolean);

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
          <Button onClick={() => setCreateModalOpen(true)}>
            <Plus size={14} className="mr-1" />
            {t("mcp.create")}
          </Button>
        }
      />

      {loading ? (
        <div className={styles.loading}>
          <p>{t("common.loading")}</p>
        </div>
      ) : clients.length === 0 ? (
        <div className={styles.emptyState}>
          <p className="text-sm text-muted-foreground">{t("mcp.emptyState")}</p>
        </div>
      ) : (
        <div className={styles.mcpGrid}>
          {clients.map((client) => (
            <MCPClientCard
              key={client.key}
              client={client}
              onToggle={handleToggleEnabled}
              onDelete={handleDelete}
              onUpdate={updateClient}
              onRefresh={refreshClients}
            />
          ))}
        </div>
      )}

      <Dialog
        open={createModalOpen}
        onOpenChange={(open) => {
          if (!open) {
            setCreateModalOpen(false);
            resetModal();
          }
        }}
      >
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>{t("mcp.create")}</DialogTitle>
          </DialogHeader>

          <Tabs
            value={activeTab}
            onValueChange={(k) => setActiveTab(k as "json" | "form")}
          >
            <TabsList>
              <TabsTrigger value="json">{t("mcp.tab.json")}</TabsTrigger>
              <TabsTrigger value="form">{t("mcp.tab.form")}</TabsTrigger>
            </TabsList>
            <TabsContent value="json">
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
                      {t("mcp.directFormat")}: <code>{`{ "key": {...} }`}</code>
                    </li>
                    <li>
                      {t("mcp.singleFormat")}:{" "}
                      <code>{`{ "key": "...", "name": "...", "command": "..." }`}</code>
                    </li>
                  </ul>
                </div>
                <Textarea
                  value={newClientJson}
                  onChange={(e) => setNewClientJson(e.target.value)}
                  rows={15}
                  className={styles.jsonTextArea}
                />
              </div>
            </TabsContent>
            <TabsContent value="form">
              <div className="flex flex-col gap-3">
                <div className="flex gap-3">
                  <div className="flex-1 flex flex-col gap-1">
                    <label className="text-xs font-medium text-muted-foreground">
                      {t("mcp.form.key")}
                      <span className="text-destructive"> *</span>
                    </label>
                    <Input
                      placeholder={t("mcp.form.keyPlaceholder")}
                      value={form.key}
                      onChange={(e) => setField("key", e.target.value)}
                    />
                  </div>
                  <div className="flex-1 flex flex-col gap-1">
                    <label className="text-xs font-medium text-muted-foreground">
                      {t("mcp.form.name")}
                      <span className="text-destructive"> *</span>
                    </label>
                    <Input
                      placeholder={t("mcp.form.namePlaceholder")}
                      value={form.name}
                      onChange={(e) => setField("name", e.target.value)}
                    />
                  </div>
                </div>

                <div className="flex flex-col gap-1">
                  <label className="text-xs font-medium text-muted-foreground">
                    {t("mcp.form.transport")}
                  </label>
                  <Select
                    value={form.transport}
                    onValueChange={(v) =>
                      setField("transport", v as MCPTransport)
                    }
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="streamable_http">
                        Streamable HTTP
                      </SelectItem>
                      <SelectItem value="sse">SSE</SelectItem>
                      <SelectItem value="stdio">Stdio</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                {isHttpTransport ? (
                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-muted-foreground">
                      {t("mcp.form.url")}
                      <span className="text-destructive"> *</span>
                    </label>
                    <Input
                      placeholder="https://mcp.example.com/mcp"
                      value={form.url}
                      onChange={(e) => setField("url", e.target.value)}
                    />
                  </div>
                ) : (
                  <>
                    <div className="flex flex-col gap-1">
                      <label className="text-xs font-medium text-muted-foreground">
                        {t("mcp.form.command")}
                        <span className="text-destructive"> *</span>
                      </label>
                      <Input
                        placeholder="npx"
                        value={form.command}
                        onChange={(e) => setField("command", e.target.value)}
                      />
                    </div>
                    <div className="flex flex-col gap-1">
                      <label className="text-xs font-medium text-muted-foreground">
                        {t("mcp.form.args")}
                      </label>
                      <Input
                        placeholder="-y @example/mcp-server"
                        value={form.args}
                        onChange={(e) => setField("args", e.target.value)}
                      />
                    </div>
                  </>
                )}

                <div className="flex flex-col gap-1">
                  <label className="text-xs font-medium text-muted-foreground">
                    {t("mcp.form.description")}
                  </label>
                  <Input
                    placeholder={t("mcp.form.descriptionPlaceholder")}
                    value={form.description}
                    onChange={(e) => setField("description", e.target.value)}
                  />
                </div>

                {form.transport === "stdio" && (
                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-muted-foreground">
                      {t("mcp.form.env")}
                    </label>
                    <Textarea
                      placeholder={t("mcp.form.envPlaceholder")}
                      value={form.env}
                      onChange={(e) => setField("env", e.target.value)}
                      rows={3}
                    />
                  </div>
                )}
              </div>
            </TabsContent>
          </Tabs>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setCreateModalOpen(false);
                resetModal();
              }}
            >
              {t("common.cancel")}
            </Button>
            <Button
              onClick={
                activeTab === "json"
                  ? handleCreateFromJson
                  : handleCreateFromForm
              }
            >
              {t("common.create")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default MCPPage;

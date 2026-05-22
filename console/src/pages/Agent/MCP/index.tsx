import { useState, useCallback } from "react";
import { Button, Empty } from "@agentscope-ai/design";
import { Plus } from "lucide-react";
import type { MCPClientInfo } from "../../../api/types";
import {
  MCPClientCard,
  MCPMarketIcon,
  MCPMarketplaceModal,
  MCPCreateModal,
} from "./components";
import { normalizeClientData } from "./utils/mcpClientUtils";
import { defaultMcpForm } from "./utils/mcpClientUtils";
import type { MCPClientCreatePayload } from "./market/installTemplate";
import { useMCP } from "./useMCP";
import { getMcpClientKeyErrorMessage } from "./utils/mcpClientKey";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { PageHeader } from "@/components/PageHeader";
import styles from "./index.module.less";

function MCPPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const {
    clients,
    loading,
    toggleEnabled,
    deleteClient,
    createClient,
    updateClient,
    refreshClients,
    refreshConnection,
  } = useMCP();
  const [marketModalOpen, setMarketModalOpen] = useState(false);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [marketInstalling, setMarketInstalling] = useState(false);

  const existingKeys = clients.map((c) => c.key);

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

  const handleCreateFromJson = useCallback(
    async (newClientJson: string) => {
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

        for (const { key } of clientsToCreate) {
          const keyError = getMcpClientKeyErrorMessage(key, t);
          if (keyError) {
            message.error(keyError);
            return false;
          }
        }

        let allSuccess = true;
        for (const { key, data } of clientsToCreate) {
          const success = await createClient(key, data);
          if (!success) allSuccess = false;
        }
        return allSuccess;
      } catch {
        alert(t("mcp.advanced.invalidJson"));
        return false;
      }
    },
    [createClient, t, message],
  );

  const handleCreateFromForm = useCallback(
    async (form: typeof defaultMcpForm) => {
      const key = form.key.trim();
      const name = form.name.trim();
      const keyError = getMcpClientKeyErrorMessage(key, t);
      if (keyError) {
        message.error(keyError);
        return false;
      }
      if (!key) {
        alert(t("mcp.form.keyRequired"));
        return false;
      }
      if (!name) {
        alert(t("mcp.form.nameRequired"));
        return false;
      }

      const isHttp =
        form.transport === "streamable_http" || form.transport === "sse";

      if (isHttp && !form.url.trim()) {
        alert(t("mcp.form.urlRequired"));
        return false;
      }
      if (form.transport === "stdio" && !form.command.trim()) {
        alert(t("mcp.form.commandRequired"));
        return false;
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

      return createClient(key, clientData);
    },
    [createClient, t, message],
  );

  const handleMarketInstall = useCallback(
    async (clientKey: string, payload: MCPClientCreatePayload) => {
      setMarketInstalling(true);
      try {
        const ok = await createClient(clientKey, payload);
        if (ok) setMarketModalOpen(false);
        return ok;
      } finally {
        setMarketInstalling(false);
      }
    },
    [createClient],
  );

  return (
    <div className={styles.mcpPage}>
      <PageHeader
        items={[{ title: t("nav.agent") }, { title: t("mcp.title") }]}
        extra={
          <div className={styles.headerActions}>
            <Button
              icon={<MCPMarketIcon size={14} />}
              onClick={() => setMarketModalOpen(true)}
            >
              {t("mcp.market.open")}
            </Button>
            <Button
              type="primary"
              icon={<Plus size={14} />}
              onClick={() => setCreateModalOpen(true)}
            >
              {t("mcp.create")}
            </Button>
          </div>
        }
      />

      <div className={styles.mcpContainer}>
        {loading ? (
          <div className={styles.loading}>
            <span className={styles.loadingText}>{t("common.loading")}</span>
          </div>
        ) : clients.length === 0 ? (
          <div className={styles.emptyState}>
            <Empty description={t("mcp.emptyState")} />
            <div className={styles.emptyActions}>
              <Button
                type="primary"
                icon={<MCPMarketIcon size={14} />}
                onClick={() => setMarketModalOpen(true)}
              >
                {t("mcp.market.browse")}
              </Button>
              <Button
                icon={<Plus size={14} />}
                onClick={() => setCreateModalOpen(true)}
              >
                {t("mcp.custom.add")}
              </Button>
            </div>
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
                onRefreshConnection={refreshConnection}
              />
            ))}
          </div>
        )}
      </div>

      <MCPMarketplaceModal
        open={marketModalOpen}
        existingKeys={existingKeys}
        installing={marketInstalling}
        onCancel={() => setMarketModalOpen(false)}
        onInstall={handleMarketInstall}
      />

      <MCPCreateModal
        open={createModalOpen}
        onClose={() => setCreateModalOpen(false)}
        onCreateFromJson={handleCreateFromJson}
        onCreateFromForm={handleCreateFromForm}
      />
    </div>
  );
}

export default MCPPage;

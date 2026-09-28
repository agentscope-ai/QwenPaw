import { MCPConnectionEditor } from "./MCPConnectionEditor";
import { readConnection, connectionError } from "./connectionValue";
import { useAutoSave } from "@/hooks/useAutoSave";
import { ServiceCard } from "@/components/interaction/ServiceCard";
import { SharedModal as Modal } from "@/components/interaction/SharedModal";
import { Button, Tooltip } from "@agentscope-ai/design";
import type { MCPAccessPolicy, MCPClientInfo } from "../../../../api/types";
import { useTranslation } from "react-i18next";
import React, { useId, useState } from "react";
import { Trash2, Wrench as ToolOutlined } from "lucide-react";
import { ShieldCheck, ShieldAlert, ShieldX, KeyRound } from "lucide-react";
import { MCPAccessModal } from "./MCPAccessModal";
import { MCPOAuthSection } from "./MCPOAuthSection";

interface MCPClientUpdate {
  name?: string;
  description?: string;
  command?: string;
  enabled?: boolean;
  transport?: "stdio" | "streamable_http" | "sse";
  url?: string;
  headers?: Record<string, string>;
  args?: string[];
  env?: Record<string, string>;
  cwd?: string;
  http_timeout?: number;
}

interface MCPClientCardProps {
  client: MCPClientInfo;
  onToggle: (client: MCPClientInfo) => Promise<void> | void;
  onDelete: (client: MCPClientInfo, e: React.MouseEvent) => void;
  onUpdate: (key: string, updates: MCPClientUpdate) => Promise<boolean>;
  onUpdatePolicy: (key: string, policy: MCPAccessPolicy) => Promise<boolean>;
  onRefresh?: () => Promise<void>;
}

export const MCPClientCard = React.memo(function MCPClientCard({
  client,
  onToggle,
  onDelete,
  onUpdate,
  onUpdatePolicy,
  onRefresh,
}: MCPClientCardProps) {
  const { t } = useTranslation();
  const surfaceId = useId();
  const [jsonModalOpen, setJsonModalOpen] = useState(false);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [accessModalOpen, setAccessModalOpen] = useState(false);
  const [editedJson, setEditedJson] = useState("");
  const [oauthModalOpen, setOauthModalOpen] = useState(false);
  const [oauthClientId, setOauthClientId] = useState("");
  const [oauthScope, setOauthScope] = useState(
    client.oauth_status?.scope || "",
  );
  const [oauthAuthEndpoint, setOauthAuthEndpoint] = useState("");
  const [oauthTokenEndpoint, setOauthTokenEndpoint] = useState("");

  // Determine if MCP client is remote or local based on command
  const isRemote =
    client.transport === "streamable_http" || client.transport === "sse";
  const clientType = t(isRemote ? "mcp.remote" : "mcp.local");

  const oauthStatus = client.oauth_status;
  const now = Date.now() / 1000;
  const isOauthAuthorized =
    !!oauthStatus?.authorized && oauthStatus.expires_at > now;
  const isOauthExpired =
    !!oauthStatus?.authorized && oauthStatus.expires_at <= now;

  const confirmDelete = () => {
    setDeleteModalOpen(false);
    onDelete(client, null as unknown as React.MouseEvent);
  };

  const handleCardClick = () => {
    const jsonStr = JSON.stringify(client, null, 2);
    setEditedJson(jsonStr);
    setJsonModalOpen(true);
  };

  const { schedule: scheduleJson, flush: flushJson } = useAutoSave(async () => {
    const parsed = readConnection(editedJson);
    if (!parsed || connectionError(parsed)) return false;
    const updates = { ...parsed };
    delete updates.key;
    return onUpdate(client.key, updates);
  });

  return (
    <>
      <ServiceCard
        surfaceId={surfaceId}
        name={client.name}
        description={client.description}
        enabled={client.enabled}
        onConfigure={handleCardClick}
        onToggle={() => onToggle(client)}
        metadata={
          <>
            <span>{clientType}</span>
            <span>{client.transport}</span>
          </>
        }
        actions={
          <>
            <Tooltip title={t("mcp.tools")}>
              <Button
                type="text"
                aria-label={t("mcp.tools")}
                icon={<ToolOutlined size={16} />}
                onClick={() => setAccessModalOpen(true)}
              />
            </Tooltip>
            {isRemote && (
              <Tooltip title={t("mcp.oauth.manage")}>
                <Button
                  type="text"
                  aria-label={t("mcp.oauth.manage")}
                  onClick={() => setOauthModalOpen(true)}
                  icon={
                    isOauthAuthorized ? (
                      <ShieldCheck size={16} />
                    ) : isOauthExpired ? (
                      <ShieldAlert size={16} />
                    ) : (
                      <KeyRound size={16} />
                    )
                  }
                />
              </Tooltip>
            )}
            <Tooltip title={t("common.delete")}>
              <Button
                type="text"
                danger
                aria-label={t("common.delete")}
                icon={<Trash2 size={16} />}
                onClick={() => setDeleteModalOpen(true)}
              />
            </Tooltip>
          </>
        }
      />

      <Modal
        title={t("common.confirm")}
        open={deleteModalOpen}
        onOk={confirmDelete}
        onCancel={() => setDeleteModalOpen(false)}
        okText={t("common.confirm")}
        cancelText={t("common.close")}
        okButtonProps={{ danger: true }}
      >
        <p>{t("mcp.deleteConfirm")}</p>
      </Modal>

      <Modal
        surfaceId={surfaceId}
        styles={{
          body: {
            maxHeight: "min(68dvh, 640px)",
            overflowY: "auto",
            padding: "2px",
          },
        }}
        title={`${client.name} · ${t("common.configure")}`}
        open={jsonModalOpen}
        onCancel={() => {
          void flushJson().then((saved) => {
            if (saved) setJsonModalOpen(false);
          });
        }}
        footer={
          <div style={{ textAlign: "right" }}>
            <Button
              onClick={() => {
                void flushJson().then((saved) => {
                  if (saved) setJsonModalOpen(false);
                });
              }}
              style={{ marginRight: 8 }}
            >
              {t("common.close")}
            </Button>
          </div>
        }
        width={700}
      >
        <MCPConnectionEditor
          value={editedJson}
          onChange={(next) => {
            setEditedJson(next);
            scheduleJson();
          }}
        />
      </Modal>

      <MCPAccessModal
        client={client}
        open={accessModalOpen}
        onClose={() => setAccessModalOpen(false)}
        onSave={(policy) => onUpdatePolicy(client.key, policy)}
      />

      {/* Dedicated OAuth modal — opened only via the Authorize button */}
      <Modal
        title={
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {isOauthAuthorized ? (
              <ShieldCheck
                size={16}
                style={{ color: "var(--app-success-text)" }}
              />
            ) : isOauthExpired ? (
              <ShieldAlert
                size={16}
                style={{ color: "var(--app-warning-text)" }}
              />
            ) : (
              <ShieldX
                size={16}
                style={{ color: "var(--app-text-tertiary)" }}
              />
            )}
            {`${client.name} — ${t("mcp.oauth.manage")}`}
          </div>
        }
        open={oauthModalOpen}
        onCancel={() => setOauthModalOpen(false)}
        footer={
          <div style={{ textAlign: "right" }}>
            <Button onClick={() => setOauthModalOpen(false)}>
              {t("common.close")}
            </Button>
          </div>
        }
        width={560}
      >
        <MCPOAuthSection
          url={client.url}
          clientKey={client.key}
          oauthEnabled
          currentOAuthStatus={oauthStatus}
          clientId={oauthClientId}
          scope={oauthScope}
          authEndpoint={oauthAuthEndpoint}
          tokenEndpoint={oauthTokenEndpoint}
          onClientIdChange={setOauthClientId}
          onScopeChange={setOauthScope}
          onAuthEndpointChange={setOauthAuthEndpoint}
          onTokenEndpointChange={setOauthTokenEndpoint}
          onAuthChanged={() => {
            onRefresh?.();
          }}
        />
      </Modal>
    </>
  );
});

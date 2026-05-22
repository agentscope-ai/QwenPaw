import {
  Card,
  Button,
  Modal,
  Tooltip,
  Input,
  Empty,
  Tag,
} from "@agentscope-ai/design";
import { Spin } from "antd";
import type { MCPClientInfo, MCPToolInfo } from "../../../../api/types";
import { useTranslation } from "react-i18next";
import React, { useState, useCallback, useMemo } from "react";
import {
  hasStaticBearerAuth,
  parseMarketClientMeta,
  resolveClientDisplayDescription,
  resolveClientDisplayName,
  resolveMarketTemplate,
} from "../market/clientMeta";
import {
  MCPTemplateIcon,
  MCPCustomClientIcon,
  type MCPMarketIconId,
} from "../market/templateIcons";
import marketStyles from "./MCPMarketplaceModal.module.less";
import { useTheme } from "../../../../contexts/ThemeContext";
import {
  EyeOutlined,
  EyeInvisibleOutlined,
  ToolOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import { ShieldCheck, ShieldAlert, ShieldX, KeyRound, Link2 } from "lucide-react";
import api from "../../../../api";
import { MCPOAuthSection } from "./MCPOAuthSection";
import { MCPInstallWizard } from "./MCPInstallWizard";
import type { MCPClientUpdatePayload } from "../market/installTemplate";
import styles from "../index.module.less";

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
}

interface MCPClientCardProps {
  client: MCPClientInfo;
  onToggle: (client: MCPClientInfo, e: React.MouseEvent) => void;
  onDelete: (client: MCPClientInfo, e: React.MouseEvent) => void;
  onUpdate: (key: string, updates: MCPClientUpdate) => Promise<boolean>;
  onRefresh?: () => Promise<void>;
  onRefreshConnection?: (client: MCPClientInfo) => Promise<unknown>;
}

export const MCPClientCard = React.memo(function MCPClientCard({
  client,
  onToggle,
  onDelete,
  onUpdate,
  onRefresh,
  onRefreshConnection,
}: MCPClientCardProps) {
  const { t } = useTranslation();
  const { isDark } = useTheme();
  const [isHovered, setIsHovered] = useState(false);
  const [jsonModalOpen, setJsonModalOpen] = useState(false);
  const [marketEditOpen, setMarketEditOpen] = useState(false);
  const [marketSaving, setMarketSaving] = useState(false);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [toolsModalOpen, setToolsModalOpen] = useState(false);
  const [tools, setTools] = useState<MCPToolInfo[]>([]);
  const [toolsLoading, setToolsLoading] = useState(false);
  const [toolsError, setToolsError] = useState<string | null>(null);
  const [editedJson, setEditedJson] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [oauthModalOpen, setOauthModalOpen] = useState(false);
  const [oauthClientId, setOauthClientId] = useState("");
  const [oauthScope, setOauthScope] = useState(
    client.oauth_status?.scope || "",
  );
  const [oauthAuthEndpoint, setOauthAuthEndpoint] = useState("");
  const [oauthTokenEndpoint, setOauthTokenEndpoint] = useState("");
  const [connectionRefreshing, setConnectionRefreshing] = useState(false);

  const marketMeta = useMemo(
    () => parseMarketClientMeta(client),
    [client.key, client.description],
  );

  const displayName = useMemo(
    () => resolveClientDisplayName(client, marketMeta, t),
    [client, marketMeta, t],
  );

  const displayDescription = useMemo(
    () => resolveClientDisplayDescription(client, marketMeta, t),
    [client, marketMeta, t],
  );

  const marketTemplate = useMemo(
    () => resolveMarketTemplate(client),
    [client],
  );

  const isRemote =
    client.transport === "streamable_http" || client.transport === "sse";

  const showOauthButton = isRemote && !hasStaticBearerAuth(client);

  const transportLabel =
    client.transport === "stdio"
      ? marketTemplate?.command === "uvx"
        ? "uvx"
        : "Stdio"
      : "HTTP";

  const oauthStatus = client.oauth_status;
  const now = Date.now() / 1000;
  const isOauthAuthorized =
    !!oauthStatus?.authorized && oauthStatus.expires_at > now;
  const isOauthExpired =
    !!oauthStatus?.authorized && oauthStatus.expires_at <= now;
  const hasOauth = !!oauthStatus;

  const connectionStatus = client.connection_status ?? "unavailable";

  const connectivityIconColor = useMemo(() => {
    const colors: Record<
      NonNullable<MCPClientInfo["connection_status"]>,
      string
    > = {
      disabled: "#bfbfbf",
      connecting: "#faad14",
      available: "#52c41a",
      unavailable: "#ff4d4f",
    };
    return colors[connectionStatus] ?? "#ff4d4f";
  }, [connectionStatus]);

  const connectivityTooltip = useMemo(() => {
    if (client.connection_message) {
      return client.connection_message;
    }
    const labels: Record<
      NonNullable<MCPClientInfo["connection_status"]>,
      string
    > = {
      disabled: t("mcp.connectivity.disabled"),
      connecting: t("mcp.connectivity.connecting"),
      available: t("mcp.connectivity.available"),
      unavailable: t("mcp.connectivity.unavailable"),
    };
    return labels[connectionStatus] ?? t("mcp.connectivity.unavailable");
  }, [client.connection_message, connectionStatus, t]);

  const handleToggleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onToggle(client, e);
  };

  const handleRefreshConnection = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!onRefreshConnection || connectionRefreshing) return;
    setConnectionRefreshing(true);
    try {
      await onRefreshConnection(client);
    } finally {
      setConnectionRefreshing(false);
    }
  };

  const handleDeleteClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    setDeleteModalOpen(true);
  };

  const confirmDelete = () => {
    setDeleteModalOpen(false);
    onDelete(client, null as unknown as React.MouseEvent);
  };

  const handleCardClick = () => {
    if (marketTemplate) {
      setMarketEditOpen(true);
      return;
    }
    const jsonStr = JSON.stringify(client, null, 2);
    setEditedJson(jsonStr);
    setIsEditing(false);
    setJsonModalOpen(true);
  };

  const handleMarketSave = async (updates: MCPClientUpdatePayload) => {
    setMarketSaving(true);
    try {
      const success = await onUpdate(client.key, updates);
      if (success) {
        setMarketEditOpen(false);
      }
      return success;
    } finally {
      setMarketSaving(false);
    }
  };

  const handleSaveJson = async () => {
    try {
      const parsed = JSON.parse(editedJson);
      const { key: _key, ...updates } = parsed;

      // Send all updates directly to backend, let backend handle env masking check
      const success = await onUpdate(client.key, updates);
      if (success) {
        setJsonModalOpen(false);
        setIsEditing(false);
      }
    } catch {
      alert("Invalid JSON format");
    }
  };

  const handleShowTools = useCallback(
    async (e: React.MouseEvent) => {
      e.stopPropagation();
      setToolsModalOpen(true);
      setToolsLoading(true);
      setToolsError(null);
      setTools([]);
      try {
        const data = await api.listMCPTools(client.key);
        setTools(data);
      } catch (err: any) {
        const msg = err?.message || "";
        if (msg.includes("connecting") || msg.includes("not ready")) {
          setToolsError(t("mcp.toolsConnecting"));
        } else {
          setToolsError(msg || t("mcp.toolsLoadError"));
        }
      } finally {
        setToolsLoading(false);
      }
    },
    [client.key, t],
  );

  const clientJson = JSON.stringify(client, null, 2);

  return (
    <>
      <Card
        hoverable
        onClick={handleCardClick}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
        className={`${styles.mcpCard} ${
          client.enabled ? styles.enabledCard : ""
        } ${isHovered ? styles.hover : styles.normal}`}
      >
        <div className={styles.installedCardTop}>
          {marketMeta.templateId && marketTemplate ? (
            <MCPTemplateIcon
              iconId={marketTemplate.iconId as MCPMarketIconId}
            />
          ) : (
            <MCPCustomClientIcon />
          )}
          <div className={styles.installedCardHeadText}>
            <div className={styles.installedCardTitleRow}>
              <Tooltip title={displayName}>
                <h3 className={styles.mcpTitle}>{displayName}</h3>
              </Tooltip>
              {marketMeta.fromMarket && (
                <span className={styles.marketBadge}>
                  {t("mcp.card.fromMarket")}
                </span>
              )}
            </div>
            <Tooltip title={client.key}>
              <span className={styles.clientKeyText}>
                {t("mcp.card.clientKey", { key: client.key })}
              </span>
            </Tooltip>
          </div>
          <div className={styles.installedCardMeta}>
            <span className={marketStyles.templateCardTransport}>
              {transportLabel}
            </span>
            <div className={styles.statusContainer}>
              <span className={styles.statusDot} />
              <span className={styles.statusText}>
                {client.enabled ? t("common.enabled") : t("common.disabled")}
              </span>
            </div>
            <div className={styles.connectivityRow}>
              <Tooltip title={connectivityTooltip}>
                <span className={styles.connectivityIconWrap}>
                  <Link2
                    size={16}
                    strokeWidth={2.25}
                    style={{ color: connectivityIconColor, flexShrink: 0 }}
                  />
                </span>
              </Tooltip>
              {client.enabled && onRefreshConnection &&
                (connectionRefreshing ? (
                  <span
                    className={styles.connectivityRefreshLoading}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <span className={styles.connectivityRefreshSpinner} />
                  </span>
                ) : (
                  <Button
                    type="text"
                    size="small"
                    className={styles.connectivityRefreshBtn}
                    icon={<ReloadOutlined />}
                    onClick={handleRefreshConnection}
                  />
                ))}
            </div>
          </div>
        </div>

        {hasOauth && (
        <div className={styles.cardHeaderOauth}>
          <div className={styles.oauthIconRow}>
            {isOauthExpired && (
              <Tooltip title={t("mcp.oauth.expired")}>
                <ShieldAlert
                  size={13}
                  style={{ color: "#e67e22", flexShrink: 0 }}
                />
              </Tooltip>
            )}
            {isOauthAuthorized && (
              <Tooltip title={t("mcp.oauth.authorized")}>
                <ShieldCheck
                  size={13}
                  style={{ color: "#27ae60", flexShrink: 0 }}
                />
              </Tooltip>
            )}
            {!isOauthAuthorized && !isOauthExpired && (
              <Tooltip title={t("mcp.oauth.notAuthorized")}>
                <ShieldX
                  size={13}
                  style={{ color: "#7f8c8d", flexShrink: 0 }}
                />
              </Tooltip>
            )}
          </div>
        </div>
        )}

        <p className={styles.mcpDescription}>
          {displayDescription || "-"}
        </p>

        <div className={styles.cardFooter}>
          <Button
            className={styles.toolsButton}
            onClick={handleShowTools}
            icon={<ToolOutlined />}
            disabled={!client.enabled || toolsLoading}
            loading={toolsLoading}
          >
            {t("mcp.tools")}
          </Button>
          {showOauthButton && (
            <Button
              className={styles.toggleButton}
              onClick={(e) => {
                e.stopPropagation();
                setOauthModalOpen(true);
              }}
              style={
                isOauthAuthorized
                  ? {
                      color: "#27ae60",
                      borderColor: "#27ae60",
                      background: "rgba(39,174,96,0.06)",
                    }
                  : isOauthExpired
                  ? {
                      color: "#e67e22",
                      borderColor: "#e67e22",
                      background: "rgba(230,126,34,0.06)",
                    }
                  : undefined
              }
            >
              <span
                style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
              >
                {isOauthAuthorized ? (
                  <ShieldCheck size={13} />
                ) : isOauthExpired ? (
                  <ShieldAlert size={13} />
                ) : (
                  <KeyRound size={13} />
                )}
                {isOauthAuthorized
                  ? t("mcp.oauth.authorized")
                  : isOauthExpired
                  ? t("mcp.oauth.expired")
                  : t("mcp.oauth.authorize")}
              </span>
            </Button>
          )}
          <Button
            className={styles.toggleButton}
            onClick={(e) => {
              e.stopPropagation();
              handleToggleClick(e);
            }}
            icon={client.enabled ? <EyeInvisibleOutlined /> : <EyeOutlined />}
          >
            {client.enabled ? t("common.disable") : t("common.enable")}
          </Button>
          <Button
            className={styles.deleteButton}
            danger
            onClick={(e) => {
              e.stopPropagation();
              handleDeleteClick(e);
            }}
          >
            {t("common.delete")}
          </Button>
        </div>
      </Card>

      <Modal
        title={t("common.confirm")}
        open={deleteModalOpen}
        onOk={confirmDelete}
        onCancel={() => setDeleteModalOpen(false)}
        okText={t("common.confirm")}
        cancelText={t("common.cancel")}
        okButtonProps={{ danger: true }}
      >
        <p>{t("mcp.deleteConfirm")}</p>
      </Modal>

      <Modal
        title={`${displayName} - ${t("mcp.tools")}`}
        open={toolsModalOpen}
        onCancel={() => setToolsModalOpen(false)}
        footer={
          <div style={{ textAlign: "right" }}>
            <Button onClick={() => setToolsModalOpen(false)}>
              {t("common.close")}
            </Button>
          </div>
        }
        width={700}
      >
        {toolsLoading ? (
          <div className={styles.toolsLoading}>
            <Spin />
          </div>
        ) : toolsError ? (
          <div className={styles.toolsError}>{toolsError}</div>
        ) : tools.length === 0 ? (
          <Empty description={t("mcp.noTools")} />
        ) : (
          <div className={styles.toolsList}>
            {tools.map((tool) => (
              <div key={tool.name} className={styles.toolItem}>
                <div className={styles.toolHeader}>
                  <Tag color="blue">{tool.name}</Tag>
                </div>
                {tool.description && (
                  <p className={styles.toolDescription}>{tool.description}</p>
                )}
                {tool.input_schema &&
                  Object.keys(tool.input_schema).length > 0 && (
                    <details className={styles.toolSchema}>
                      <summary>{t("mcp.toolSchema")}</summary>
                      <pre className={styles.toolSchemaContent}>
                        {JSON.stringify(tool.input_schema, null, 2)}
                      </pre>
                    </details>
                  )}
              </div>
            ))}
          </div>
        )}
      </Modal>

      <Modal
        title={`${displayName} — ${t("common.edit")}`}
        open={marketEditOpen}
        onCancel={() => !marketSaving && setMarketEditOpen(false)}
        footer={null}
        width={640}
        destroyOnClose
      >
        {marketTemplate && (
          <MCPInstallWizard
            template={marketTemplate}
            existingKeys={[]}
            editClient={client}
            marketUserNote={marketMeta.userNote}
            saving={marketSaving}
            onBack={() => setMarketEditOpen(false)}
            onSave={handleMarketSave}
          />
        )}
      </Modal>

      <Modal
        title={`${displayName} - Configuration`}
        open={jsonModalOpen}
        onCancel={() => setJsonModalOpen(false)}
        footer={
          <div style={{ textAlign: "right" }}>
            <Button
              onClick={() => setJsonModalOpen(false)}
              style={{ marginRight: 8 }}
            >
              {t("common.cancel")}
            </Button>
            {isEditing ? (
              <Button type="primary" onClick={handleSaveJson}>
                {t("common.save")}
              </Button>
            ) : (
              <Button type="primary" onClick={() => setIsEditing(true)}>
                {t("common.edit")}
              </Button>
            )}
          </div>
        }
        width={700}
      >
        <div className={styles.maskedFieldHint}>{t("mcp.maskedFieldHint")}</div>
        {isEditing ? (
          <Input.TextArea
            value={editedJson}
            onChange={(e) => setEditedJson(e.target.value)}
            autoSize={{ minRows: 15, maxRows: 25 }}
            style={{
              fontFamily: "Monaco, Courier New, monospace",
              fontSize: 13,
            }}
          />
        ) : (
          <pre
            style={{
              backgroundColor: isDark ? "#1f1f1f" : "#f5f5f5",
              color: isDark ? "rgba(255,255,255,0.85)" : "rgba(0,0,0,0.88)",
              padding: 16,
              borderRadius: 8,
              maxHeight: 400,
              overflow: "auto",
            }}
          >
            {clientJson}
          </pre>
        )}
      </Modal>

      {/* Dedicated OAuth modal — opened only via the Authorize button */}
      <Modal
        title={
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {isOauthAuthorized ? (
              <ShieldCheck size={16} style={{ color: "#27ae60" }} />
            ) : isOauthExpired ? (
              <ShieldAlert size={16} style={{ color: "#e67e22" }} />
            ) : (
              <ShieldX size={16} style={{ color: "#7f8c8d" }} />
            )}
            {`${displayName} — ${t("mcp.oauth.manage")}`}
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

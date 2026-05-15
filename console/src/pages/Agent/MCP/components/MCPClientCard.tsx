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
import React, { useState, useCallback } from "react";
import { useTheme } from "../../../../contexts/ThemeContext";
import {
  EyeOutlined,
  EyeInvisibleOutlined,
  ToolOutlined,
} from "@ant-design/icons";
import { ShieldCheck, ShieldAlert, ShieldX, KeyRound } from "lucide-react";
import api from "../../../../api";
import { MCPOAuthSection } from "./MCPOAuthSection";
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
}

export const MCPClientCard = React.memo(function MCPClientCard({
  client,
  onToggle,
  onDelete,
  onUpdate,
  onRefresh,
}: MCPClientCardProps) {
  const { t } = useTranslation();
  const { isDark } = useTheme();
  const [isHovered, setIsHovered] = useState(false);
  const [jsonModalOpen, setJsonModalOpen] = useState(false);
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

  // Determine if MCP client is remote or local based on command
  const isRemote =
    client.transport === "streamable_http" || client.transport === "sse";
  const clientType = isRemote ? "Remote" : "Local";

  const oauthStatus = client.oauth_status;
  const now = Date.now() / 1000;
  const isOauthAuthorized =
    !!oauthStatus?.authorized && oauthStatus.expires_at > now;
  const isOauthExpired =
    !!oauthStatus?.authorized && oauthStatus.expires_at <= now;
  const hasOauth = !!oauthStatus;

  const handleToggleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onToggle(client, e);
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
    const jsonStr = JSON.stringify(client, null, 2);
    setEditedJson(jsonStr);
    setIsEditing(false);
    setJsonModalOpen(true);
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
        <div className={styles.cardHeader}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              minWidth: 0,
            }}
          >
            <Tooltip title={client.name}>
              <h3 className={styles.mcpTitle}>{client.name}</h3>
            </Tooltip>
            <span
              className={`${styles.typeBadge} ${
                isRemote ? styles.remote : styles.local
              }`}
            >
              {clientType}
            </span>
            {hasOauth && isOauthExpired && (
              <Tooltip title={t("mcp.oauth.expired")}>
                <ShieldAlert
                  size={13}
                  style={{ color: "#e67e22", flexShrink: 0 }}
                />
              </Tooltip>
            )}
            {hasOauth && isOauthAuthorized && (
              <Tooltip title={t("mcp.oauth.authorized")}>
                <ShieldCheck
                  size={13}
                  style={{ color: "#27ae60", flexShrink: 0 }}
                />
              </Tooltip>
            )}
            {hasOauth && !isOauthAuthorized && !isOauthExpired && (
              <Tooltip title={t("mcp.oauth.notAuthorized")}>
                <ShieldX
                  size={13}
                  style={{ color: "#7f8c8d", flexShrink: 0 }}
                />
              </Tooltip>
            )}
          </div>
          <div className={styles.statusContainer}>
            <span className={styles.statusDot} />
            <span className={styles.statusText}>
              {client.enabled ? t("common.enabled") : t("common.disabled")}
            </span>
          </div>
        </div>

        <p className={styles.mcpDescription}>{client.description || "-"}</p>

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
          {isRemote && (
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
        title={`${client.name} - ${t("mcp.tools")}`}
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
        title={`${client.name} - Configuration`}
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

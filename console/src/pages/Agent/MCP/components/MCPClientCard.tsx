import { Card, Button, Modal, Tooltip, Input } from "@agentscope-ai/design";
import type { MCPClientInfo } from "../../../../api/types";
import { useTranslation } from "react-i18next";
import { useState } from "react";
import { useTheme } from "../../../../contexts/ThemeContext";
import { EyeOutlined, EyeInvisibleOutlined } from "@ant-design/icons";
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
  isHovered: boolean;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
}

export function MCPClientCard({
  client,
  onToggle,
  onDelete,
  onUpdate,
  isHovered,
  onMouseEnter,
  onMouseLeave,
}: MCPClientCardProps) {
  const { t } = useTranslation();
  const { isDark } = useTheme();
  const [jsonModalOpen, setJsonModalOpen] = useState(false);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [editedJson, setEditedJson] = useState("");
  const [isEditing, setIsEditing] = useState(false);

  // Determine if MCP client is remote or local based on command
  const isRemote =
    client.transport === "streamable_http" || client.transport === "sse";
  const clientType = isRemote ? "Remote" : "Local";

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

  const clientJson = JSON.stringify(client, null, 2);

  return (
    <>
      <Card
        hoverable
        onClick={handleCardClick}
        onMouseEnter={onMouseEnter}
        onMouseLeave={onMouseLeave}
        className={`${styles.mcpCard} ${
          client.enabled ? styles.enabledCard : ""
        } ${isHovered ? styles.hover : styles.normal}`}
      >
        <div className={styles.cardHeader}>
          <Tooltip title={client.name}>
            <h3 className={styles.mcpTitle}>
              <span>{client.name}</span>
              <span
                className={`${styles.typeBadge} ${
                  isRemote ? styles.remote : styles.local
                }`}
              >
                {clientType}
              </span>
            </h3>
          </Tooltip>
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
              maxHeight: 500,
              overflow: "auto",
            }}
          >
            {clientJson}
          </pre>
        )}
      </Modal>
    </>
  );
}

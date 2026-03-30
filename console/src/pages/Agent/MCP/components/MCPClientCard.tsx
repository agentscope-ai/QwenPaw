import { Card, Button, Modal, Tooltip, Input } from "@agentscope-ai/design";
import { Server } from "lucide-react";
import type { MCPClientInfo } from "../../../../api/types";
import { useTranslation } from "react-i18next";
import { useState } from "react";
import { useTheme } from "../../../../contexts/ThemeContext";
import styles from "../index.module.less";

interface MCPClientCardProps {
  client: MCPClientInfo;
  onToggle: (client: MCPClientInfo, e: React.MouseEvent) => void;
  onDelete: (client: MCPClientInfo, e: React.MouseEvent) => void;
  onUpdate: (key: string, updates: any) => Promise<boolean>;
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

  // Check if command is npx to show special icon
  const isNpxCommand = client.command?.includes("npx");

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
    onDelete(client, null as any);
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
      const { key, ...updates } = parsed;

      // Send all updates directly to backend, let backend handle env masking check
      const success = await onUpdate(client.key, updates);
      if (success) {
        setJsonModalOpen(false);
        setIsEditing(false);
      }
    } catch (error) {
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
          {/* Left section: icon, name, badge */}
          <div className={styles.leftSection}>
            <span className={styles.fileIcon}>
              {isNpxCommand ? (
                <img
                  src="https://gw.alicdn.com/imgextra/i4/O1CN01iz3wMQ1u1yoImSYTX_!!6000000005978-2-tps-160-160.png"
                  alt="npx"
                  style={{ width: 40, height: 40 }}
                />
              ) : (
                <Server style={{ color: "#1890ff", fontSize: 20 }} />
              )}
            </span>
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
          </div>

          {/* Right section: status */}
          <div className={styles.statusContainer}>
            <span
              className={`${styles.statusDot} ${
                client.enabled ? styles.enabled : styles.disabled
              }`}
            />
            <span
              className={`${styles.statusText} ${
                client.enabled ? styles.enabled : styles.disabled
              }`}
            >
              {client.enabled ? t("common.enabled") : t("common.disabled")}
            </span>
          </div>
        </div>

        {/* Description - only show when exists */}

        <div className={styles.descriptionContainer}>
          <p className={styles.descriptionLabel}>Introduction</p>
          <p className={styles.descriptionText}>{client.description || "-"}</p>
        </div>

        {/* Footer with buttons - only show on hover */}
        {isHovered && (
          <div className={styles.cardFooter}>
            {
              <>
                <Button
                  className={styles.actionButton}
                  onClick={(e) => {
                    e.stopPropagation();
                    handleToggleClick(e);
                  }}
                >
                  {client.enabled ? "Disable" : "Enable"}
                </Button>

                <Button
                  danger
                  className={styles.deleteButtonLarge}
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDeleteClick(e);
                  }}
                >
                  Delete
                </Button>
              </>
            }
          </div>
        )}
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

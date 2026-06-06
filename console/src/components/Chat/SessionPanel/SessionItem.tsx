import React, { useCallback, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Dropdown, Input } from "antd";
import type { InputRef } from "antd";
import {
  DeleteOutlined,
  EditOutlined,
  EllipsisOutlined,
  PushpinOutlined,
  PushpinFilled,
} from "@ant-design/icons";
import type { ChatSession } from "../types";
import styles from "./SessionPanel.module.less";

interface SessionItemProps {
  session: ChatSession;
  isActive: boolean;
  isEditing: boolean;
  onClick: () => void;
  onDelete: () => void;
  onRename: (name: string) => void;
  onPin: () => void;
  onStartEdit: () => void;
  onCancelEdit: () => void;
}

const SessionItem: React.FC<SessionItemProps> = ({
  session,
  isActive,
  isEditing,
  onClick,
  onDelete,
  onRename,
  onPin,
  onStartEdit,
  onCancelEdit,
}) => {
  const { t } = useTranslation();
  const [editValue, setEditValue] = useState(session.name);
  const inputRef = useRef<InputRef>(null);

  const handleRenameSubmit = useCallback(() => {
    const trimmed = editValue.trim();
    if (trimmed && trimmed !== session.name) {
      onRename(trimmed);
    } else {
      onCancelEdit();
    }
  }, [editValue, session.name, onRename, onCancelEdit]);

  const contextMenuItems = [
    {
      key: "rename",
      icon: <EditOutlined />,
      label: t("chat.sessionPanel.rename"),
      onClick: () => {
        setEditValue(session.name);
        onStartEdit();
        setTimeout(() => inputRef.current?.focus(), 50);
      },
    },
    {
      key: "pin",
      icon: session.pinned ? <PushpinFilled /> : <PushpinOutlined />,
      label: session.pinned
        ? t("chat.sessionPanel.unpin")
        : t("chat.sessionPanel.pinToTop"),
      onClick: onPin,
    },
    { type: "divider" as const },
    {
      key: "delete",
      icon: <DeleteOutlined />,
      label: t("chat.sessionPanel.delete"),
      danger: true,
      onClick: onDelete,
    },
  ];

  return (
    <Dropdown menu={{ items: contextMenuItems }} trigger={["contextMenu"]}>
      <div
        className={`${styles.sessionItem} ${
          isActive ? styles.sessionItemActive : ""
        }`}
        onClick={onClick}
        role="button"
        tabIndex={0}
      >
        {session.pinned && <PushpinFilled className={styles.pinIcon} />}
        {isEditing ? (
          <Input
            ref={inputRef}
            size="small"
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onPressEnter={handleRenameSubmit}
            onBlur={handleRenameSubmit}
            onClick={(e) => e.stopPropagation()}
            className={styles.renameInput}
          />
        ) : (
          <>
            <span className={styles.sessionName}>{session.name}</span>
            {session.lastMessage && (
              <span className={styles.sessionPreview}>
                {session.lastMessage}
              </span>
            )}
          </>
        )}
        {session.status === "running" && <span className={styles.runningDot} />}
        {!isEditing && (
          <Dropdown
            menu={{ items: contextMenuItems }}
            trigger={["click"]}
            placement="bottomRight"
          >
            <span
              className={styles.sessionActions}
              onClick={(e) => e.stopPropagation()}
            >
              <EllipsisOutlined />
            </span>
          </Dropdown>
        )}
      </div>
    </Dropdown>
  );
};

export default SessionItem;

import React, { useCallback, useRef, useState } from "react";
import { Dropdown, Input } from "antd";
import type { InputRef } from "antd";
import { useTranslation } from "react-i18next";
import {
  SparkMoreLine,
  SparkDeleteLine,
  SparkEditLine,
  SparkMarkLine,
  SparkMarkFill,
} from "@agentscope-ai/icons";
import { ChannelIcon } from "../pages/Control/Channels/components";
import type { ChatStatus } from "../api/types/chat";
import styles from "./sidebarSessionItem.module.less";

export interface SidebarSessionItemProps {
  sessionId: string;
  name: string;
  channelKey?: string;
  channelLabel?: string;
  chatStatus?: ChatStatus;
  generating?: boolean;
  pinned?: boolean;
  active?: boolean;
  disabled?: boolean;
  editing?: boolean;
  editValue?: string;
  onClick?: (sessionId: string) => void;
  onEdit?: (sessionId: string, currentName: string) => void;
  onDelete?: (sessionId: string) => void;
  onPin?: (sessionId: string) => void;
  onEditChange?: (value: string) => void;
  onEditSubmit?: () => void;
  onEditCancel?: () => void;
}

const SidebarSessionItem: React.FC<SidebarSessionItemProps> = (props) => {
  const { t } = useTranslation();
  const inputRef = useRef<InputRef>(null);
  const [dropdownOpen, setDropdownOpen] = useState(false);

  const inProgress =
    props.generating === true || props.chatStatus === "running";
  const isIdle =
    !inProgress && !!props.chatStatus && props.chatStatus !== "running";

  const handleClick = useCallback(() => {
    if (props.disabled || props.editing) return;
    props.onClick?.(props.sessionId);
  }, [props.disabled, props.editing, props.onClick, props.sessionId]);

  const handleStartEdit = useCallback(() => {
    props.onEdit?.(props.sessionId, props.name);
    setTimeout(() => inputRef.current?.focus(), 50);
  }, [props.onEdit, props.sessionId, props.name]);

  const handleRenameSubmit = useCallback(() => {
    const trimmed = (props.editValue ?? "").trim();
    if (trimmed && trimmed !== props.name) {
      props.onEditSubmit?.();
    } else {
      props.onEditCancel?.();
    }
  }, [props.editValue, props.name, props.onEditSubmit, props.onEditCancel]);

  const dropdownItems = [
    {
      key: "rename",
      icon: <SparkEditLine size={14} />,
      label: t("chat.contextMenu.rename", "Rename"),
      onClick: handleStartEdit,
    },
    {
      key: "pin",
      icon: props.pinned ? (
        <SparkMarkFill size={14} />
      ) : (
        <SparkMarkLine size={14} />
      ),
      label: props.pinned
        ? t("chat.contextMenu.unpin", "Unpin")
        : t("chat.contextMenu.pin", "Pin"),
      onClick: () => props.onPin?.(props.sessionId),
    },
    { type: "divider" as const },
    {
      key: "delete",
      icon: <SparkDeleteLine size={14} />,
      label: t("chat.contextMenu.delete", "Delete"),
      danger: true,
      onClick: () => props.onDelete?.(props.sessionId),
    },
  ];

  const cls = [
    styles.item,
    props.active ? styles.active : "",
    props.disabled ? styles.disabled : "",
    dropdownOpen ? styles.dropdownOpen : "",
  ]
    .filter(Boolean)
    .join(" ");

  const itemContent = (
    <div className={cls} onClick={handleClick} role="button" tabIndex={0}>
      {/* Status slot — leftmost, fixed width */}
      {!props.editing && (
        <span className={styles.statusSlot}>
          {inProgress && <span className={styles.runningDot} />}
          {isIdle && <span className={styles.idleDot} />}
        </span>
      )}

      {/* Name / edit input */}
      {props.editing ? (
        <Input
          ref={inputRef}
          autoFocus
          size="small"
          value={props.editValue}
          className={styles.renameInput}
          onChange={(e) => props.onEditChange?.(e.target.value)}
          onPressEnter={handleRenameSubmit}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault();
              props.onEditCancel?.();
            }
          }}
          onBlur={handleRenameSubmit}
          onClick={(e) => e.stopPropagation()}
        />
      ) : (
        <span className={styles.name}>{props.name || "New Chat"}</span>
      )}

      {/* Channel icon */}
      {!props.editing && props.channelKey && (
        <span
          className={styles.channelTag}
          title={props.channelLabel || props.channelKey}
        >
          <ChannelIcon channelKey={props.channelKey} size={14} />
        </span>
      )}

      {/* ... action button — appears on hover */}
      {!props.editing && (
        <Dropdown
          menu={{ items: dropdownItems }}
          trigger={["click"]}
          placement="bottomRight"
          onOpenChange={setDropdownOpen}
        >
          <span className={styles.moreBtn} onClick={(e) => e.stopPropagation()}>
            <SparkMoreLine size={14} />
          </span>
        </Dropdown>
      )}
    </div>
  );

  // Wrap with right-click context menu as well
  return (
    <Dropdown menu={{ items: dropdownItems }} trigger={["contextMenu"]}>
      {itemContent}
    </Dropdown>
  );
};

export default React.memo(SidebarSessionItem);

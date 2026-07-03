import React, { useCallback, useRef, useState } from "react";
import { Dropdown, Input } from "antd";
import type { InputRef } from "antd";
import { IconButton } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import {
  SparkMoreLine,
  SparkDeleteLine,
  SparkEditLine,
  SparkMarkLine,
  SparkMarkFill,
} from "@agentscope-ai/icons";
import { ChannelIcon } from "../../pages/Control/Channels/components";
import type { ChatStatus } from "../../api/types/chat";
import styles from "./sessionItem.module.less";

export interface SessionItemProps {
  // -- Data --
  sessionId: string;
  name: string;
  channelKey?: string;
  channelLabel?: string;
  chatStatus?: ChatStatus;
  generating?: boolean;
  pinned?: boolean;
  time?: string; // Only used by the drawer variant

  // -- State --
  active?: boolean;
  disabled?: boolean;
  editing?: boolean;
  editValue?: string;

  // -- Variant --
  variant: "drawer" | "sidebar";

  // -- Events --
  onClick?: (sessionId: string) => void;
  onEdit?: (sessionId: string, currentName: string) => void;
  onDelete?: (sessionId: string) => void;
  onPin?: (sessionId: string) => void;
  onEditChange?: (value: string) => void;
  onEditSubmit?: () => void;
  onEditCancel?: () => void;
  onContextMenu?: (sessionId: string, event: React.MouseEvent) => void;
}

const SessionItem: React.FC<SessionItemProps> = ({
  sessionId,
  name,
  channelKey,
  channelLabel,
  chatStatus,
  generating,
  pinned,
  time,
  active,
  disabled,
  editing,
  editValue,
  variant,
  onClick,
  onEdit,
  onDelete,
  onPin,
  onEditChange,
  onEditSubmit,
  onEditCancel,
  onContextMenu,
}) => {
  const { t } = useTranslation();
  const inputRef = useRef<InputRef>(null);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const isComposingRef = useRef(false);

  const inProgress = generating === true || chatStatus === "running";
  const isIdle = !inProgress && !!chatStatus;
  const statusAriaLabel = inProgress
    ? t("chat.statusInProgress")
    : t("chat.statusIdle");

  const handleClick = useCallback(() => {
    if (disabled || editing) return;
    onClick?.(sessionId);
  }, [disabled, editing, onClick, sessionId]);

  const handleStartEdit = useCallback(() => {
    onEdit?.(sessionId, name);
    setTimeout(() => inputRef.current?.focus(), 50);
  }, [onEdit, sessionId, name]);

  const handleRenameSubmit = useCallback(() => {
    const trimmed = (editValue ?? "").trim();
    if (trimmed && trimmed !== name) {
      onEditSubmit?.();
    } else {
      onEditCancel?.();
    }
  }, [editValue, name, onEditSubmit, onEditCancel]);

  const handleContextMenu = useCallback(
    (event: React.MouseEvent) => {
      if (editing) return;
      onContextMenu?.(sessionId, event);
    },
    [onContextMenu, sessionId, editing],
  );

  const dropdownItems = [
    {
      key: "rename",
      icon: <SparkEditLine size={14} />,
      label: t("chat.contextMenu.rename", "Rename"),
      onClick: handleStartEdit,
    },
    {
      key: "pin",
      icon: pinned ? <SparkMarkFill size={14} /> : <SparkMarkLine size={14} />,
      label: pinned
        ? t("chat.contextMenu.unpin", "Unpin")
        : t("chat.contextMenu.pin", "Pin"),
      onClick: () => onPin?.(sessionId),
    },
    { type: "divider" as const },
    {
      key: "delete",
      icon: <SparkDeleteLine size={14} />,
      label: t("chat.contextMenu.delete", "Delete"),
      danger: true,
      onClick: () => onDelete?.(sessionId),
    },
  ];

  const cls = [
    styles.item,
    styles[variant],
    active ? styles.active : "",
    disabled ? styles.disabled : "",
    editing ? styles.editing : "",
    dropdownOpen ? styles.dropdownOpen : "",
  ]
    .filter(Boolean)
    .join(" ");

  const itemContent = (
    <div
      className={cls}
      onClick={handleClick}
      onContextMenu={variant === "drawer" ? handleContextMenu : undefined}
      role="button"
      tabIndex={0}
    >
      {/* Drawer variant: timeline indicator */}
      {variant === "drawer" && <div className={styles.iconPlaceholder} />}

      {/* Status slot — leftmost for sidebar variant only */}
      {!editing && variant === "sidebar" && (
        <span className={styles.statusSlot}>
          {inProgress && <span className={styles.runningDot} />}
          {isIdle && <span className={styles.idleDot} />}
        </span>
      )}

      {/* Content area */}
      <div className={styles.content}>
        {editing ? (
          <Input
            ref={inputRef}
            autoFocus
            size="small"
            value={editValue}
            className={styles.renameInput}
            onChange={(e) => onEditChange?.(e.target.value)}
            onCompositionStart={() => {
              isComposingRef.current = true;
            }}
            onCompositionEnd={() => {
              isComposingRef.current = false;
            }}
            onPressEnter={(e) => {
              if (!e.nativeEvent.isComposing && !isComposingRef.current) {
                handleRenameSubmit();
              }
            }}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                e.preventDefault();
                onEditCancel?.();
              }
            }}
            onBlur={() => {
              setTimeout(() => {
                if (!isComposingRef.current) {
                  handleRenameSubmit();
                }
              }, 100);
            }}
            onClick={(e) => e.stopPropagation()}
          />
        ) : (
          <>
            {variant === "drawer" ? (
              <div className={styles.titleRow}>
                <span
                  className={styles.statusWrap}
                  role="img"
                  aria-label={statusAriaLabel}
                >
                  <span
                    className={`${styles.statusDot} ${
                      inProgress ? styles.statusDotActive : styles.statusDotIdle
                    }`}
                    aria-hidden
                  />
                </span>
                <div className={styles.name}>{name || "New Chat"}</div>
              </div>
            ) : (
              <div className={styles.name}>{name || "New Chat"}</div>
            )}
          </>
        )}
        {/* Drawer variant: show time and channel in meta row */}
        {variant === "drawer" && (
          <div className={styles.metaRow}>
            {time && <span className={styles.time}>{time}</span>}
            {(channelKey || channelLabel) && (
              <span
                className={styles.channelTag}
                title={channelLabel || channelKey}
              >
                {channelKey ? (
                  <ChannelIcon channelKey={channelKey} size={14} />
                ) : null}
                {channelLabel ? (
                  <span className={styles.channelTagText}>{channelLabel}</span>
                ) : null}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Sidebar variant: channel icon */}
      {!editing && variant === "sidebar" && channelKey && (
        <span className={styles.channelTag} title={channelLabel || channelKey}>
          <ChannelIcon channelKey={channelKey} size={14} />
        </span>
      )}

      {/* Pin button - drawer variant only */}
      {!editing && variant === "drawer" && (
        <IconButton
          bordered={false}
          size="small"
          className={styles.pinButton}
          data-pinned={pinned}
          icon={pinned ? <SparkMarkFill /> : <SparkMarkLine />}
          onClick={(e) => {
            e.stopPropagation();
            onPin?.(sessionId);
          }}
        />
      )}

      {/* Action buttons - drawer variant: edit/delete on hover */}
      {!editing && variant === "drawer" && (
        <div className={styles.actions}>
          <IconButton
            bordered={false}
            size="small"
            icon={<SparkEditLine />}
            onClick={(e) => {
              e.stopPropagation();
              handleStartEdit();
            }}
          />
          <IconButton
            bordered={false}
            size="small"
            icon={<SparkDeleteLine />}
            onClick={(e) => {
              e.stopPropagation();
              onDelete?.(sessionId);
            }}
          />
        </div>
      )}

      {/* More button - sidebar variant only */}
      {!editing && variant === "sidebar" && (
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

  // Sidebar variant: wrap with right-click context menu
  if (variant === "sidebar") {
    return (
      <Dropdown menu={{ items: dropdownItems }} trigger={["contextMenu"]}>
        {itemContent}
      </Dropdown>
    );
  }

  return itemContent;
};

export default React.memo(SessionItem);

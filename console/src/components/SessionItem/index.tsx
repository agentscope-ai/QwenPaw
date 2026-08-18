import React, { useCallback, useMemo, useRef, useState } from "react";
import { Dropdown, Input } from "antd";
import type { InputRef } from "antd";
import { useTranslation } from "react-i18next";
import {
  Archive,
  Bot,
  Clock3,
  FolderInput,
  GripVertical,
  MoreHorizontal,
  Pencil,
  Pin,
  PinOff,
  Trash2,
} from "lucide-react";
import { ChannelIcon } from "../../pages/Control/Channels/components";
import type { ChatStatus } from "../../api/types/chat";
import type { ChatGroup } from "../../api/types/chat";
import styles from "./sessionItem.module.less";

export interface SessionItemProps {
  // -- Data --
  sessionId: string;
  name: string;
  channelKey?: string;
  channelLabel?: string;
  chatStatus?: ChatStatus;
  generating?: boolean;
  archived?: boolean;
  pinned?: boolean;
  source?: "chat" | "cron" | "subagent";
  groupId?: string | null;
  groups?: ChatGroup[];
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
  onArchive?: (sessionId: string) => void;
  onPin?: (sessionId: string, pinned: boolean) => void;
  onMove?: (sessionId: string, groupId: string) => void;
  onEditChange?: (value: string) => void;
  onEditSubmit?: () => void;
  onEditCancel?: () => void;
}

const SessionItem: React.FC<SessionItemProps> = ({
  sessionId,
  name,
  channelKey,
  channelLabel,
  chatStatus,
  generating,
  archived,
  pinned = false,
  source,
  groupId,
  groups = [],
  time,
  active,
  disabled,
  editing,
  editValue,
  variant,
  onClick,
  onEdit,
  onDelete,
  onArchive,
  onPin,
  onMove,
  onEditChange,
  onEditSubmit,
  onEditCancel,
}) => {
  const { t } = useTranslation();
  const inputRef = useRef<InputRef>(null);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const isComposingRef = useRef(false);

  const inProgress = generating === true || chatStatus === "running";
  const isSubagent = source === "subagent";
  const isCron = source === "cron";
  const sourceLabel = isCron
    ? t("chat.groups.cronShort", "Cron")
    : t("chat.groups.subagentShort", "Subagent");
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

  const dropdownItems = useMemo(
    () => [
      {
        key: "rename",
        icon: <Pencil size={14} />,
        label: t("chat.contextMenu.rename", "Rename"),
        onClick: handleStartEdit,
      },
      {
        key: "pin",
        icon: pinned ? <PinOff size={14} /> : <Pin size={14} />,
        label: pinned
          ? t("chat.contextMenu.unpin", "Unpin")
          : t("chat.contextMenu.pin", "Pin"),
        onClick: () => onPin?.(sessionId, !pinned),
      },
      {
        key: "move",
        icon: <FolderInput size={14} />,
        label: t("chat.contextMenu.moveToGroup", "Move to group"),
        children: groups.map((group) => ({
          key: `move-${group.id}`,
          label: group.name,
          disabled: group.id === groupId,
          onClick: () => onMove?.(sessionId, group.id),
        })),
      },
      {
        key: "archive",
        icon: <Archive size={14} />,
        label: archived
          ? t("sessions.archive.unaction", "Unarchive")
          : t("sessions.archive.action", "Archive"),
        onClick: () => onArchive?.(sessionId),
      },
      { type: "divider" as const },
      {
        key: "delete",
        icon: <Trash2 size={14} />,
        label: t("chat.contextMenu.delete", "Delete"),
        danger: true,
        onClick: () => onDelete?.(sessionId),
      },
    ],
    [
      archived,
      pinned,
      sessionId,
      t,
      onArchive,
      onPin,
      onDelete,
      groupId,
      groups,
      onMove,
      handleStartEdit,
    ],
  );

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
      data-pinned={pinned}
      onClick={handleClick}
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
            {(isSubagent || isCron) && (
              <span className={styles.sourceTag}>
                {isCron ? <Clock3 size={11} /> : <Bot size={11} />}
                <span>{sourceLabel}</span>
              </span>
            )}
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

      {!editing && variant === "sidebar" && (isSubagent || isCron) && (
        <span className={styles.sourceIcon} title={sourceLabel}>
          {isCron ? <Clock3 size={13} /> : <Bot size={13} />}
        </span>
      )}

      {!editing && pinned && (
        <span
          className={styles.pinMark}
          title={t("chat.group.pinned", "Pinned")}
        >
          <Pin size={11} />
        </span>
      )}

      {!editing && (
        <span
          className={styles.dragHint}
          title={t(
            "chat.groups.dragSessionHint",
            "Press and hold to move this conversation",
          )}
          aria-hidden
        >
          <GripVertical size={12} />
        </span>
      )}

      {/* More button — unified for both variants */}
      {!editing && (
        <Dropdown
          menu={{ items: dropdownItems }}
          trigger={["click"]}
          placement="bottomRight"
          onOpenChange={setDropdownOpen}
        >
          <span className={styles.moreBtn} onClick={(e) => e.stopPropagation()}>
            <MoreHorizontal size={14} />
          </span>
        </Dropdown>
      )}
    </div>
  );

  return (
    <Dropdown menu={{ items: dropdownItems }} trigger={["contextMenu"]}>
      {itemContent}
    </Dropdown>
  );
};

export default React.memo(SessionItem);

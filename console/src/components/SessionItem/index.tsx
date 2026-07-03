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
  // ── 数据 ──
  sessionId: string;
  name: string;
  channelKey?: string;
  channelLabel?: string;
  chatStatus?: ChatStatus;
  generating?: boolean;
  pinned?: boolean;
  time?: string; // 仅 drawer variant 使用

  // ── 状态 ──
  active?: boolean;
  disabled?: boolean;
  editing?: boolean;
  editValue?: string;

  // ── 变体 ──
  variant: "drawer" | "sidebar";

  // ── 事件 ──
  onClick?: (sessionId: string) => void;
  onEdit?: (sessionId: string, currentName: string) => void;
  onDelete?: (sessionId: string) => void;
  onPin?: (sessionId: string) => void;
  onEditChange?: (value: string) => void;
  onEditSubmit?: () => void;
  onEditCancel?: () => void;
  onContextMenu?: (sessionId: string, event: React.MouseEvent) => void;
}

const SessionItem: React.FC<SessionItemProps> = (props) => {
  const { t } = useTranslation();
  const inputRef = useRef<InputRef>(null);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const isComposingRef = useRef(false);

  const inProgress =
    props.generating === true || props.chatStatus === "running";
  const isIdle =
    !inProgress && !!props.chatStatus && props.chatStatus !== "running";
  const statusAriaLabel = inProgress
    ? t("chat.statusInProgress")
    : t("chat.statusIdle");

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

  const handleContextMenu = useCallback(
    (event: React.MouseEvent) => {
      if (props.editing) return;
      props.onContextMenu?.(props.sessionId, event);
    },
    [props.onContextMenu, props.sessionId, props.editing],
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
    styles[props.variant],
    props.active ? styles.active : "",
    props.disabled ? styles.disabled : "",
    props.editing ? styles.editing : "",
    props.pinned ? styles.pinned : "",
    dropdownOpen ? styles.dropdownOpen : "",
  ]
    .filter(Boolean)
    .join(" ");

  const itemContent = (
    <div
      className={cls}
      onClick={handleClick}
      onContextMenu={props.variant === "drawer" ? handleContextMenu : undefined}
      role="button"
      tabIndex={0}
    >
      {/* Drawer variant: timeline indicator */}
      {props.variant === "drawer" && <div className={styles.iconPlaceholder} />}

      {/* Status slot — leftmost for sidebar variant only */}
      {!props.editing && props.variant === "sidebar" && (
        <span className={styles.statusSlot}>
          {inProgress && <span className={styles.runningDot} />}
          {isIdle && <span className={styles.idleDot} />}
        </span>
      )}

      {/* Content area */}
      <div className={styles.content}>
        {props.editing ? (
          <Input
            ref={inputRef}
            autoFocus
            size="small"
            value={props.editValue}
            className={styles.renameInput}
            onChange={(e) => props.onEditChange?.(e.target.value)}
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
                props.onEditCancel?.();
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
            {props.variant === "drawer" ? (
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
                <div className={styles.name}>{props.name || "New Chat"}</div>
              </div>
            ) : (
              <div className={styles.name}>{props.name || "New Chat"}</div>
            )}
          </>
        )}
        {/* Drawer variant: show time and channel in meta row */}
        {props.variant === "drawer" && (
          <div className={styles.metaRow}>
            {props.time && <span className={styles.time}>{props.time}</span>}
            {(props.channelKey || props.channelLabel) && (
              <span
                className={styles.channelTag}
                title={props.channelLabel || props.channelKey}
              >
                {props.channelKey ? (
                  <ChannelIcon channelKey={props.channelKey} size={14} />
                ) : null}
                {props.channelLabel ? (
                  <span className={styles.channelTagText}>
                    {props.channelLabel}
                  </span>
                ) : null}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Sidebar variant: channel icon */}
      {!props.editing && props.variant === "sidebar" && props.channelKey && (
        <span
          className={styles.channelTag}
          title={props.channelLabel || props.channelKey}
        >
          <ChannelIcon channelKey={props.channelKey} size={14} />
        </span>
      )}

      {/* Pin button - drawer variant only */}
      {!props.editing && props.variant === "drawer" && (
        <IconButton
          bordered={false}
          size="small"
          className={styles.pinButton}
          data-pinned={props.pinned}
          icon={props.pinned ? <SparkMarkFill /> : <SparkMarkLine />}
          onClick={(e) => {
            e.stopPropagation();
            props.onPin?.(props.sessionId);
          }}
        />
      )}

      {/* Action buttons - drawer variant: edit/delete on hover */}
      {!props.editing && props.variant === "drawer" && (
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
              props.onDelete?.(props.sessionId);
            }}
          />
        </div>
      )}

      {/* More button - sidebar variant only */}
      {!props.editing && props.variant === "sidebar" && (
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
  if (props.variant === "sidebar") {
    return (
      <Dropdown menu={{ items: dropdownItems }} trigger={["contextMenu"]}>
        {itemContent}
      </Dropdown>
    );
  }

  return itemContent;
};

export default React.memo(SessionItem);

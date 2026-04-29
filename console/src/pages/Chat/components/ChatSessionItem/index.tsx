import React, { useCallback, useRef } from "react";
import { Input } from "antd";
import { IconButton } from "@agentscope-ai/design";
import {
  SparkEditLine,
  SparkDeleteLine,
  SparkMarkLine,
  SparkMarkFill,
} from "@agentscope-ai/icons";
import { useTranslation } from "react-i18next";
import { ChannelIcon } from "../../../Control/Channels/components";
import type { ChatStatus } from "../../../../api/types/chat";
import styles from "./index.module.less";

interface ChatSessionItemProps {
  /** Unique session id — used to call back parent handlers without inline closures */
  sessionId: string;
  /** Session display name */
  name: string;
  /** Pre-formatted creation time string */
  time: string;
  /** Channel key (e.g. console, dingtalk) — used with shared channel icons */
  channelKey?: string;
  /** Localized channel label (e.g. Console, DingTalk) */
  channelLabel?: string;
  chatStatus?: ChatStatus;
  generating?: boolean;
  /** Whether this is the currently selected session */
  active?: boolean;
  /** Whether the item is in inline-edit mode */
  editing?: boolean;
  /** Current value of the edit input */
  editValue?: string;
  /** Whether the chat is pinned */
  pinned?: boolean;
  /** Click callback — receives sessionId */
  onClick?: (sessionId: string) => void;
  /** Edit button callback — receives (sessionId, currentName) */
  onEdit?: (sessionId: string, currentName: string) => void;
  /** Delete button callback — receives sessionId */
  onDelete?: (sessionId: string) => void;
  /** Pin button callback — receives sessionId */
  onPin?: (sessionId: string) => void;
  /** Edit input value change callback */
  onEditChange?: (value: string) => void;
  /** Confirm edit callback (Enter key or blur) */
  onEditSubmit?: () => void;
  /** Cancel edit callback */
  onEditCancel?: () => void;
  /** Context menu callback — parent manages a shared ContextMenu */
  onContextMenu?: (sessionId: string, event: React.MouseEvent) => void;
  className?: string;
}

const ChatSessionItem: React.FC<ChatSessionItemProps> = (props) => {
  const { t } = useTranslation();

  /** Track IME composition state to prevent premature submit during CJK input */
  const isComposingRef = useRef(false);

  const inProgress =
    props.generating === true || props.chatStatus === "running";
  const statusAriaLabel = inProgress
    ? t("chat.statusInProgress")
    : t("chat.statusIdle");

  const handleClick = useCallback(() => {
    props.onClick?.(props.sessionId);
  }, [props.onClick, props.sessionId]);

  const handleEdit = useCallback(
    (event: React.MouseEvent) => {
      event.stopPropagation();
      props.onEdit?.(props.sessionId, props.name);
    },
    [props.onEdit, props.sessionId, props.name],
  );

  const handleDelete = useCallback(
    (event: React.MouseEvent) => {
      event.stopPropagation();
      props.onDelete?.(props.sessionId);
    },
    [props.onDelete, props.sessionId],
  );

  const handlePin = useCallback(
    (event: React.MouseEvent) => {
      event.stopPropagation();
      props.onPin?.(props.sessionId);
    },
    [props.onPin, props.sessionId],
  );

  const handleContextMenu = useCallback(
    (event: React.MouseEvent) => {
      props.onContextMenu?.(props.sessionId, event);
    },
    [props.onContextMenu, props.sessionId],
  );

  const className = [
    styles.chatSessionItem,
    props.active ? styles.active : "",
    props.editing ? styles.editing : "",
    props.pinned ? styles.pinned : "",
    props.className || "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div
      className={className}
      onClick={props.editing ? undefined : handleClick}
      onContextMenu={props.editing ? undefined : handleContextMenu}
    >
      {/* Timeline indicator placeholder */}
      <div className={styles.iconPlaceholder} />
      <div className={styles.content}>
        {props.editing ? (
          <Input
            autoFocus
            size="small"
            value={props.editValue}
            onChange={(e) => props.onEditChange?.(e.target.value)}
            onCompositionStart={() => {
              isComposingRef.current = true;
            }}
            onCompositionEnd={() => {
              isComposingRef.current = false;
            }}
            onPressEnter={() => {
              if (!isComposingRef.current) {
                props.onEditSubmit?.();
              }
            }}
            onBlur={() => {
              if (!isComposingRef.current) {
                props.onEditSubmit?.();
              }
            }}
            onClick={(e) => e.stopPropagation()}
          />
        ) : (
          <div className={styles.titleRow}>
            <div
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
            </div>
            <div className={styles.name}>{props.name}</div>
          </div>
        )}
        <div className={styles.metaRow}>
          <span className={styles.time}>{props.time}</span>
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
      </div>
      {/* Pin button - always visible when pinned, positioned independently */}
      {!props.editing && (
        <IconButton
          bordered={false}
          size="small"
          className={styles.pinButton}
          data-pinned={props.pinned}
          icon={props.pinned ? <SparkMarkFill /> : <SparkMarkLine />}
          onClick={handlePin}
        />
      )}
      {/* Action buttons - edit and delete, only visible on hover */}
      {!props.editing && (
        <div className={styles.actions}>
          <IconButton
            bordered={false}
            size="small"
            icon={<SparkEditLine />}
            onClick={handleEdit}
          />
          <IconButton
            bordered={false}
            size="small"
            icon={<SparkDeleteLine />}
            onClick={handleDelete}
          />
        </div>
      )}
    </div>
  );
};

export default React.memo(ChatSessionItem);

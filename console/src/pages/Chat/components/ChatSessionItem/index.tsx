import React from "react";
import { Input } from "antd";
import { IconButton } from "@agentscope-ai/design";
import { SparkEditLine, SparkDeleteLine } from "@agentscope-ai/icons";
import styles from "./index.module.less";

interface ChatSessionItemProps {
  /** Session display name */
  name: string;
  /** Pre-formatted creation time string */
  time: string;
  /** Whether this is the currently selected session */
  active?: boolean;
  /** Whether the item is in inline-edit mode */
  editing?: boolean;
  /** Current value of the edit input */
  editValue?: string;
  /** Click callback */
  onClick?: () => void;
  /** Edit button callback */
  onEdit?: () => void;
  /** Delete button callback */
  onDelete?: () => void;
  /** Edit input value change callback */
  onEditChange?: (value: string) => void;
  /** Confirm edit callback (Enter key or blur) */
  onEditSubmit?: () => void;
  /** Cancel edit callback */
  onEditCancel?: () => void;
  className?: string;
}

const ChatSessionItem: React.FC<ChatSessionItemProps> = (props) => {
  const className = [
    styles.chatSessionItem,
    props.active ? styles.active : "",
    props.editing ? styles.editing : "",
    props.className || "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div
      className={className}
      onClick={props.editing ? undefined : props.onClick}
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
            onPressEnter={props.onEditSubmit}
            onBlur={props.onEditSubmit}
            onClick={(e) => e.stopPropagation()}
          />
        ) : (
          <div className={styles.name}>{props.name}</div>
        )}
        <div className={styles.time}>{props.time}</div>
      </div>
      {/* Action buttons visible on hover */}
      {!props.editing && (
        <div className={styles.actions}>
          <IconButton
            bordered={false}
            size="small"
            icon={<SparkEditLine />}
            onClick={(e) => {
              e.stopPropagation();
              props.onEdit?.();
            }}
          />
          <IconButton
            bordered={false}
            size="small"
            icon={<SparkDeleteLine />}
            onClick={(e) => {
              e.stopPropagation();
              props.onDelete?.();
            }}
          />
        </div>
      )}
    </div>
  );
};

export default ChatSessionItem;

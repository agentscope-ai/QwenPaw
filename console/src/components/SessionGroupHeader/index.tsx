import { useMemo, useState } from "react";
import { Dropdown, Input } from "antd";
import { useTranslation } from "react-i18next";
import {
  ArrowDown,
  ArrowUp,
  Bot,
  ChevronDown,
  MoreHorizontal,
  Pencil,
  Trash2,
} from "lucide-react";
import type { ChatGroup } from "../../api/types/chat";
import styles from "./SessionGroupHeader.module.less";

interface SessionGroupHeaderProps {
  group: ChatGroup;
  count: number;
  collapsed: boolean;
  pinned?: boolean;
  canMoveUp?: boolean;
  canMoveDown?: boolean;
  onToggle: () => void;
  onRename?: (name: string) => void;
  onDelete?: () => void;
  onMoveUp?: () => void;
  onMoveDown?: () => void;
}

export default function SessionGroupHeader({
  group,
  count,
  collapsed,
  pinned = false,
  canMoveUp = false,
  canMoveDown = false,
  onToggle,
  onRename,
  onDelete,
  onMoveUp,
  onMoveDown,
}: SessionGroupHeaderProps) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(group.name);

  const submitRename = () => {
    const next = name.trim();
    setEditing(false);
    if (next && next !== group.name) onRename?.(next);
    else setName(group.name);
  };

  const menuItems = useMemo(
    () => [
      {
        key: "rename",
        icon: <Pencil size={13} />,
        label: t("chat.groups.rename", "Rename"),
        onClick: () => {
          setName(group.name);
          setEditing(true);
        },
      },
      {
        key: "up",
        icon: <ArrowUp size={13} />,
        label: t("chat.groups.moveUp", "Move up"),
        disabled: !canMoveUp,
        onClick: onMoveUp,
      },
      {
        key: "down",
        icon: <ArrowDown size={13} />,
        label: t("chat.groups.moveDown", "Move down"),
        disabled: !canMoveDown,
        onClick: onMoveDown,
      },
      ...(group.kind === "custom"
        ? [
            { type: "divider" as const },
            {
              key: "delete",
              icon: <Trash2 size={13} />,
              label: t("chat.groups.delete", "Delete group"),
              danger: true,
              onClick: onDelete,
            },
          ]
        : []),
    ],
    [
      canMoveDown,
      canMoveUp,
      group.kind,
      group.name,
      onDelete,
      onMoveDown,
      onMoveUp,
      t,
    ],
  );

  return (
    <div
      className={`${styles.header} ${
        group.kind === "subagents" ? styles.subagent : ""
      }`}
      role="button"
      tabIndex={0}
      onClick={onToggle}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") onToggle();
      }}
    >
      <span
        className={`${styles.chevron} ${collapsed ? styles.collapsed : ""}`}
      >
        <ChevronDown size={13} />
      </span>
      {group.kind === "subagents" && (
        <span className={styles.kindIcon}>
          <Bot size={13} />
        </span>
      )}
      {editing ? (
        <Input
          autoFocus
          size="small"
          className={styles.renameInput}
          value={name}
          onChange={(event) => setName(event.target.value)}
          onPressEnter={submitRename}
          onBlur={submitRename}
          onClick={(event) => event.stopPropagation()}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              setName(group.name);
              setEditing(false);
            }
          }}
        />
      ) : (
        <span className={styles.label}>{group.name}</span>
      )}
      <span className={styles.count}>{count}</span>
      {!pinned && !editing && (
        <Dropdown menu={{ items: menuItems }} trigger={["click"]}>
          <button
            className={styles.more}
            aria-label={t("chat.groups.manage", "Manage group")}
            onClick={(event) => event.stopPropagation()}
          >
            <MoreHorizontal size={14} />
          </button>
        </Dropdown>
      )}
    </div>
  );
}

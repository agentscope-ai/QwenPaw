import { useMemo, useState } from "react";
import { Dropdown, Input } from "antd";
import { useTranslation } from "react-i18next";
import {
  ArrowDown,
  ArrowUp,
  Bot,
  ChevronDown,
  Clock3,
  LockKeyhole,
  MoreHorizontal,
  Pencil,
  Pin,
  PinOff,
  Trash2,
} from "lucide-react";
import type { ChatGroup } from "../../api/types/chat";
import styles from "./SessionGroupHeader.module.less";

interface SessionGroupHeaderProps {
  group: ChatGroup;
  count: number;
  collapsed: boolean;
  canMoveUp?: boolean;
  canMoveDown?: boolean;
  onToggle: () => void;
  onRename?: (name: string) => void;
  onPin?: (pinned: boolean) => void;
  onDelete?: () => void;
  onMoveUp?: () => void;
  onMoveDown?: () => void;
}

export default function SessionGroupHeader({
  group,
  count,
  collapsed,
  canMoveUp = false,
  canMoveDown = false,
  onToggle,
  onRename,
  onPin,
  onDelete,
  onMoveUp,
  onMoveDown,
}: SessionGroupHeaderProps) {
  const { t } = useTranslation();
  const isCron = group.kind === "cron";
  const isSubagents = group.kind === "subagents";
  const isFixedSource = isCron || isSubagents;
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
        key: "pin",
        icon: group.pinned ? <PinOff size={13} /> : <Pin size={13} />,
        label: group.pinned
          ? t("chat.groups.unpin", "Unpin group")
          : t("chat.groups.pin", "Pin group"),
        onClick: () => onPin?.(!group.pinned),
      },
      { type: "divider" as const },
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
      group.pinned,
      onDelete,
      onMoveDown,
      onMoveUp,
      onPin,
      t,
    ],
  );

  return (
    <div
      className={`${styles.header} ${isFixedSource ? styles.source : ""} ${
        group.pinned ? styles.pinned : ""
      } ${!isFixedSource && !editing ? styles.managed : ""}`}
      role="button"
      tabIndex={0}
      title={
        isFixedSource
          ? t(
              isCron ? "chat.groups.cronHint" : "chat.groups.subagentsHint",
              isCron
                ? "Conversations created by scheduled tasks"
                : "Conversations created by child agents",
            )
          : undefined
      }
      onClick={onToggle}
      onKeyDown={(event) => {
        if (event.target !== event.currentTarget) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onToggle();
        }
      }}
    >
      <span
        className={`${styles.chevron} ${collapsed ? styles.collapsed : ""}`}
      >
        <ChevronDown size={13} />
      </span>
      {isFixedSource && (
        <span className={styles.kindIcon}>
          {isCron ? <Clock3 size={13} /> : <Bot size={13} />}
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
      {group.pinned && !isFixedSource && (
        <span
          className={styles.pinMark}
          title={t("chat.groups.pinned", "Pinned group")}
        >
          <Pin size={11} />
        </span>
      )}
      {isFixedSource && (
        <span
          className={styles.lockMark}
          title={t("chat.groups.fixedLast", "Fixed at the bottom")}
        >
          <LockKeyhole size={11} />
        </span>
      )}
      {!isFixedSource && !editing && (
        <Dropdown
          menu={{
            items: menuItems,
            onClick: ({ domEvent }) => domEvent.stopPropagation(),
          }}
          trigger={["click"]}
        >
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

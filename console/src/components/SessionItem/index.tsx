import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Dropdown, Input, Popover } from "antd";
import type { InputRef } from "antd";
import { useTranslation } from "react-i18next";
import {
  Archive,
  Bot,
  Clock3,
  Copy,
  Folder,
  FolderInput,
  MoreHorizontal,
  Pencil,
  Pin,
  PinOff,
  Trash2,
} from "lucide-react";
import { ChannelIcon } from "../../pages/Control/Channels/components";
import type { ChatStatus } from "../../api/types/chat";
import type { ChatGroup } from "../../api/types/chat";
import { useAppMessage } from "../../hooks/useAppMessage";
import { copyText } from "../../utils/clipboard";
import styles from "./sessionItem.module.less";

const MAX_LIST_NAME_CHARS = 100;
const MAX_INFO_NAME_CHARS = 500;

export interface SessionItemProps {
  // -- Data --
  sessionId: string;
  name: string;
  updatedAt?: string | null;
  channelKey?: string;
  channelLabel?: string;
  chatStatus?: ChatStatus;
  generating?: boolean;
  unseenResult?: boolean;
  archived?: boolean;
  pinned?: boolean;
  source?: "chat" | "cron" | "subagent";
  groupId?: string | null;
  groups?: ChatGroup[];

  // -- State --
  active?: boolean;
  disabled?: boolean;
  editing?: boolean;
  editValue?: string;

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
  updatedAt,
  channelKey,
  channelLabel,
  chatStatus,
  generating,
  unseenResult = false,
  archived,
  pinned = false,
  source = "chat",
  groupId,
  groups = [],
  active,
  disabled,
  editing,
  editValue,
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
  const { t, i18n } = useTranslation();
  const { message } = useAppMessage();
  const inputRef = useRef<InputRef>(null);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [infoOpen, setInfoOpen] = useState(false);
  const [infoTimeReference, setInfoTimeReference] = useState(Date.now);
  const isComposingRef = useRef(false);

  const inProgress = generating === true || chatStatus === "running";
  const isIdle = !inProgress && !!chatStatus;
  const hasUnseenResult = isIdle && unseenResult;
  const statusAriaLabel = inProgress
    ? t("chat.statusInProgress")
    : hasUnseenResult
    ? t("chat.statusUnseenResult", "New result")
    : t("chat.statusIdle");

  const displayName = useMemo(
    () =>
      name.length > MAX_LIST_NAME_CHARS
        ? `${name.slice(0, MAX_LIST_NAME_CHARS)}…`
        : name || t("chat.newChat", "New Chat"),
    [name, t],
  );
  const infoName = useMemo(() => {
    const fallbackName = name || t("chat.newChat", "New Chat");
    return fallbackName.length > MAX_INFO_NAME_CHARS
      ? `${fallbackName.slice(0, MAX_INFO_NAME_CHARS)}…`
      : fallbackName;
  }, [name, t]);
  const sessionTime = useMemo(
    () =>
      formatSessionTime(
        updatedAt,
        i18n.resolvedLanguage ?? i18n.language ?? "en",
        infoTimeReference,
      ),
    [i18n.language, i18n.resolvedLanguage, infoTimeReference, updatedAt],
  );

  const fallbackGroupKind =
    source === "cron"
      ? "cron"
      : source === "subagent"
      ? "subagents"
      : "default";
  const sessionGroup =
    groups.find((group) => group.id === groupId) ??
    groups.find((group) => group.kind === fallbackGroupKind);
  const sessionGroupKind = sessionGroup?.kind ?? fallbackGroupKind;
  const sessionGroupLabel =
    sessionGroup?.name ??
    (sessionGroupKind === "cron"
      ? t("chat.groups.cron", "Scheduled task conversations")
      : sessionGroupKind === "subagents"
      ? t("chat.groups.subagents", "Conversations with subagents")
      : t("chat.groups.uncategorized", "Uncategorized"));
  const sessionGroupIcon =
    sessionGroupKind === "cron" ? (
      <Clock3 size={15} aria-hidden="true" />
    ) : sessionGroupKind === "subagents" ? (
      <Bot size={15} aria-hidden="true" />
    ) : (
      <Folder size={15} aria-hidden="true" />
    );

  const infoCard = (
    <div className={styles.infoCard}>
      <div className={styles.infoHeader}>
        <div className={styles.infoName}>{infoName}</div>
        {sessionTime && (
          <time
            className={styles.infoTime}
            dateTime={sessionTime.iso}
            title={sessionTime.exact}
            aria-label={sessionTime.exact}
          >
            {sessionTime.relative}
          </time>
        )}
      </div>
      <div className={styles.infoRows}>
        {channelKey && (
          <div className={styles.infoRow}>
            <span className={styles.infoIcon}>
              <ChannelIcon channelKey={channelKey} size={18} />
            </span>
            <span>{channelLabel || channelKey}</span>
          </div>
        )}
        <div className={styles.infoRow}>
          <span className={styles.infoIcon}>{sessionGroupIcon}</span>
          <span>{sessionGroupLabel}</span>
        </div>
      </div>
    </div>
  );

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

  const handleCopySessionId = useCallback(async () => {
    try {
      await copyText(sessionId);
      message.success(t("common.copied", "Copied to clipboard"));
    } catch {
      message.error(t("common.copyFailed", "Failed to copy to clipboard"));
    }
  }, [message, sessionId, t]);

  const handleDropdownOpenChange = useCallback((open: boolean) => {
    setDropdownOpen(open);
    if (open) setInfoOpen(false);
  }, []);

  const handleInfoOpenChange = useCallback(
    (open: boolean) => {
      if (open && dropdownOpen) return;
      setInfoOpen(open);
      if (open) setInfoTimeReference(Date.now());
    },
    [dropdownOpen],
  );

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
      {
        key: "copy-id",
        icon: <Copy size={14} />,
        label: t("chat.contextMenu.copyId", "Copy conversation ID"),
        onClick: handleCopySessionId,
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
      handleCopySessionId,
      handleStartEdit,
    ],
  );

  const cls = [
    styles.item,
    styles.sidebar,
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
      onKeyDown={(event) => {
        // Rename inputs and the nested actions have their own keyboard
        // behavior; only activate when the session row itself has focus.
        if (
          event.target !== event.currentTarget ||
          event.repeat ||
          event.nativeEvent.isComposing
        ) {
          return;
        }
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          handleClick();
        }
      }}
      role="button"
      aria-disabled={disabled || undefined}
      tabIndex={disabled || editing ? -1 : 0}
    >
      {!editing && (
        <span
          className={styles.statusSlot}
          role="img"
          aria-label={statusAriaLabel}
        >
          {inProgress && <span className={styles.runningDot} />}
          {hasUnseenResult && <span className={styles.unseenDot} />}
          {isIdle && !hasUnseenResult && <span className={styles.idleDot} />}
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
          <MarqueeName name={displayName} />
        )}
      </div>

      {!editing && pinned && (
        <span
          className={styles.pinMark}
          title={t("chat.group.pinned", "Pinned")}
        >
          <Pin size={11} />
        </span>
      )}

      {!editing && (
        <Dropdown
          menu={{
            items: dropdownItems,
            onClick: ({ domEvent }) => domEvent.stopPropagation(),
          }}
          trigger={["click"]}
          placement="bottomRight"
          onOpenChange={handleDropdownOpenChange}
        >
          <button
            type="button"
            aria-label={t("appCenter.moreActions", "More actions")}
            className={styles.moreBtn}
            onClick={(e) => e.stopPropagation()}
          >
            <MoreHorizontal size={14} />
          </button>
        </Dropdown>
      )}
    </div>
  );

  return (
    <Dropdown
      menu={{ items: dropdownItems }}
      trigger={["contextMenu"]}
      onOpenChange={handleDropdownOpenChange}
    >
      <Popover
        content={infoCard}
        trigger={["hover", "focus"]}
        placement="rightTop"
        mouseEnterDelay={0.35}
        destroyOnHidden
        classNames={{ root: styles.infoPopover }}
        open={infoOpen}
        onOpenChange={handleInfoOpenChange}
      >
        {itemContent}
      </Popover>
    </Dropdown>
  );
};

interface FormattedSessionTime {
  exact: string;
  iso: string;
  relative: string;
}

function formatSessionTime(
  value: string | null | undefined,
  locale: string,
  now: number,
): FormattedSessionTime | null {
  if (!value) return null;

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;

  const deltaMs = date.getTime() - now;
  const absoluteDelta = Math.abs(deltaMs);
  let relativeValue = 0;
  let relativeUnit: Intl.RelativeTimeFormatUnit = "second";

  if (absoluteDelta >= 365 * 24 * 60 * 60 * 1000) {
    relativeValue = Math.round(deltaMs / (365 * 24 * 60 * 60 * 1000));
    relativeUnit = "year";
  } else if (absoluteDelta >= 30 * 24 * 60 * 60 * 1000) {
    relativeValue = Math.round(deltaMs / (30 * 24 * 60 * 60 * 1000));
    relativeUnit = "month";
  } else if (absoluteDelta >= 24 * 60 * 60 * 1000) {
    relativeValue = Math.round(deltaMs / (24 * 60 * 60 * 1000));
    relativeUnit = "day";
  } else if (absoluteDelta >= 60 * 60 * 1000) {
    relativeValue = Math.round(deltaMs / (60 * 60 * 1000));
    relativeUnit = "hour";
  } else if (absoluteDelta >= 60 * 1000) {
    relativeValue = Math.round(deltaMs / (60 * 1000));
    relativeUnit = "minute";
  }

  return {
    exact: new Intl.DateTimeFormat(locale, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(date),
    iso: date.toISOString(),
    relative: new Intl.RelativeTimeFormat(locale, {
      numeric: "auto",
      style: "short",
    }).format(relativeValue, relativeUnit),
  };
}

interface MarqueeNameProps {
  name: string;
}

function MarqueeName({ name }: MarqueeNameProps) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const trackRef = useRef<HTMLSpanElement>(null);
  const [overflow, setOverflow] = useState(0);

  useEffect(() => {
    const viewport = viewportRef.current;
    const track = trackRef.current;
    if (!viewport || !track) return;

    const updateOverflow = () => {
      setOverflow(Math.max(0, track.scrollWidth - viewport.clientWidth));
    };
    updateOverflow();
    const observer = new ResizeObserver(updateOverflow);
    observer.observe(viewport);
    observer.observe(track);
    return () => observer.disconnect();
  }, [name]);

  return (
    <div ref={viewportRef} className={styles.nameViewport}>
      <span
        ref={trackRef}
        className={`${styles.nameTrack} ${
          overflow > 0 ? styles.nameTrackOverflow : ""
        }`}
        style={
          {
            "--name-marquee-distance": `-${overflow}px`,
            "--name-marquee-duration": `${Math.max(
              3,
              Math.min(12, overflow / 24 + 2.5),
            )}s`,
          } as React.CSSProperties
        }
      >
        {name}
      </span>
    </div>
  );
}

export default React.memo(SessionItem);

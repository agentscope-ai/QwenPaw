import React, { useEffect, useRef, useState } from "react";
import { Dropdown } from "antd";
import { useChatAnywhereSessionsState } from "@agentscope-ai/chat";
import { Check, ChevronDown, Pencil, X, Clock3 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useCodingMode } from "../../../../stores/codingModeStore";
import type { ExtendedSession } from "../../../../stores/sessionListStore";
import { buildChatPath } from "../../../../utils/sessionRoute";
import sessionApi from "../../sessionApi";
import styles from "./index.module.less";
import { useTranslation } from "react-i18next";
import { chatApi } from "../../../../api/modules/chat";
import { syncSessionsGlobal } from "../../../../stores/sessionListStore";
import { getBackendId } from "../../../../layouts/useSidebarSessionListData";
import { useAppMessage } from "../../../../hooks/useAppMessage";

const ChatHeaderTitle: React.FC = () => {
  const { sessions, currentSessionId } = useChatAnywhereSessionsState();
  const navigate = useNavigate();
  const { t, i18n } = useTranslation();
  const { message } = useAppMessage();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [now, setNow] = useState(Date.now);
  const input = useRef<HTMLInputElement>(null);
  const currentId = useRef(currentSessionId);
  currentId.current = currentSessionId;
  useEffect(() => {
    setEditing(false);
    setSaving(false);
  }, [currentSessionId]);
  useEffect(() => {
    if (editing) {
      input.current?.focus();
      input.current?.select();
    }
  }, [editing]);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60000);
    return () => window.clearInterval(timer);
  }, []);
  const { codingMode } = useCodingMode();
  const currentSession = sessions.find(
    (s) =>
      !!currentSessionId &&
      (s.id === currentSessionId ||
        (s as ExtendedSession).realId === currentSessionId),
  );
  const chatName = currentSession?.name || "New Chat";

  const [open, setOpen] = useState(false);

  const handleSessionClick = (sessionId: string) => {
    navigate(buildChatPath(sessionApi.getEffectiveSessionId(sessionId)), {
      replace: true,
    });
    setOpen(false);
  };

  const menuItems = sessions.map((session) => {
    const item = session as ExtendedSession;
    const date = new Date(item.updatedAt || item.createdAt || "");
    const valid = !Number.isNaN(date.getTime());
    return {
      key: session.id,
      label: (
        <div className={styles.menuItem}>
          <span className={styles.menuItemContent}>
            <span className={styles.menuItemName}>
              {session.name || "New Chat"}
            </span>
            <span className={styles.menuItemMeta}>
              {valid ? (
                <time dateTime={date.toISOString()}>
                  {date.toLocaleString(i18n.language, {
                    year: "numeric",
                    month: "2-digit",
                    day: "2-digit",
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                    hour12: false,
                  })}
                </time>
              ) : (
                <span>#{(item.realId || item.id).slice(-8)}</span>
              )}
              {item.channel && (
                <span className={styles.menuItemChannel}>{item.channel}</span>
              )}
            </span>
          </span>
          {session === currentSession && (
            <Check className={styles.menuItemActive} size={16} aria-hidden />
          )}
        </div>
      ),
      onClick: () => handleSessionClick(session.id),
    };
  });

  const className = codingMode
    ? `${styles.chatName} ${styles.chatNameCoding}`
    : styles.chatName;

  const extended = currentSession as ExtendedSession | undefined;
  const backendId = extended
    ? getBackendId({ id: extended.id, realId: extended.realId })
    : null;
  const updated = extended?.updatedAt ? new Date(extended.updatedAt) : null;
  const validDate =
    updated && !Number.isNaN(updated.getTime()) ? updated : null;
  const minutes = validDate
    ? Math.min(0, Math.round((validDate.getTime() - now) / 60000))
    : 0;
  const unit =
    Math.abs(minutes) >= 1440
      ? "day"
      : Math.abs(minutes) >= 60
      ? "hour"
      : "minute";
  const relative = new Intl.RelativeTimeFormat(i18n.language, {
    numeric: "auto",
  }).format(
    Math.round(minutes / (unit === "day" ? 1440 : unit === "hour" ? 60 : 1)),
    unit,
  );
  const save = async () => {
    const name = draft.trim();
    if (!name || saving || !backendId) return;
    if (name === chatName) {
      setEditing(false);
      return;
    }
    const owner = sessionApi.getActiveOwner();
    const id = currentSessionId;
    setSaving(true);
    try {
      await chatApi.updateChat(backendId, { name });
      if (!sessionApi.isActiveOwner(owner)) return;
      const list = await sessionApi.getSessionList();
      if (!sessionApi.isActiveOwner(owner)) return;
      syncSessionsGlobal(list as ExtendedSession[]);
      if (currentId.current === id) setEditing(false);
    } catch {
      if (sessionApi.isActiveOwner(owner) && currentId.current === id)
        message.error(t("common.saveFailed"));
    } finally {
      if (currentId.current === id) setSaving(false);
    }
  };
  return (
    <div className={styles.titleBlock}>
      <div className={styles.titleRow}>
        {editing ? (
          <form
            className={styles.renameForm}
            onSubmit={(event) => {
              event.preventDefault();
              void save();
            }}
          >
            <input
              ref={input}
              aria-label={t("chat.contextMenu.rename")}
              value={draft}
              maxLength={100}
              disabled={saving}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Escape" && !saving) {
                  event.preventDefault();
                  setEditing(false);
                }
                if (event.key === "Enter" && event.nativeEvent.isComposing)
                  event.preventDefault();
              }}
            />
            <button
              type="submit"
              data-press
              disabled={saving || !draft.trim()}
              aria-label={t("common.save")}
            >
              <Check size={16} />
            </button>
            <button
              type="button"
              data-press
              disabled={saving}
              aria-label={t("common.cancel")}
              onClick={() => setEditing(false)}
            >
              <X size={16} />
            </button>
          </form>
        ) : (
          <>
            <button
              type="button"
              className={styles.titleEdit}
              title={backendId ? t("chat.contextMenu.rename") : chatName}
              disabled={!backendId}
              onClick={() => {
                setDraft(chatName);
                setEditing(true);
              }}
            >
              <span className={className}>{chatName}</span>
              {backendId && <Pencil size={13} className={styles.editIcon} />}
            </button>
            {sessions.length > 1 && (
              <Dropdown
                menu={{ items: menuItems }}
                open={open}
                onOpenChange={setOpen}
                trigger={["click"]}
                placement="bottomLeft"
                overlayClassName={styles.sessionDropdown}
              >
                <button
                  type="button"
                  className={styles.switchButton}
                  aria-label={t("chat.switchSession")}
                  aria-haspopup="menu"
                  aria-expanded={open}
                >
                  <ChevronDown size={14} />
                </button>
              </Dropdown>
            )}
          </>
        )}
      </div>
      {validDate && (
        <span
          className={styles.activity}
          title={validDate.toLocaleString(i18n.language)}
        >
          <Clock3 size={11} />
          <span>{t("chat.lastActive", { time: relative })}</span>
        </span>
      )}
    </div>
  );
};

export default ChatHeaderTitle;

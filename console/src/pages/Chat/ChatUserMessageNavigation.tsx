import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { createPortal } from "react-dom";
import { useContextSelector } from "use-context-selector";
import { ChatAnywhereMessagesContext } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/Context/ChatAnywhereMessagesContext";
import { Popover, Tooltip } from "antd";
import { ChevronDown, ChevronUp, List } from "lucide-react";
import { HistoryNavigationDirectory } from "./HistoryMessageWindow";
import {
  historyMessageWindow,
  type HistoryUserMessage,
} from "./historyMessageWindowStore";
import {
  activeUserAtScrollPosition,
  getNavigationUsers,
  mergeNavigationUsers,
} from "./userMessageNavigation";
import { useUserMessageIndex } from "./useUserMessageIndex";
import { revealCachedMessage } from "./MeasuredMessageWindow";
import styles from "./HistoryMessageWindow.module.less";

export function ChatUserMessageNavigation({
  sessionId,
  onNavigate,
  onCancel,
}: {
  sessionId?: string;
  onNavigate: (item: HistoryUserMessage) => void;
  onCancel: () => void;
}) {
  // Assistant deltas must not trigger directory renders or network requests.
  const usersKey = useContextSelector(ChatAnywhereMessagesContext, (value) =>
    JSON.stringify(getNavigationUsers(value.messages)),
  );
  const visible = useMemo<HistoryUserMessage[]>(
    () => JSON.parse(usersKey),
    [usersKey],
  );
  const window = useSyncExternalStore(
    historyMessageWindow.subscribe,
    historyMessageWindow.getSnapshot,
    () => null,
  );
  const {
    page: directory,
    loading,
    loadOlder,
  } = useUserMessageIndex(sessionId, usersKey);
  const marker = useRef<HTMLSpanElement>(null);
  const [host, setHost] = useState<HTMLElement | null>(null);
  const [active, setActive] = useState<string>();
  const [open, setOpen] = useState(false);
  const [openVersion, setOpenVersion] = useState(0);
  const pending = useRef<HistoryUserMessage>();
  const locatedMessage = useRef<string>();
  const navigationIntent = useRef(0);
  const currentWindow = window?.sessionId === sessionId ? window : null;
  const persisted =
    directory && directory.sessionId === sessionId
      ? directory.items
      : currentWindow?.userMessages ?? [];
  const historyUsers = useMemo(
    () => getNavigationUsers(currentWindow?.turnRows.flat() ?? []),
    [currentWindow?.turnRows],
  );
  const merged = mergeNavigationUsers(
    mergeNavigationUsers(persisted, historyUsers),
    visible,
  );
  const newest = persisted[persisted.length - 1]?.createdAt;
  const liveExtra = mergeNavigationUsers(persisted, visible)
    .slice(persisted.length)
    .filter(
      (item) => !newest || !item.createdAt || item.createdAt >= newest,
    ).length;
  const items = [...merged].sort((a, b) =>
    a.createdAt && b.createdAt ? a.createdAt.localeCompare(b.createdAt) : 0,
  );
  const total = directory
    ? Math.max(directory.total + liveExtra, items.length)
    : items.length;
  const sessionRef = useRef(sessionId);
  sessionRef.current = sessionId;

  // Forward history paging and the directory must share the same index.
  useEffect(() => {
    if (
      directory &&
      currentWindow &&
      currentWindow.userMessages !== directory.items
    ) {
      historyMessageWindow.setUserMessages(
        directory.sessionId,
        directory.items,
      );
    }
  }, [directory, currentWindow]);

  useLayoutEffect(() => {
    setHost(
      marker.current?.closest<HTMLElement>(
        ".qwenpaw-chat-anywhere-layout-right",
      ) ?? null,
    );
  }, []);

  useEffect(() => {
    navigationIntent.current += 1;
    pending.current = undefined;
    locatedMessage.current = undefined;
    setOpen(false);
    setActive(undefined);
  }, [sessionId]);

  const getScroll = useCallback(
    () =>
      host?.querySelector<HTMLElement>("[data-history-message-window]") ??
      host?.querySelector<HTMLElement>(
        ".qwenpaw-chat-anywhere-message-list-bubble-scroll",
      ),
    [host],
  );
  const locate = (item: HistoryUserMessage) => {
    const scroll = getScroll();
    if (!scroll) return false;
    const alias = visible.find(
      (entry) =>
        entry.messageId === item.clientMessageId ||
        (entry.clientMessageId &&
          entry.clientMessageId === item.clientMessageId),
    );
    const element = Array.from(
      scroll.querySelectorAll<HTMLElement>('[data-role="user"][id]'),
    ).find(
      (node) => node.id === item.messageId || node.id === alias?.messageId,
    );
    if (!element) return false;
    const top = scroll.getBoundingClientRect().top;
    const header = host?.querySelector<HTMLElement>(
      ".qwenpaw-chat-anywhere-layout-right-header",
    );
    const inset = Math.max(
      0,
      (header?.getBoundingClientRect().bottom ?? top) - top,
    );
    scroll.scrollTop += element.getBoundingClientRect().top - top - inset - 24;
    locatedMessage.current = element.id;
    scroll.dispatchEvent(new Event("chat-history-navigated"));
    setActive(item.messageId);
    return true;
  };
  useLayoutEffect(() => {
    if (pending.current && locate(pending.current)) pending.current = undefined;
  });

  useEffect(() => {
    const scroll = getScroll();
    if (
      pending.current &&
      scroll &&
      currentWindow &&
      !currentWindow.loading &&
      currentWindow.canLoadOlder
    ) {
      // Publish each bounded fragment before continuing a directory seek.
      // User interaction clears pending and cancels the in-flight request.
      currentWindow.onFillOlder(scroll);
    }
  }, [currentWindow, getScroll]);

  useEffect(() => {
    if (!host) return;
    const cancel = () => {
      navigationIntent.current += 1;
      locatedMessage.current = undefined;
      if (!pending.current) return;
      pending.current = undefined;
      onCancel();
    };
    const update = () => {
      const scroll = getScroll();
      if (!scroll) return;
      const header = host.querySelector<HTMLElement>(
        ".qwenpaw-chat-anywhere-layout-right-header",
      );
      const top =
        Math.max(
          scroll.getBoundingClientRect().top,
          header?.getBoundingClientRect().bottom ?? 0,
        ) + 24;
      const users = Array.from(
        scroll.querySelectorAll<HTMLElement>('[data-role="user"][id]'),
      ).map((element) => ({
        id: element.id,
        top: element.getBoundingClientRect().top,
      }));
      const located = users.find((item) => item.id === locatedMessage.current);
      if (located) {
        // A nested step window may measure its real height after navigation.
        // Keep the requested user visible until explicit user interaction.
        const delta = located.top - top;
        if (Math.abs(delta) > 1) scroll.scrollTop += delta;
        setActive(located.id);
        return;
      }
      const reversed = scroll.className.includes("bubble-list-order-desc");
      const atBottom = reversed
        ? Math.abs(scroll.scrollTop) <= 1
        : scroll.scrollHeight - scroll.clientHeight - scroll.scrollTop <= 1;
      const id = activeUserAtScrollPosition(users, top, atBottom);
      if (id) setActive(id);
    };
    const frame = requestAnimationFrame(update);
    const scroll = getScroll();
    const intersections =
      typeof IntersectionObserver !== "undefined" && scroll
        ? new IntersectionObserver(update, { root: scroll, threshold: [0, 1] })
        : undefined;
    const observeUsers = () => {
      intersections?.disconnect();
      scroll
        ?.querySelectorAll('[data-role="user"][id]')
        .forEach((node) => intersections?.observe(node));
      update();
    };
    const mutations = new MutationObserver(observeUsers);
    if (scroll) mutations.observe(scroll, { childList: true, subtree: true });
    const resize =
      typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(update)
        : undefined;
    if (scroll?.firstElementChild) resize?.observe(scroll.firstElementChild);
    observeUsers();
    host.addEventListener("scroll", update, true);
    host.addEventListener("chat-message-window-rendered", update);
    host.addEventListener("wheel", cancel, { passive: true });
    host.addEventListener("pointerdown", cancel);
    host.addEventListener("keydown", cancel);
    host.addEventListener("touchstart", cancel, { passive: true });
    return () => {
      cancelAnimationFrame(frame);
      mutations.disconnect();
      resize?.disconnect();
      intersections?.disconnect();
      host.removeEventListener("scroll", update, true);
      host.removeEventListener("chat-message-window-rendered", update);
      host.removeEventListener("wheel", cancel);
      host.removeEventListener("pointerdown", cancel);
      host.removeEventListener("keydown", cancel);
      host.removeEventListener("touchstart", cancel);
    };
  }, [host, onCancel, currentWindow, getScroll, usersKey]);

  const select = (item: HistoryUserMessage) => {
    navigationIntent.current += 1;
    onCancel();
    pending.current = undefined;
    setOpen(false);
    if (locate(item) || !item.anchor) return;
    pending.current = item;
    const scroll = getScroll();
    if (
      scroll &&
      revealCachedMessage(scroll, item.messageId, () => {
        if (pending.current === item && locate(item))
          pending.current = undefined;
      })
    )
      return;
    // A later turn may span many pages. Locate this turn first and let
    // viewport loading fetch its successors incrementally.
    onNavigate(item);
  };
  const found = items.findIndex(
    (item) =>
      Boolean(active) &&
      (item.messageId === active || item.clientMessageId === active),
  );
  const index = active ? found : items.length - 1;
  const navigateAdjacent = async (direction: -1 | 1) => {
    const intent = ++navigationIntent.current;
    const target = items[index];
    if (!target) return;
    let entries = persisted;
    let position = entries.findIndex(
      (item) =>
        item.messageId === target.messageId ||
        item.clientMessageId === target.messageId,
    );
    let before = directory?.before;
    while (before && (position < 0 || (direction === -1 && position === 0))) {
      const older = await loadOlder();
      if (
        !older ||
        sessionRef.current !== sessionId ||
        intent !== navigationIntent.current
      )
        return;
      entries = older.items;
      position = entries.findIndex(
        (item) =>
          item.messageId === target.messageId ||
          item.clientMessageId === target.messageId,
      );
      if (older.before === before) return;
      before = older.before;
    }
    const entry =
      position >= 0
        ? entries[position + direction] ?? items[index + direction]
        : items[index + direction];
    if (entry) {
      onCancel();
      pending.current = entry;
      setOpen(false);
      if (locate(entry)) pending.current = undefined;
      else onNavigate(entry);
    }
  };
  return (
    <span ref={marker}>
      {host && sessionId && total >= 3
        ? createPortal(
            <nav
              className={styles.navigation}
              aria-label="User message navigation"
            >
              <Tooltip title="Previous user message" placement="left">
                <button
                  type="button"
                  aria-label="Previous user message"
                  disabled={loading || (index <= 0 && !directory?.before)}
                  onClick={() => void navigateAdjacent(-1)}
                >
                  <ChevronUp size={18} />
                </button>
              </Tooltip>
              <Popover
                open={open}
                onOpenChange={(value) => {
                  setOpen(value);
                  if (value) setOpenVersion((version) => version + 1);
                }}
                content={
                  <HistoryNavigationDirectory
                    activeMessageId={items[index]?.messageId}
                    items={items}
                    openVersion={openVersion}
                    onSelect={select}
                    total={total}
                    hasMore={Boolean(directory?.before)}
                    loading={loading}
                    onLoadOlder={loadOlder}
                  />
                }
                overlayClassName={styles.navigationDirectoryPopover}
                placement="left"
                styles={{ body: { padding: 0 } }}
                trigger="click"
              >
                <button type="button" aria-label="User message directory">
                  <List size={18} />
                  <span>{total > 99 ? "99+" : total}</span>
                </button>
              </Popover>
              <Tooltip title="Next user message" placement="left">
                <button
                  type="button"
                  aria-label="Next user message"
                  disabled={loading || index >= items.length - 1}
                  onClick={() => void navigateAdjacent(1)}
                >
                  <ChevronDown size={18} />
                </button>
              </Tooltip>
            </nav>,
            host,
          )
        : null}
    </span>
  );
}

import { BOTTOM_THRESHOLD_PX } from "./bottomFollow";
import {
  PureComponent,
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { createPortal } from "react-dom";
import {
  Bubble,
  type IAgentScopeRuntimeWebUIMessage,
} from "@agentscope-ai/chat";
import { ArrowDown, LocateFixed } from "lucide-react";
import { useTranslation } from "react-i18next";
import { FixedSizeList } from "react-window";
import { EagerHistoryContent } from "./HostBubbles";
import {
  MeasuredMessageWindow,
  revealCachedMessage,
} from "./MeasuredMessageWindow";
import {
  followInitialHistoryBottom,
  followInitialHistoryPosition,
} from "./initialHistoryBottom";
import { restoreMessageScrollAnchor } from "./messageScroll";
import {
  createMessageWindowState,
  MessageWindowStateContext,
} from "./messageWindowState";
import {
  historyMessageWindow,
  type HistoryUserMessage,
} from "./historyMessageWindowStore";
import styles from "./HistoryMessageWindow.module.less";

const EDGE_TOLERANCE_PX = 1;
const WHEEL_GESTURE_IDLE_MS = 160;
// One user bubble and one reply, with their gaps.
const ESTIMATED_TURN_HEIGHT = 528;
const MAX_SCROLL_RESERVE = 1_000_000;
const EMPTY_TURN_ROWS: IAgentScopeRuntimeWebUIMessage[][] = [];

function turnSequence(message: IAgentScopeRuntimeWebUIMessage) {
  const data = message.cards?.[0]?.data;
  const position = (data?.input?.[0] ?? data?.output?.[0])?.metadata
    ?.qwenpaw_transcript_position;
  const seq = position?.turn_seq;
  return Number.isSafeInteger(seq) && seq > 0 ? (seq as number) : undefined;
}

function historyScrollEdges(scroll: HTMLElement) {
  const style = (scroll.firstElementChild as HTMLElement | null)?.style;
  const before =
    Number.parseFloat(
      style?.getPropertyValue("--history-space-before") ?? "",
    ) || 0;
  const after =
    Number.parseFloat(style?.getPropertyValue("--history-space-after") ?? "") ||
    0;
  const end = Math.max(0, scroll.scrollHeight - scroll.clientHeight - after);
  return {
    start: Math.min(before, end),
    end,
    hasReserve: before > 0 || after > 0,
    loadedHeight: scroll.scrollHeight - before - after,
  };
}

const HistoryMessage = memo(function HistoryMessage({
  message,
  isLast,
}: {
  message: IAgentScopeRuntimeWebUIMessage;
  isLast: boolean;
}) {
  return (
    <Bubble
      {...message}
      isLast={isLast}
      style={{ contentVisibility: "visible", containIntrinsicSize: "none" }}
    />
  );
});

function formatNavigationTime(createdAt: string, locale?: string): string {
  const date = new Date(createdAt);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(locale, {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function HistoryNavigationDirectory({
  activeMessageId,
  items,
  openVersion,
  onSelect,
  total = items.length,
  hasMore = false,
  loading = false,
  onLoadOlder,
}: {
  activeMessageId: string | undefined;
  items: HistoryUserMessage[];
  openVersion: number;
  onSelect: (item: HistoryUserMessage) => void;
  total?: number;
  hasMore?: boolean;
  loading?: boolean;
  onLoadOlder?: () => unknown;
}) {
  const { t, i18n } = useTranslation();
  const listRef = useRef<FixedSizeList>(null);
  const scrollOffset = useRef(0);
  const previousItems = useRef(items);
  const receivedInitialScroll = useRef(false);
  const activeIndex = items.findIndex(
    (item) => item.messageId === activeMessageId,
  );
  const activeIndexRef = useRef(activeIndex);
  activeIndexRef.current = activeIndex;

  const scrollActiveItemIntoView = useCallback(() => {
    if (activeIndexRef.current >= 0)
      listRef.current?.scrollToItem(activeIndexRef.current, "center");
  }, []);

  useLayoutEffect(() => {
    const first = previousItems.current[0];
    const added = first
      ? items.findIndex((item) => item.messageId === first.messageId)
      : 0;
    if (added > 0) listRef.current?.scrollTo(scrollOffset.current + added * 33);
    previousItems.current = items;
  }, [items]);

  useEffect(() => {
    if (!openVersion) return undefined;
    const frame = requestAnimationFrame(() => {
      scrollActiveItemIntoView();
    });
    return () => cancelAnimationFrame(frame);
  }, [openVersion, scrollActiveItemIntoView]);

  return (
    <div className={styles.navigationDirectory}>
      <div className={styles.navigationDirectoryTitle}>
        <span>{t("chat.messageNavigation.title", { count: total })}</span>
        <button
          type="button"
          aria-label={t(
            "chat.messageNavigation.locate",
            "Scroll directory to active user message",
          )}
          className={styles.navigationDirectoryLocate}
          disabled={!activeMessageId}
          onClick={(event) => {
            event.stopPropagation();
            scrollActiveItemIntoView();
          }}
        >
          <LocateFixed size={14} />
        </button>
      </div>
      <FixedSizeList
        className={styles.navigationDirectoryList}
        ref={listRef}
        height={Math.min(360, items.length * 33)}
        width="100%"
        itemCount={items.length}
        itemSize={33}
        initialScrollOffset={Math.max(0, activeIndex * 33 - 164)}
        overscanCount={4}
        itemKey={(index) => items[index].messageId}
        onScroll={({ scrollOffset: offset, scrollUpdateWasRequested }) => {
          scrollOffset.current = offset;
          if (!receivedInitialScroll.current) {
            receivedInitialScroll.current = true;
            return;
          }
          if (!scrollUpdateWasRequested && offset < 66 && hasMore && !loading)
            onLoadOlder?.();
        }}
      >
        {({ index, style }) => {
          const item = items[index];
          const active = item.messageId === activeMessageId;
          return (
            <button
              key={item.messageId}
              type="button"
              className={`${styles.navigationItem} ${
                active ? styles.navigationItemActive : ""
              }`}
              onClick={() => onSelect(item)}
              aria-current={active ? "true" : undefined}
              style={style}
            >
              <span>
                {item.preview ||
                  t("chat.messageNavigation.userMessage", "User message")}
              </span>
              <time dateTime={item.createdAt}>
                {formatNavigationTime(
                  item.createdAt,
                  i18n?.resolvedLanguage ?? i18n?.language,
                )}
              </time>
            </button>
          );
        }}
      </FixedSizeList>
    </div>
  );
}

interface ContentsProps {
  messages: IAgentScopeRuntimeWebUIMessage[];
  sessionId: string;
  canLoadOlder: boolean;
  canLoadNewer?: boolean;
}

interface ScrollAnchor {
  messageId: string;
  offset: number;
  fromStart: number;
  fromEnd: number;
  progress: number;
}

// Capture the actual visible DOM before React inserts a page.
class HistoryContents extends PureComponent<ContentsProps> {
  private content: HTMLDivElement | null = null;
  private windowState = createMessageWindowState();
  private before = 0;
  private after = 0;
  private rangeAfter = 0;
  private latestTurn = 0;

  private reserve(before: number, after: number) {
    this.before = this.props.canLoadOlder ? Math.max(0, before) : 0;
    this.after = this.props.canLoadNewer ? Math.max(0, after) : 0;
    this.content?.style.setProperty(
      "--history-space-before",
      `${this.before}px`,
    );
    this.content?.style.setProperty(
      "--history-space-after",
      `${this.after + this.rangeAfter}px`,
    );
  }

  private estimateSpace() {
    const turns = this.props.messages
      .map(turnSequence)
      .filter((seq) => seq !== undefined);
    const oldest = turns[0];
    const newest = turns[turns.length - 1];
    if (!oldest || !newest) return [0, 0] as const;
    this.latestTurn = Math.max(this.latestTurn, newest);
    // Stay below browser layout limits even for unusually long sessions.
    const estimate = (count: number) =>
      Math.min(count * ESTIMATED_TURN_HEIGHT, MAX_SCROLL_RESERVE);
    return [estimate(oldest - 1), estimate(this.latestTurn - newest)] as const;
  }

  componentDidMount() {
    this.reserve(...this.estimateSpace());
    this.content?.parentElement?.addEventListener("scroll", this.releaseTail);
  }

  componentWillUnmount() {
    this.content?.parentElement?.removeEventListener(
      "scroll",
      this.releaseTail,
    );
  }

  private releaseTail = () => {
    const scroll = this.content?.parentElement;
    if (!scroll || !this.rangeAfter || this.props.canLoadNewer) return;
    if (
      scroll.scrollTop + EDGE_TOLERANCE_PX >=
      historyScrollEdges(scroll).end
    ) {
      this.rangeAfter = 0;
      this.reserve(this.before, this.after);
    }
  };

  getSnapshotBeforeUpdate(): ScrollAnchor | null {
    const content = this.content;
    const scroll = content?.parentElement;
    if (!content || !scroll) return null;
    const viewport = scroll.getBoundingClientRect();
    const bounds = content.getBoundingClientRect();
    const element = Array.from(
      content.querySelectorAll<HTMLElement>("[data-role][id]"),
    ).find((item) => {
      const row = item.getBoundingClientRect();
      return item.id && row.bottom > viewport.top && row.top < viewport.bottom;
    });
    if (!element) return null;
    const anchorTop = element.getBoundingClientRect().top;
    return {
      messageId: element.id,
      offset: anchorTop - viewport.top,
      fromStart: anchorTop - bounds.top,
      fromEnd: bounds.bottom - anchorTop,
      progress:
        scroll.scrollTop /
        Math.max(1, scroll.scrollHeight - scroll.clientHeight),
    };
  }

  componentDidUpdate(
    previous: ContentsProps,
    _state: unknown,
    anchor: ScrollAnchor | null,
  ) {
    const content = this.content;
    const scroll = content?.parentElement;
    if (!content || !scroll) return;
    const element = Array.from(
      content.querySelectorAll<HTMLElement>("[data-role][id]"),
    ).find((item) => item.id === anchor?.messageId);
    const estimate = this.estimateSpace();
    if (!element || !anchor) {
      this.rangeAfter = 0;
      this.reserve(...estimate);
      return;
    }
    const bounds = content.getBoundingClientRect();
    const anchorTop = element.getBoundingClientRect().top;
    // Replace reserves with real content while keeping the message in view.
    const growth = anchorTop - bounds.top - anchor.fromStart;
    let before = this.before - growth;
    const first =
      this.props.messages[0] && turnSequence(this.props.messages[0]);
    const previousFirst =
      previous.messages[0] && turnSequence(previous.messages[0]);
    const prepend = first && previousFirst && first < previousFirst;
    if (prepend && growth > 0 && before < growth && this.props.canLoadOlder) {
      // If another page this tall would exhaust the leading space, estimate
      // the remaining turns using the height that was actually inserted.
      const perTurn = growth / (previousFirst - first);
      before = Math.max(
        before,
        Math.min(MAX_SCROLL_RESERVE, perTurn * (first - 1)),
      );
    }
    this.reserve(
      before,
      this.after + anchor.fromEnd - (bounds.bottom - anchorTop),
    );
    const offset =
      element.getBoundingClientRect().top - scroll.getBoundingClientRect().top;
    if (Math.abs(offset - anchor.offset) > 0.5) {
      scroll.scrollTop += offset - anchor.offset;
    }
    // Moving the reader's anchor forward by one pixel per added pixel of
    // padding needs a corresponding adjustment to the available scroll range.
    if (prepend && anchor.progress > 0 && anchor.progress < 1) {
      const extra =
        scroll.scrollTop / anchor.progress -
        (scroll.scrollHeight - scroll.clientHeight);
      if (extra > 1) {
        this.rangeAfter = Math.min(MAX_SCROLL_RESERVE, this.rangeAfter + extra);
        this.reserve(this.before, this.after);
      }
    }
  }

  render() {
    return (
      <div
        ref={(node) => {
          this.content = node;
        }}
        className={styles.page}
      >
        <MessageWindowStateContext.Provider value={this.windowState}>
          <EagerHistoryContent>
            <MeasuredMessageWindow
              key={this.props.sessionId}
              ids={this.props.messages.map((message) => message.id)}
              gap={24}
              initialEnd
            >
              {(index) => (
                <HistoryMessage
                  message={this.props.messages[index]}
                  isLast={index === this.props.messages.length - 1}
                />
              )}
            </MeasuredMessageWindow>
          </EagerHistoryContent>
        </MessageWindowStateContext.Provider>
      </div>
    );
  }
}

export function HistoryMessageWindowCard() {
  const { t } = useTranslation();
  const current = useSyncExternalStore(
    historyMessageWindow.subscribe,
    historyMessageWindow.getSnapshot,
    () => null,
  );
  const placeholderRef = useRef<HTMLSpanElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pendingNavigationRef = useRef<string>();
  const pendingBottomRef = useRef(false);
  const stopBottomFollowRef = useRef<() => void>();
  const [atBottom, setAtBottom] = useState(true);
  const wheelUntilRef = useRef(0);
  const scrollIntentRef = useRef<"older" | "newer" | null>(null);
  const previousScrollTopRef = useRef(0);
  const directScrollRef = useRef(false);
  const [portalTarget, setPortalTarget] = useState<HTMLElement | null>(null);
  const turnRows = current?.turnRows ?? EMPTY_TURN_ROWS;
  const messages = useMemo(() => turnRows.flat(), [turnRows]);
  const latestUser = current?.userMessages[current.userMessages.length - 1];

  const followBottom = useCallback(() => {
    stopBottomFollowRef.current?.();
    const scroll = scrollRef.current;
    if (scroll)
      stopBottomFollowRef.current = followInitialHistoryBottom(scroll);
  }, []);

  const locate = useCallback((messageId: string) => {
    const scroll = scrollRef.current;
    const element = Array.from(
      scroll?.querySelectorAll<HTMLElement>("[data-role][id]") ?? [],
    ).find((item) => item.id === messageId);
    if (!scroll || !element) return false;
    const header = scroll
      .closest(".qwenpaw-chat-anywhere-layout-right")
      ?.querySelector<HTMLElement>(
        ".qwenpaw-chat-anywhere-layout-right-header",
      );
    const headerInset = header
      ? Math.max(
          0,
          header.getBoundingClientRect().bottom -
            scroll.getBoundingClientRect().top,
        )
      : 0;
    scroll.scrollTop +=
      element.getBoundingClientRect().top -
      scroll.getBoundingClientRect().top -
      headerInset -
      24;
    return true;
  }, []);

  useLayoutEffect(() => {
    setPortalTarget(
      placeholderRef.current?.closest<HTMLElement>(
        ".qwenpaw-chat-anywhere-message-list",
      ) ?? null,
    );
  }, []);

  useLayoutEffect(() => {
    const scroll = scrollRef.current;
    if (!scroll || !current?.sessionId) return;
    const initialAnchor = current.initialScrollAnchor;
    if (initialAnchor) {
      let cached: boolean | undefined;
      stopBottomFollowRef.current = followInitialHistoryPosition(scroll, () => {
        if (restoreMessageScrollAnchor(scroll, initialAnchor)) return;
        cached ??= revealCachedMessage(scroll, initialAnchor.id);
        if (!cached) scroll.scrollTop = scroll.scrollHeight;
      });
    } else followBottom();
    return () => stopBottomFollowRef.current?.();
  }, [
    current?.initialScrollAnchor,
    current?.sessionId,
    portalTarget,
    followBottom,
  ]);

  useLayoutEffect(() => {
    const scroll = scrollRef.current;
    if (!scroll) return;
    // Window measurements can change the bottom distance without scrolling.
    const update = () =>
      setAtBottom(
        scroll.scrollHeight - scroll.clientHeight - scroll.scrollTop <=
          BOTTOM_THRESHOLD_PX,
      );
    const observer = new ResizeObserver(update);
    observer.observe(scroll);
    if (scroll.firstElementChild) observer.observe(scroll.firstElementChild);
    scroll.addEventListener("chat-message-window-rendered", update);
    update();
    return () => {
      observer.disconnect();
      scroll.removeEventListener("chat-message-window-rendered", update);
    };
  }, [current?.sessionId, portalTarget]);

  useLayoutEffect(() => {
    const scroll = scrollRef.current;
    if (!current || !scroll) return;
    const pending = pendingNavigationRef.current;
    if (pending && locate(pending)) {
      pendingNavigationRef.current = undefined;
      if (pendingBottomRef.current) {
        followBottom();
        pendingBottomRef.current = false;
      }
    }
  }, [current, messages, locate, portalTarget, followBottom]);

  const loadNewerHistory = useCallback(() => {
    if (!current || current.loading || current.newerLoadFailed) return;
    const lastUser = [...messages]
      .reverse()
      .find((item) => item.role === "user");
    // Optimistic SDK identities cannot be used as durable history cursors.
    // Keep the live response mounted and return to it only at the viewport edge.
    const liveBoundary =
      current.onReturnToLatest &&
      (lastUser as { history?: boolean } | undefined)?.history !== true;
    if (liveBoundary || current.canLoadNewer === false) {
      const scroll = scrollRef.current;
      if (
        scroll &&
        historyScrollEdges(scroll).end - scroll.scrollTop <= EDGE_TOLERANCE_PX
      )
        current.onReturnToLatest?.();
      return;
    }
    if (lastUser?.id) {
      // A directory jump requests one following page. Further prefetching
      // follows the reader's next scroll gesture instead of evicting the
      // target before it can be read.
      scrollIntentRef.current = null;
      current.onNavigateToUserMessage(
        {
          messageId: lastUser.id,
          preview: "",
          createdAt: "",
          anchor: "",
        },
        "append-newer",
      );
    }
  }, [current, messages]);

  const prefetchHistory = useCallback(() => {
    const scroll = scrollRef.current;
    if (!scroll || !current || historyMessageWindow.getSnapshot()?.loading)
      return;
    if (scroll.clientHeight <= 0) return;
    // Keep two viewports ready in the direction the reader actually chose.
    // In a short window both edges can qualify: never prefer the wrong edge.
    const threshold = scroll.clientHeight * 2;
    const { start, end } = historyScrollEdges(scroll);
    if (
      scrollIntentRef.current === "older" &&
      scroll.scrollTop - start <= threshold &&
      current.canLoadOlder
    ) {
      current.onLoadOlder(scroll);
    } else if (
      scrollIntentRef.current === "newer" &&
      end - scroll.scrollTop <= threshold
    ) {
      loadNewerHistory();
    }
  }, [current, loadNewerHistory]);

  const updateActiveMessage = useCallback(() => {
    const scroll = scrollRef.current;
    if (!scroll || !current) return;
    const topBeforeClamp = scroll.scrollTop;
    const { start, end, hasReserve } = historyScrollEdges(scroll);
    // A fast gesture or thumb drag must not leave the reader in unloaded space.
    if (hasReserve && topBeforeClamp < start) scroll.scrollTop = start;
    else if (hasReserve && topBeforeClamp > end) scroll.scrollTop = end;
    const remaining =
      scroll.scrollHeight - scroll.clientHeight - scroll.scrollTop;
    setAtBottom(remaining <= BOTTOM_THRESHOLD_PX);
    const top = scroll.getBoundingClientRect().top;
    const active = Array.from(
      scroll.querySelectorAll<HTMLElement>("[data-role][id]"),
    ).find((item) => item.getBoundingClientRect().bottom > top);
    historyMessageWindow.setActiveMessage(current.sessionId, active?.id);
    const delta = topBeforeClamp - previousScrollTopRef.current;
    previousScrollTopRef.current = scroll.scrollTop;
    if (directScrollRef.current && Math.abs(delta) > EDGE_TOLERANCE_PX) {
      scrollIntentRef.current = delta < 0 ? "older" : "newer";
    }
    prefetchHistory();
  }, [current, prefetchHistory]);

  useLayoutEffect(() => {
    // Prepending and window measurements move scrollTop to preserve the
    // visible anchor. That correction must not reverse the reader's intent.
    previousScrollTopRef.current = scrollRef.current?.scrollTop ?? 0;
  }, [messages]);

  useEffect(() => {
    if (current?.loading) return;
    // A reader may reach the boundary while a request is in flight. Recheck
    // after publishing, without requiring a second wheel gesture to resume.
    const frame = requestAnimationFrame(prefetchHistory);
    return () => cancelAnimationFrame(frame);
  }, [current, prefetchHistory]);

  useEffect(() => {
    const scroll = scrollRef.current;
    if (!scroll || !current) return;
    const cancelNavigation = () => {
      if (!pendingNavigationRef.current) return;
      pendingNavigationRef.current = undefined;
      pendingBottomRef.current = false;
      current.onCancelPending();
    };
    const wheel = (event: WheelEvent) => {
      cancelNavigation();
      directScrollRef.current = false;
      if (event.deltaY !== 0) {
        scrollIntentRef.current = event.deltaY < 0 ? "older" : "newer";
      }
      if (current.loading || Date.now() < wheelUntilRef.current) return;
      const { start, end } = historyScrollEdges(scroll);
      if (event.deltaY < 0 && scroll.scrollTop - start <= EDGE_TOLERANCE_PX) {
        if (!current.canLoadOlder) return;
        wheelUntilRef.current = Date.now() + WHEEL_GESTURE_IDLE_MS;
        current.onLoadOlder(scroll);
      } else if (
        event.deltaY > 0 &&
        end - scroll.scrollTop <= EDGE_TOLERANCE_PX
      ) {
        wheelUntilRef.current = Date.now() + WHEEL_GESTURE_IDLE_MS;
        loadNewerHistory();
      } else {
        prefetchHistory();
      }
    };
    const directScroll = () => {
      cancelNavigation();
      directScrollRef.current = true;
      previousScrollTopRef.current = scroll.scrollTop;
    };
    const navigated = () => {
      // A directory jump is an explicit request to read from this message
      // onward. Fill its following context even if no wheel event follows.
      directScrollRef.current = false;
      scrollIntentRef.current = "newer";
      previousScrollTopRef.current = scroll.scrollTop;
      prefetchHistory();
    };
    scroll.addEventListener("wheel", wheel, { passive: true });
    scroll.addEventListener("pointerdown", directScroll);
    scroll.addEventListener("touchstart", directScroll, { passive: true });
    scroll.addEventListener("keydown", directScroll);
    scroll.addEventListener("chat-history-navigated", navigated);
    return () => {
      scroll.removeEventListener("wheel", wheel);
      scroll.removeEventListener("pointerdown", directScroll);
      scroll.removeEventListener("touchstart", directScroll);
      scroll.removeEventListener("keydown", directScroll);
      scroll.removeEventListener("chat-history-navigated", navigated);
    };
  }, [current, loadNewerHistory, portalTarget, prefetchHistory]);

  useEffect(() => {
    const scroll = scrollRef.current;
    if (!current || !scroll || current.loading) return;
    const frame = requestAnimationFrame(() => {
      if (
        scroll.clientHeight > 0 &&
        historyScrollEdges(scroll).loadedHeight <= scroll.clientHeight + 1
      ) {
        if (current.canLoadOlder) {
          current.onFillOlder(scroll);
        } else {
          loadNewerHistory();
        }
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [current, loadNewerHistory, portalTarget]);

  return (
    <span ref={placeholderRef}>
      {current && portalTarget
        ? createPortal(
            <div className={styles.window}>
              <div
                ref={scrollRef}
                // Share the SDK's responsive sizing and scrollbar gutter without
                // opting into its live, reverse-order scroll controller.
                className={`${styles.list} qwenpaw-bubble-list-scroll qwenpaw-bubble-list`}
                data-history-message-window="true"
                data-history-loading={String(current.loading)}
                onScroll={updateActiveMessage}
              >
                <HistoryContents
                  key={current.sessionId}
                  messages={messages}
                  sessionId={current.sessionId}
                  canLoadOlder={current.canLoadOlder}
                  canLoadNewer={current.canLoadNewer}
                />
              </div>
              {current.newerLoadFailed && (
                <button
                  type="button"
                  onClick={() =>
                    historyMessageWindow.setNewerLoadFailed(
                      current.sessionId,
                      false,
                    )
                  }
                >
                  {t("common.retry", "Retry")}
                </button>
              )}
              {(current.onReturnToLatest ||
                !atBottom ||
                current.canLoadNewer === true) && (
                <button
                  type="button"
                  className={styles.scrollToBottom}
                  aria-label={t(
                    "chat.messageNavigation.bottom",
                    "Scroll to bottom",
                  )}
                  onClick={() => {
                    if (current.onReturnToLatest) {
                      current.onReturnToLatest();
                      return;
                    }
                    const latest = latestUser;
                    if (
                      latest &&
                      !messages.some((item) => item.id === latest.messageId)
                    ) {
                      pendingNavigationRef.current = latest.messageId;
                      pendingBottomRef.current = true;
                      current.onNavigateToUserMessage(latest, "replace");
                    } else if (scrollRef.current) {
                      followBottom();
                    }
                  }}
                >
                  <ArrowDown size={18} />
                </button>
              )}
            </div>,
            portalTarget,
          )
        : null}
    </span>
  );
}

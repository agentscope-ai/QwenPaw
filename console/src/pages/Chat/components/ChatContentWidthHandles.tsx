/**
 * Drag handles that resize the conversation column.
 *
 * Two full-height strips sit just outside the transcript's left and right edges.
 * Dragging either one publishes a symmetric width change into the Chat page's
 * width axis, so the transcript and composer resize together. The preference is
 * persisted; a press that never moves does not overwrite it, and a double click
 * restores the shipped default. Wheel events over a strip keep scrolling the
 * transcript, and keyboard arrows expose the same adjustment to assistive users.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type {
  KeyboardEvent,
  PointerEvent as ReactPointerEvent,
  RefObject,
  WheelEvent as ReactWheelEvent,
} from "react";
import { useTranslation } from "react-i18next";
import {
  CHAT_CONTENT_WIDTH_KEYBOARD_STEP,
  CHAT_CONTENT_WIDTH_MIN,
  canResizeChatContent,
  clampChatContentWidth,
  contentWidthFromHandleOffset,
  maxChatContentWidth,
  readChatContentWidthPreference,
  resolveChatContentWidth,
  writeChatContentWidthPreference,
} from "../../../utils/chatContentWidth";
import styles from "./ChatContentWidthHandles.module.less";

/** Live width axis consumed by the transcript and composer CSS. */
const DISPLAY_WIDTH_VAR = "--qwenpaw-chat-content-display-width";
/** Persisted preference axis; absent until the user drags a handle. */
const USER_WIDTH_VAR = "--qwenpaw-chat-user-content-width";
/** Vertical anchor (px from the handle top) for the gradient glow segment. */
const POINTER_Y_VAR = "--qwenpaw-width-handle-pointer-y";

const WHEEL_DELTA_LINE = 1;
const WHEEL_DELTA_PAGE = 2;
const FALLBACK_WHEEL_LINE_PX = 16;

type Side = "left" | "right";

interface Props {
  /** Chat column whose measured width bounds the resize range. */
  containerRef: RefObject<HTMLDivElement | null>;
  /** Transcript scrollport that wheel events over a handle keep scrolling. */
  scrollRef: RefObject<HTMLDivElement | null>;
  enabled?: boolean;
}

export default function ChatContentWidthHandles({
  containerRef,
  scrollRef,
  enabled = true,
}: Props) {
  const { t } = useTranslation();
  const [width, setWidth] = useState(0);
  const [visible, setVisible] = useState(false);
  const [dragging, setDragging] = useState<Side | null>(null);
  const maxWidth = useRef(CHAT_CONTENT_WIDTH_MIN);

  /** Publish one width preference (or the shipped default with null) onto the column. */
  const publish = useCallback(
    (preference: number | null) => {
      const container = containerRef.current;
      if (!container) return;
      const columnWidth = container.clientWidth;
      const display = resolveChatContentWidth(columnWidth, preference);
      maxWidth.current = maxChatContentWidth(columnWidth);
      container.style.setProperty(DISPLAY_WIDTH_VAR, `${display}px`);
      if (preference === null) {
        container.style.removeProperty(USER_WIDTH_VAR);
      } else {
        container.style.setProperty(USER_WIDTH_VAR, `${display}px`);
      }
      setWidth(display);
      setVisible(enabled && canResizeChatContent(columnWidth, display));
    },
    [containerRef, enabled],
  );

  // The parent column's ref is attached before effects run; a layout effect
  // here would observe a null ref because child effects commit first.
  useEffect(() => {
    publish(readChatContentWidthPreference());
    const container = containerRef.current;
    if (!container || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      publish(readChatContentWidthPreference());
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, [containerRef, publish]);

  /** Anchor the gradient glow segment at the pointer's height on the handle. */
  const trackPointer = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      const box = event.currentTarget.getBoundingClientRect();
      event.currentTarget.style.setProperty(
        POINTER_Y_VAR,
        `${Math.max(0, event.clientY - box.top)}px`,
      );
    },
    [],
  );

  const startDrag = useCallback(
    (side: Side, event: ReactPointerEvent<HTMLDivElement>) => {
      if (!enabled || event.button !== 0) return;
      const container = containerRef.current;
      if (!container) return;
      event.preventDefault();
      const handleElement = event.currentTarget;
      const originX = event.clientX;
      const base = resolveChatContentWidth(
        container.clientWidth,
        readChatContentWidthPreference(),
      );
      let moved = false;
      let outward = 0;
      setDragging(side);
      trackPointer(event);
      const apply = (nextWidth: number) => {
        const columnWidth = container.clientWidth;
        const next = clampChatContentWidth(nextWidth, columnWidth);
        maxWidth.current = maxChatContentWidth(columnWidth);
        container.style.setProperty(DISPLAY_WIDTH_VAR, `${next}px`);
        container.style.setProperty(USER_WIDTH_VAR, `${next}px`);
        setWidth(next);
      };
      const onMove = (moveEvent: PointerEvent) => {
        outward =
          side === "right"
            ? moveEvent.clientX - originX
            : originX - moveEvent.clientX;
        if (moveEvent.clientX !== originX) moved = true;
        const box = handleElement.getBoundingClientRect();
        handleElement.style.setProperty(
          POINTER_Y_VAR,
          `${Math.max(0, moveEvent.clientY - box.top)}px`,
        );
        apply(
          contentWidthFromHandleOffset(base, outward, container.clientWidth),
        );
      };
      const finish = (commit: boolean) => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onPointerUp);
        window.removeEventListener("pointercancel", onPointerCancel);
        setDragging(null);
        if (commit && moved) {
          writeChatContentWidthPreference(
            contentWidthFromHandleOffset(base, outward, container.clientWidth),
          );
        }
        publish(readChatContentWidthPreference());
      };
      const onPointerUp = () => finish(true);
      const onPointerCancel = () => finish(false);
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onPointerUp);
      window.addEventListener("pointercancel", onPointerCancel);
    },
    [containerRef, enabled, publish, trackPointer],
  );

  const adjustWithKeyboard = useCallback(
    (side: Side, event: KeyboardEvent<HTMLDivElement>) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault();
      const container = containerRef.current;
      if (!container) return;
      const current = resolveChatContentWidth(
        container.clientWidth,
        readChatContentWidthPreference(),
      );
      const outward =
        side === "right"
          ? event.key === "ArrowRight"
            ? 1
            : -1
          : event.key === "ArrowLeft"
          ? 1
          : -1;
      const next = clampChatContentWidth(
        current + outward * CHAT_CONTENT_WIDTH_KEYBOARD_STEP,
        container.clientWidth,
      );
      writeChatContentWidthPreference(next);
      publish(next);
    },
    [containerRef, publish],
  );

  const reset = useCallback(() => {
    writeChatContentWidthPreference(null);
    publish(null);
  }, [publish]);

  const onWheel = useCallback(
    (event: ReactWheelEvent<HTMLDivElement>) => {
      const scroll = scrollRef.current;
      if (!scroll || event.ctrlKey || event.deltaY === 0) return;
      let delta = event.deltaY;
      if (event.deltaMode === WHEEL_DELTA_LINE) {
        const lineHeight = Number.parseFloat(
          getComputedStyle(scroll).lineHeight,
        );
        delta *= Number.isFinite(lineHeight)
          ? lineHeight
          : FALLBACK_WHEEL_LINE_PX;
      } else if (event.deltaMode === WHEEL_DELTA_PAGE) {
        delta *= scroll.clientHeight || 1;
      }
      scroll.scrollBy({ top: delta });
    },
    [scrollRef],
  );

  if (!enabled || !visible) return null;

  return (
    <div className={styles.layer} data-chat-width-handles>
      {(["left", "right"] as const).map((side) => (
        <div
          key={side}
          className={styles.handle}
          data-side={side}
          data-active={dragging === side ? "true" : undefined}
          role="separator"
          aria-orientation="vertical"
          aria-label={t("chat.conversationWidth.resize", "调整会话宽度")}
          aria-valuemin={CHAT_CONTENT_WIDTH_MIN}
          aria-valuemax={maxWidth.current}
          aria-valuenow={width}
          title={t(
            "chat.conversationWidth.hint",
            "拖动调整会话宽度，双击恢复默认",
          )}
          tabIndex={0}
          onPointerDown={(event) => startDrag(side, event)}
          onPointerMove={trackPointer}
          onKeyDown={(event) => adjustWithKeyboard(side, event)}
          onDoubleClick={reset}
          onWheel={onWheel}
        />
      ))}
    </div>
  );
}

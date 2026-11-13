import { useEffect, useRef, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import { ArrowDown } from "lucide-react";
import { attachBottomFollow } from "./bottomFollow";
import { getMessageScroller } from "./messageScroll";
import styles from "./HistoryMessageWindow.module.less";

export function ChatBottomFollow({
  rootRef,
  sessionId,
  disabled,
}: {
  rootRef: RefObject<HTMLDivElement>;
  sessionId?: string;
  disabled: boolean;
}) {
  const [target, setTarget] = useState<HTMLElement | null>(null);
  const [away, setAway] = useState(false);
  const controller = useRef<ReturnType<typeof attachBottomFollow>>();
  useEffect(() => {
    const root = rootRef.current;
    if (!root || disabled) return;
    let attached: HTMLElement | null = null;
    const bind = () => {
      const scroll = getMessageScroller(root);
      if (scroll === attached) return;
      controller.current?.dispose();
      attached?.parentElement?.removeAttribute("data-chat-bottom-owner");
      attached = scroll;
      setTarget(scroll?.parentElement ?? null);
      if (scroll) {
        scroll.parentElement?.setAttribute("data-chat-bottom-owner", "true");
        controller.current = attachBottomFollow(scroll, setAway);
      }
    };
    const observer = new MutationObserver(bind);
    observer.observe(root, { childList: true, subtree: true });
    bind();
    return () => {
      observer.disconnect();
      controller.current?.dispose();
      controller.current = undefined;
      attached?.parentElement?.removeAttribute("data-chat-bottom-owner");
    };
  }, [rootRef, sessionId, disabled]);
  if (disabled || !target || !away) return null;
  return createPortal(
    <button
      type="button"
      className={styles.scrollToBottom}
      aria-label="Scroll to bottom"
      onClick={() => controller.current?.resume()}
    >
      <ArrowDown size={18} />
    </button>,
    target,
  );
}

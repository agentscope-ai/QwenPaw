import React, { useEffect, useRef, useState } from "react";
import { Dropdown } from "antd";
import { useChatAnywhereSessionsState } from "@agentscope-ai/chat";
import { useCodingMode } from "../../../../stores/codingModeStore";
import styles from "./index.module.less";

const MOBILE_BREAKPOINT_PX = 480;

const ChatHeaderTitle: React.FC = () => {
  const { sessions, currentSessionId, setCurrentSessionId } =
    useChatAnywhereSessionsState();
  const { codingMode } = useCodingMode();
  const currentSession = sessions.find((s) => s.id === currentSessionId);
  const chatName = currentSession?.name || "New Chat";

  const [open, setOpen] = useState(false);

  // Detect mobile + whether title overflows. On mobile + overflow, render as
  // a horizontal marquee; otherwise keep the original ellipsis behavior.
  const containerRef = useRef<HTMLSpanElement | null>(null);
  const measureRef = useRef<HTMLSpanElement | null>(null);
  const [shouldMarquee, setShouldMarquee] = useState(false);

  useEffect(() => {
    const check = () => {
      const w =
        typeof window !== "undefined" ? window.innerWidth : Number.MAX_VALUE;
      const isMobile = w <= MOBILE_BREAKPOINT_PX;
      if (!isMobile) {
        setShouldMarquee(false);
        return;
      }
      const containerWidth =
        containerRef.current?.getBoundingClientRect().width ?? 0;
      const textWidth = measureRef.current?.getBoundingClientRect().width ?? 0;
      // Add a few px tolerance to avoid borderline jitter.
      setShouldMarquee(textWidth > containerWidth + 2);
    };

    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, [chatName, codingMode]);

  const handleSessionClick = (sessionId: string) => {
    setCurrentSessionId(sessionId);
    setOpen(false);
  };

  const menuItems = sessions.map((session) => ({
    key: session.id,
    label: (
      <div className={styles.menuItem}>
        <span className={styles.menuItemName}>
          {session.name || "New Chat"}
        </span>
        {session.id === currentSessionId && (
          <span className={styles.menuItemActive}>✓</span>
        )}
      </div>
    ),
    onClick: () => handleSessionClick(session.id),
  }));

  const className = codingMode
    ? `${styles.chatName} ${styles.chatNameCoding}`
    : styles.chatName;

  const titleContent = (
    <span className={className} ref={containerRef}>
      {shouldMarquee ? (
        <span className={styles.marquee}>{chatName}</span>
      ) : (
        chatName
      )}
    </span>
  );

  // Hidden span used to measure intrinsic text width for the marquee decision.
  // Placed outside .chatName so it does not duplicate text for screen readers
  // or testing-library queries.
  const measureSpan = (
    <span
      ref={measureRef}
      aria-hidden="true"
      style={{
        position: "absolute",
        visibility: "hidden",
        whiteSpace: "nowrap",
        pointerEvents: "none",
      }}
    >
      {chatName}
    </span>
  );

  if (sessions.length <= 1) {
    return (
      <>
        {titleContent}
        {measureSpan}
      </>
    );
  }

  return (
    <Dropdown
      menu={{ items: menuItems }}
      open={open}
      onOpenChange={setOpen}
      trigger={["click"]}
      placement="bottomLeft"
    >
      <span className={styles.trigger}>
        {titleContent}
        {measureSpan}
      </span>
    </Dropdown>
  );
};

export default ChatHeaderTitle;

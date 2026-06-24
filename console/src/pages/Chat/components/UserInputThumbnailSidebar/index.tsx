import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Anchor } from "antd";
import {
  UpOutlined,
  DownOutlined,
  UnorderedListOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { useUserMessageSnapshot } from "./useUserMessageSnapshot";
import styles from "./index.module.less";

const THUMB_ID_PREFIX = "user-thumb-";
const MAX_TEXT = 26;

function truncate(s: string, n: number) {
  return s.length <= n ? s : s.slice(0, n) + "…";
}

interface UserInputThumbnailSidebarProps {
  visible?: boolean;
}

const UserInputThumbnailSidebar: React.FC<UserInputThumbnailSidebarProps> = ({
  visible = true,
}) => {
  const { t } = useTranslation();
  const { snapshots } = useUserMessageSnapshot();
  const [expanded, setExpanded] = useState(false);
  const scrollerRef = useRef<HTMLElement | null>(null);
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Clean up timer on unmount
  useEffect(() => {
    return () => {
      if (closeTimerRef.current) clearTimeout(closeTimerRef.current);
    };
  }, []);

  const handleMouseEnter = useCallback(() => {
    if (closeTimerRef.current) {
      clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
    setExpanded(true);
  }, []);

  const handleMouseLeave = useCallback(() => {
    closeTimerRef.current = setTimeout(() => {
      setExpanded(false);
      closeTimerRef.current = null;
    }, 300);
  }, []);

  // Tag each visible bubble with an id & detect scroll container
  useEffect(() => {
    if (snapshots.length === 0) return;

    snapshots.forEach((snap) => {
      snap.element.id = `${THUMB_ID_PREFIX}${snap.index}`;
    });

    // Detect scrollable ancestor
    let scroller: Element | null = snapshots[0].element.parentElement;
    while (scroller && scroller !== document.documentElement) {
      const s = getComputedStyle(scroller);
      if (
        (s.overflowY === "auto" || s.overflowY === "scroll") &&
        scroller.scrollHeight > scroller.clientHeight
      ) {
        break;
      }
      scroller = scroller.parentElement;
    }
    scrollerRef.current = (scroller as HTMLElement) ?? null;
  }, [snapshots]);

  // Header height for Anchor targetOffset
  const targetOffset = useMemo(() => {
    const area = document.querySelector('[class*="chatMessagesArea"]');
    const header = area?.querySelector('[class*="layout-right-header"]');
    return header ? header.getBoundingClientRect().height + 12 : 66;
  }, [snapshots.length]);

  const getContainer = useCallback(
    () => scrollerRef.current || (window as unknown as HTMLElement),
    [],
  );

  // Click: scroll directly to the DOM element (no hash change)
  const handleAnchorClick = useCallback(
    (e: React.MouseEvent<HTMLElement>, link: { href: string }) => {
      e.preventDefault();
      e.stopPropagation();

      const indexStr = link.href.replace(/.*user-thumb-/, "");
      const index = parseInt(indexStr, 10);
      if (Number.isNaN(index)) return;

      const target = snapshots[index]?.element;
      if (target) {
        target.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    },
    [snapshots],
  );

  // Build Anchor items from DOM-visible bubbles only
  const anchorItems = useMemo(
    () =>
      snapshots.map((snap) => {
        const text = snap.text.trim()
          ? truncate(snap.text, MAX_TEXT)
          : `📎 ${t("chat.thumbnailSidebar.attachment")}`;
        return {
          key: snap.id,
          href: `#${THUMB_ID_PREFIX}${snap.index}`,
          title: (
            <span className={styles.anchorItemInner}>
              <span className={styles.thumbnailDot} />
              <span className={styles.anchorItemContent}>
                <span className={styles.thumbnailText}>{text}</span>
                {snap.timeLabel && (
                  <span className={styles.thumbnailTime}>{snap.timeLabel}</span>
                )}
              </span>
            </span>
          ),
        };
      }),
    [snapshots, t],
  );

  // Scroll to top (first message) / bottom (latest content)
  const scrollToEdge = useCallback(
    (direction: "top" | "bottom") => {
      if (direction === "top") {
        // Scroll to the first user bubble
        const target = snapshots[0]?.element;
        if (target) {
          target.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      } else {
        // Scroll to very bottom (newest content)
        // In column-reverse layout, scrollTop=0 is the bottom
        const scroller = scrollerRef.current;
        if (scroller) {
          scroller.scrollTo({ top: 0, behavior: "smooth" });
        }
      }
    },
    [snapshots],
  );

  if (!visible || snapshots.length === 0) return null;

  return (
    <div className={styles.sidebarRoot}>
      {/* Icon group: up arrow + count badge (hover trigger) + down arrow */}
      <div className={styles.collapsedGroup}>
        <button
          className={styles.scrollBtn}
          onClick={() => scrollToEdge("top")}
          aria-label="Scroll to top"
        >
          <UpOutlined />
        </button>
        <div
          className={styles.countBadgeArea}
          onMouseEnter={handleMouseEnter}
          onMouseLeave={handleMouseLeave}
        >
          {/* Expanded: anchor list (appears to the LEFT) */}
          {expanded && (
            <div className={styles.anchorWrapper}>
              <Anchor
                items={anchorItems}
                getContainer={getContainer}
                targetOffset={targetOffset}
                onClick={handleAnchorClick}
                affix={false}
              />
            </div>
          )}
          <div className={styles.countBadge}>
            <UnorderedListOutlined className={styles.countIcon} />
            <span className={styles.countNum}>
              {snapshots.length > 99 ? "99+" : snapshots.length}
            </span>
          </div>
        </div>
        <button
          className={styles.scrollBtn}
          onClick={() => scrollToEdge("bottom")}
          aria-label="Scroll to bottom"
        >
          <DownOutlined />
        </button>
      </div>
    </div>
  );
};

export default UserInputThumbnailSidebar;

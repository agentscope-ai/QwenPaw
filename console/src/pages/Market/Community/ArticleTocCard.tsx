import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { List } from "lucide-react";
import type { TocItem } from "./articleToc";
import styles from "./index.module.less";

/** 标题定位/高亮判定的顶部偏移（相对滚动容器视口顶部） */
const TOP_OFFSET = 80;
/** 高亮判定容差：像素取整/缩放时标题 top 可能略大于 TOP_OFFSET */
const SPY_TOLERANCE = 4;

function scrollContainerOf(node: HTMLElement | null): HTMLElement | null {
  for (let el = node?.parentElement ?? null; el; el = el.parentElement) {
    const { overflowY } = getComputedStyle(el);
    if (overflowY === "auto" || overflowY === "scroll") return el;
  }
  return null;
}

/** Right-hand contents card: scrollspy highlight + click to jump. */
export function ArticleToc({ items }: { items: TocItem[] }) {
  const { t } = useTranslation();
  const [activeId, setActiveId] = useState("");
  const sectionRef = useRef<HTMLElement | null>(null);
  const listRef = useRef<HTMLUListElement | null>(null);
  const itemRefs = useRef(new Map<string, HTMLLIElement>());
  // 点击目录后的锁定：用户未真正滚动前 spy 不重算，避免高亮回退到上一条
  const clickLockRef = useRef<{ id: string; top: number } | null>(null);

  // Keep the active row inside the list's own scrollport; called on every
  // spy tick so the TOC follows the content scroll continuously instead of
  // only on the frame where the active id happens to change.
  const revealActive = (id: string) => {
    const list = listRef.current;
    const item = id ? itemRefs.current.get(id) : null;
    if (!list || !item) return;
    const listRect = list.getBoundingClientRect();
    const itemRect = item.getBoundingClientRect();
    if (itemRect.top < listRect.top) {
      list.scrollTop -= listRect.top - itemRect.top;
    } else if (itemRect.bottom > listRect.bottom) {
      list.scrollTop += itemRect.bottom - listRect.bottom;
    }
  };

  useEffect(() => {
    if (items.length === 0) {
      setActiveId("");
      return;
    }
    const container = scrollContainerOf(sectionRef.current);
    clickLockRef.current = null;

    let ticking = false;
    const compute = () => {
      ticking = false;
      const lock = clickLockRef.current;
      const scrollTop = container ? container.scrollTop : window.scrollY;
      if (lock) {
        if (Math.abs(scrollTop - lock.top) <= 2) {
          setActiveId(lock.id);
          revealActive(lock.id);
          return;
        }
        clickLockRef.current = null;
      }
      const base = container ? container.getBoundingClientRect().top : 0;
      let bestId = items[0]?.id ?? "";
      for (const item of items) {
        const el = document.getElementById(item.id);
        if (!el) continue;
        if (
          el.getBoundingClientRect().top - base <=
          TOP_OFFSET + SPY_TOLERANCE
        ) {
          bestId = item.id;
        } else {
          break;
        }
      }
      const atBottom = container
        ? container.scrollTop + container.clientHeight >=
          container.scrollHeight - 4
        : window.innerHeight + window.scrollY >=
          document.documentElement.scrollHeight - 4;
      if (atBottom) bestId = items[items.length - 1]?.id ?? bestId;
      setActiveId(bestId);
      revealActive(bestId);
    };
    const onScroll = () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(compute);
    };

    compute();
    if (container) {
      container.addEventListener("scroll", onScroll, { passive: true });
      window.addEventListener("scroll", onScroll, { passive: true });
      window.addEventListener("resize", onScroll);
      return () => {
        container.removeEventListener("scroll", onScroll);
        window.removeEventListener("scroll", onScroll);
        window.removeEventListener("resize", onScroll);
      };
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, [items]);

  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    // Inline enforcement of the viewport clamp: guarantees the list is the
    // scroller even if a stale CSS-module generation drops the rule in dev.
    // Deps on items: the first render may bail out with an empty list, so the
    // <ul> only exists once data arrives.
    list.style.maxHeight = "calc(100vh - 160px)";
    list.style.overflowY = "auto";
  }, [items]);

  useEffect(() => {
    const list = listRef.current;
    const activeItem = activeId ? itemRefs.current.get(activeId) : null;
    if (!list || !activeItem) return;
    const listRect = list.getBoundingClientRect();
    const itemRect = activeItem.getBoundingClientRect();
    if (itemRect.top < listRect.top) {
      list.scrollTop -= listRect.top - itemRect.top;
    } else if (itemRect.bottom > listRect.bottom) {
      list.scrollTop += itemRect.bottom - listRect.bottom;
    }
  }, [activeId]);

  if (items.length === 0) return null;
  const minLevel = Math.min(...items.map((item) => item.level));

  const handleClick = (id: string) => {
    const el = document.getElementById(id);
    if (!el) return;
    setActiveId(id);
    const container = scrollContainerOf(sectionRef.current);
    const base = container ? container.getBoundingClientRect().top : 0;
    const current = container ? container.scrollTop : window.scrollY;
    const top = Math.max(
      0,
      el.getBoundingClientRect().top - base + current - TOP_OFFSET,
    );
    if (container) {
      if (typeof container.scrollTo === "function") {
        container.scrollTo({ top, behavior: "instant" });
      } else {
        container.scrollTop = top;
      }
      clickLockRef.current = { id, top: container.scrollTop };
    } else {
      window.scrollTo({ top, behavior: "instant" });
      clickLockRef.current = { id, top: window.scrollY };
    }
  };

  return (
    <section ref={sectionRef} className={styles.tocCard}>
      <div className={styles.tocTitle}>
        <List size={16} aria-hidden="true" />
        <span>{t("communityPage.tocTitle")}</span>
      </div>
      <nav aria-label={t("communityPage.tocTitle")}>
        <ul ref={listRef} className={styles.tocList}>
          {items.map((item) => {
            const depth = Math.max(0, item.level - minLevel);
            const active = item.id === activeId;
            return (
              <li
                key={item.id}
                ref={(element) => {
                  if (element) itemRefs.current.set(item.id, element);
                  else itemRefs.current.delete(item.id);
                }}
                style={{ paddingLeft: depth * 12 }}
              >
                <button
                  type="button"
                  title={item.text}
                  className={`${styles.tocItem} ${
                    active ? styles.tocItemActive : ""
                  }`}
                  onClick={() => handleClick(item.id)}
                >
                  {item.text}
                </button>
              </li>
            );
          })}
        </ul>
      </nav>
    </section>
  );
}

import { useEffect, type RefObject } from "react";

/** Locate a translated setting after its lazy page has mounted. */
export function useSettingsSearchTarget(
  container: RefObject<HTMLElement | null>,
  target: { page: string; label: string; tab?: string } | null,
  activePage: string | undefined,
) {
  useEffect(() => {
    const root = container.current;
    if (!root || !target || target.page !== activePage) return;
    let highlighted: HTMLElement | null = null;
    let frame = 0;
    const locate = () => {
      if (highlighted) return;
      const tab = Array.from(
        root.querySelectorAll<HTMLElement>('[role="tab"]'),
      ).find(
        (element) =>
          element.textContent?.trim() === (target.tab ?? target.label),
      );
      if (tab && tab.getAttribute("aria-selected") !== "true") {
        tab.click();
        return;
      }
      const match = Array.from(
        root.querySelectorAll<HTMLElement>("h2,h3,h4,strong,label,button,span"),
      ).find(
        (element) =>
          element.textContent?.trim() === target.label &&
          element.getClientRects().length > 0,
      );
      if (!match) return;
      highlighted =
        match.closest<HTMLElement>("[data-setting-block],.ant-form-item") ??
        match;
      highlighted.setAttribute("data-search-highlight", "true");
      frame = requestAnimationFrame(() => {
        highlighted?.scrollIntoView({ block: "center", behavior: "instant" });
      });
    };
    const observer = new MutationObserver(locate);
    observer.observe(root, {
      childList: true,
      subtree: true,
      attributes: true,
    });
    locate();
    const timeout = window.setTimeout(() => observer.disconnect(), 5000);
    return () => {
      observer.disconnect();
      window.clearTimeout(timeout);
      cancelAnimationFrame(frame);
      highlighted?.removeAttribute("data-search-highlight");
    };
  }, [container, target, activePage]);
}

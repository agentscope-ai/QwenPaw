import { useEffect, type RefObject } from "react";
import type { SettingsSearchTarget } from "@/plugins/settingsSearch";

/** Locate settings by stable identifiers, including portalled editors. */
export function useSettingsSearchTarget(
  container: RefObject<HTMLElement | null>,
  target: SettingsSearchTarget | null,
  activePage: string | undefined,
) {
  useEffect(() => {
    const root =
      target?.targetId || target?.surface
        ? container.current?.ownerDocument.body
        : container.current;
    if (!root || !target || target.page !== activePage) return;
    let highlighted: HTMLElement | null = null;
    let frame = 0;
    let scrollFrame = 0;
    let openedSurface = false;
    let pendingTab: HTMLElement | undefined;
    const visible = (element: HTMLElement) =>
      element.getClientRects().length > 0 &&
      !element.closest('[hidden],[aria-hidden="true"],[inert]') &&
      getComputedStyle(element).visibility !== "hidden";
    const text = (element: HTMLElement) => {
      const copy = element.cloneNode(true) as HTMLElement;
      copy
        .querySelectorAll(
          'svg,[aria-hidden="true"],.ant-badge,.qwenpaw-badge,[data-settings-count]',
        )
        .forEach((child) => child.remove());
      return copy.textContent?.replace(/\s+/g, " ").trim();
    };
    const find = (
      selector: string,
      predicate: (element: HTMLElement) => boolean,
    ) =>
      Array.from(root.querySelectorAll<HTMLElement>(selector)).find(
        (element) => !element.closest("aside,nav") && predicate(element),
      );
    const sameLabel = (element: HTMLElement) =>
      text(element) === target.label ||
      element.getAttribute("aria-label") === target.label;
    const locate = () => {
      if (
        highlighted?.isConnected &&
        highlighted.hasAttribute("data-search-highlight")
      )
        return;
      highlighted = null;
      const candidates = target.targetId
        ? Array.from(
            root.querySelectorAll<HTMLElement>("[data-settings-target]"),
          ).filter(
            (element) => element.dataset.settingsTarget === target.targetId,
          )
        : [];
      const stableTarget = candidates.find(visible) ?? candidates[0];
      if (
        (!stableTarget || !visible(stableTarget)) &&
        target.surface &&
        !openedSurface
      ) {
        const opener = find(
          "button[data-settings-open]",
          (button) =>
            button.dataset.settingsOpen === target.surface &&
            button.getAttribute("aria-expanded") !== "true" &&
            visible(button) &&
            !(button as HTMLButtonElement).disabled,
        );
        if (opener) {
          openedSurface = true;
          opener.click();
          return;
        }
      }
      const section = find("button[data-settings-labels]", (button) => {
        const labels = button.dataset.settingsLabels?.split("\u001f") ?? [];
        return (
          labels.includes(target.label) || labels.includes(target.tab ?? "")
        );
      });
      if (section && section.getAttribute("aria-expanded") !== "true") {
        section.click();
        return;
      }
      const tab = find(
        '[role="tab"]',
        (element) =>
          visible(element) &&
          ((target.tabId &&
            (element.dataset.settingsTab === target.tabId ||
              element.querySelector<HTMLElement>("[data-settings-tab]")?.dataset
                .settingsTab === target.tabId)) ||
            text(element) === (target.tab ?? target.label)),
      );
      if (tab && tab.getAttribute("aria-selected") !== "true") {
        if (pendingTab !== tab) {
          pendingTab = tab;
          tab.click();
        }
        return;
      }
      const fieldSelector =
        "h2,h3,h4,strong,label,button,span,dt,[aria-label],[role='tab'],[class*='spark-title'],[class*='card-head-title']";
      const hiddenField =
        stableTarget ??
        (!target.targetId ? find(fieldSelector, sameLabel) : undefined);
      const disclosures: HTMLElement[] = [];
      for (
        let ancestor: HTMLElement | null | undefined = hiddenField;
        ancestor && ancestor !== root;
        ancestor = ancestor.parentElement
      ) {
        if (ancestor.matches(".ant-collapse-item,.qwenpaw-collapse-item"))
          disclosures.unshift(ancestor);
        if (ancestor.id && !visible(ancestor)) {
          const toggle = find(
            'button[aria-controls][aria-expanded="false"]',
            (button) =>
              button.getAttribute("aria-controls") === ancestor!.id &&
              visible(button),
          );
          if (toggle) {
            toggle.click();
            return;
          }
        }
      }
      for (const disclosure of disclosures) {
        const toggle = disclosure.querySelector<HTMLElement>(
          ':scope > [role="button"][aria-expanded="false"]',
        );
        if (toggle && visible(toggle)) {
          toggle.click();
          return;
        }
      }
      const match = target.targetId
        ? stableTarget && visible(stableTarget)
          ? stableTarget
          : undefined
        : find(
            fieldSelector,
            (element) => sameLabel(element) && visible(element),
          );
      const destination = match ?? section;
      if (!destination) return;
      highlighted =
        destination.closest<HTMLElement>(
          "[data-setting-block],.ant-form-item,.qwenpaw-form-item",
        ) ?? destination;
      highlighted.setAttribute("data-search-highlight", "true");
      cancelAnimationFrame(scrollFrame);
      scrollFrame = requestAnimationFrame(() => {
        scrollFrame = 0;
        highlighted?.scrollIntoView({ block: "center", behavior: "instant" });
      });
    };
    const observer = new MutationObserver(() => {
      if (
        frame ||
        (highlighted?.isConnected &&
          highlighted.hasAttribute("data-search-highlight"))
      )
        return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        locate();
      });
    });
    observer.observe(root, {
      childList: true,
      subtree: true,
      attributes: true,
    });
    locate();
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
      cancelAnimationFrame(scrollFrame);
      highlighted?.removeAttribute("data-search-highlight");
    };
  }, [container, target, activePage]);
}

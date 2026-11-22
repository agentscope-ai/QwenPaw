const REVERSE_MESSAGE_SCROLL_SELECTOR =
  '[class*="chat-anywhere-message-list-bubble-scroll"]' +
  '[class*="bubble-list-order-desc"]';

const LINE_HEIGHT_PX = 16;
const SCROLL_TOLERANCE_PX = 1;

export function enableMessageScrollerKeyboardFocus(
  root: HTMLElement,
  label: string,
): () => void {
  let scroller: HTMLElement | null = null;
  let restore: (() => void) | undefined;
  const bindScroller = () => {
    if (scroller && root.contains(scroller)) return;
    restore?.();
    const target = root.querySelector<HTMLElement>(
      REVERSE_MESSAGE_SCROLL_SELECTOR,
    );
    scroller = target;
    if (!target) return;

    const attributes = [
      ["tabindex", "0"],
      ["role", "region"],
      ["aria-label", label],
    ].filter(([name]) => !target.hasAttribute(name));
    for (const [name, value] of attributes) target.setAttribute(name, value);
    restore = () => {
      for (const [name, value] of attributes) {
        if (target.getAttribute(name) === value) target.removeAttribute(name);
      }
    };
  };
  bindScroller();
  const observer = new MutationObserver(bindScroller);
  observer.observe(root, { childList: true, subtree: true });
  return () => {
    observer.disconnect();
    restore?.();
  };
}

function wheelDeltaInPixels(
  deltaY: number,
  deltaMode: number,
  clientHeight: number,
): number {
  if (deltaMode === 1) return deltaY * LINE_HEIGHT_PX;
  if (deltaMode === 2) return deltaY * clientHeight;
  return deltaY;
}

export function getNextReverseScrollTop(
  scrollTop: number,
  scrollHeight: number,
  clientHeight: number,
  deltaY: number,
  deltaMode: number,
): number {
  const maxScrollDistance = Math.max(scrollHeight - clientHeight, 0);
  const pixelDelta = wheelDeltaInPixels(deltaY, deltaMode, clientHeight);

  return Math.min(0, Math.max(-maxScrollDistance, scrollTop + pixelDelta));
}

function canConsumeVerticalWheel(
  element: HTMLElement,
  deltaY: number,
): boolean {
  const maxScrollTop = element.scrollHeight - element.clientHeight;
  if (maxScrollTop <= SCROLL_TOLERANCE_PX) return false;

  // Most ancestors inside a message cannot scroll. Check their inexpensive
  // geometry first so the wheel hot path does not force style resolution for
  // every nested Markdown node.
  const overflowY = window.getComputedStyle(element).overflowY;
  if (overflowY !== "auto" && overflowY !== "scroll") return false;

  if (deltaY < 0) return element.scrollTop > SCROLL_TOLERANCE_PX;
  return element.scrollTop < maxScrollTop - SCROLL_TOLERANCE_PX;
}

function hasScrollableChildBeforeScroller(
  target: Element,
  scroller: HTMLElement,
  deltaY: number,
): boolean {
  let current: HTMLElement | null =
    target instanceof HTMLElement ? target : target.parentElement;

  while (current && current !== scroller) {
    if (canConsumeVerticalWheel(current, deltaY)) return true;
    current = current.parentElement;
  }

  return false;
}

export function scrollReverseMessageList(
  root: HTMLElement,
  target: EventTarget | null,
  deltaY: number,
  deltaMode: number,
): boolean {
  if (!(target instanceof Element) || deltaY === 0) return false;

  const scroller = target.closest<HTMLElement>(REVERSE_MESSAGE_SCROLL_SELECTOR);
  if (!scroller || !root.contains(scroller)) return false;
  if (hasScrollableChildBeforeScroller(target, scroller, deltaY)) return false;

  const nextScrollTop = getNextReverseScrollTop(
    scroller.scrollTop,
    scroller.scrollHeight,
    scroller.clientHeight,
    deltaY,
    deltaMode,
  );
  if (nextScrollTop === scroller.scrollTop) return false;

  scroller.scrollTop = nextScrollTop;
  return true;
}

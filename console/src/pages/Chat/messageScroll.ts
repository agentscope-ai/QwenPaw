const REVERSE_MESSAGE_SCROLL_SELECTOR =
  '[class*="chat-anywhere-message-list-bubble-scroll"]' +
  '[class*="bubble-list-order-desc"]';

const LINE_HEIGHT_PX = 16;
const SCROLL_TOLERANCE_PX = 1;
const BOTTOM_TOLERANCE_PX = 2;
const SCROLL_TO_LATEST_EVENT = "qwenpaw:chat-scroll-to-latest";

function clampReverseScroll(scroller: HTMLElement, scrollTop: number): number {
  return Math.min(
    0,
    Math.max(scroller.clientHeight - scroller.scrollHeight, scrollTop),
  );
}

function readViewport(scroller: HTMLElement) {
  const scrollTop = scroller.scrollTop;
  if (scrollTop >= -BOTTOM_TOLERANCE_PX) return { scrollTop };

  const { children } = scroller;
  const { top, bottom } = scroller.getBoundingClientRect();
  // Children run newest-first. Find the oldest one that crosses the
  // viewport's top edge without measuring every offscreen bubble.
  let low = 0;
  let high = children.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (children[middle].getBoundingClientRect().bottom > top) low = middle + 1;
    else high = middle;
  }
  for (let i = low - 1; i >= 0; i--) {
    const child = children[i];
    const rect = child.getBoundingClientRect();
    if (rect.top >= bottom) break;
    if (child.id && child.hasAttribute("data-role")) {
      return { scrollTop, anchor: { id: child.id, offset: rect.top - top } };
    }
  }
  return { scrollTop };
}

function observeViewport(scroller: HTMLElement) {
  let viewport = readViewport(scroller);
  const restore = () => {
    if (!scroller.clientHeight) return;
    const { anchor, scrollTop } = viewport;
    const element = anchor && scroller.children.namedItem(anchor.id);
    let next = anchor ? 0 : scrollTop;
    if (scrollTop >= -BOTTOM_TOLERANCE_PX) {
      next = 0;
    } else if (anchor && element) {
      const rect = element.getBoundingClientRect();
      // If the part the reader was looking at collapsed, show the message
      // from its start instead of leaving it entirely above the viewport.
      const offset = anchor.offset <= -rect.height ? 0 : anchor.offset;
      next =
        scroller.scrollTop +
        rect.top -
        scroller.getBoundingClientRect().top -
        offset;
    }
    next = clampReverseScroll(scroller, next);
    if (Math.abs(next - scroller.scrollTop) > SCROLL_TOLERANCE_PX) {
      scroller.scrollTop = next;
    }
    viewport = readViewport(scroller);
  };

  const handleScroll = () => {
    const previousTop = viewport.scrollTop;
    const clampedTop = clampReverseScroll(scroller, previousTop);
    if (
      previousTop < clampedTop &&
      Math.abs(scroller.scrollTop - clampedTop) <= SCROLL_TOLERANCE_PX
    ) {
      // Resize-induced clamping can emit scroll before ResizeObserver.
      restore();
    } else {
      viewport = readViewport(scroller);
    }
  };

  // The SDK is about to swap the history window. Do not restore the old
  // anchor before the browser dispatches its asynchronous scroll event.
  const followLatest = () => {
    viewport = { scrollTop: 0 };
  };
  const resizeObserver = new ResizeObserver(restore);
  const updateChildren = () => {
    restore();
    resizeObserver.disconnect();
    resizeObserver.observe(scroller);
    for (const child of scroller.children) resizeObserver.observe(child);
  };
  scroller.addEventListener("scroll", handleScroll, { passive: true });
  scroller.addEventListener(SCROLL_TO_LATEST_EVENT, followLatest);
  updateChildren();
  return {
    updateChildren,
    disconnect() {
      resizeObserver.disconnect();
      scroller.removeEventListener("scroll", handleScroll);
      scroller.removeEventListener(SCROLL_TO_LATEST_EVENT, followLatest);
    },
  };
}

export function preserveReverseMessageViewport(root: HTMLElement): () => void {
  let scroller: HTMLElement | null = null;
  let viewport: ReturnType<typeof observeViewport> | undefined;
  const bind = () => {
    viewport?.disconnect();
    scroller = root.querySelector<HTMLElement>(REVERSE_MESSAGE_SCROLL_SELECTOR);
    viewport = scroller ? observeViewport(scroller) : undefined;
  };
  const observer = new MutationObserver((mutations) => {
    if (!scroller || !root.contains(scroller)) bind();
    else if (mutations.some(({ target }) => target === scroller)) {
      viewport?.updateChildren();
    }
  });
  observer.observe(root, { childList: true, subtree: true });
  bind();
  return () => {
    observer.disconnect();
    viewport?.disconnect();
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

const REVERSE_MESSAGE_SCROLL_SELECTOR =
  '[class*="chat-anywhere-message-list-bubble-scroll"]' +
  '[class*="bubble-list-order-desc"]';

const LINE_HEIGHT_PX = 16;
const SCROLL_TOLERANCE_PX = 1;

export interface MessageScrollAnchor {
  id: string;
  offsetTop: number;
}

export function isOldestLoadedMessageVisible(
  scroller: HTMLElement,
  message: HTMLElement | null,
  tolerance = SCROLL_TOLERANCE_PX,
): boolean {
  if (!message || !scroller.contains(message)) return false;

  const scrollerRect = scroller.getBoundingClientRect();
  const messageRect = message.getBoundingClientRect();
  return (
    messageRect.bottom >= scrollerRect.top - tolerance &&
    messageRect.top <= scrollerRect.bottom + tolerance
  );
}

export function captureMessageScrollAnchor(
  scroller: HTMLElement,
): MessageScrollAnchor | null {
  const scrollerRect = scroller.getBoundingClientRect();
  const visible = Array.from(
    scroller.querySelectorAll<HTMLElement>("[id][data-role]"),
  )
    .filter((element) => {
      const rect = element.getBoundingClientRect();
      return rect.bottom > scrollerRect.top && rect.top < scrollerRect.bottom;
    })
    .sort(
      (left, right) =>
        left.getBoundingClientRect().top - right.getBoundingClientRect().top,
    );
  const anchor = visible[0];
  if (!anchor) return null;
  return {
    id: anchor.id,
    offsetTop: anchor.getBoundingClientRect().top - scrollerRect.top,
  };
}

export function restoreMessageScrollAnchor(
  scroller: HTMLElement,
  anchor: MessageScrollAnchor,
): boolean {
  const element = document.getElementById(anchor.id);
  if (!element || !scroller.contains(element)) return false;
  const offsetTop =
    element.getBoundingClientRect().top - scroller.getBoundingClientRect().top;
  scroller.scrollTop += offsetTop - anchor.offsetTop;
  return true;
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

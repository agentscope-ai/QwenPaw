export const BOTTOM_THRESHOLD_PX = 24;

export function distanceFromBottom(scroll: HTMLElement): number {
  return scroll.className.includes("bubble-list-order-desc")
    ? Math.max(0, -scroll.scrollTop)
    : Math.max(0, scroll.scrollHeight - scroll.clientHeight - scroll.scrollTop);
}

/** Own live following independently of SDK message insertion effects. */
export function attachBottomFollow(
  scroll: HTMLElement,
  onDistance: (away: boolean) => void,
) {
  let following = true;
  let savedTop = scroll.scrollTop;
  let manualUntil = 0;
  let pointerDown = false;
  let frame = 0;
  let disposed = false;
  const bottom = () => {
    scroll.scrollTop = scroll.className.includes("bubble-list-order-desc")
      ? 0
      : Math.max(0, scroll.scrollHeight - scroll.clientHeight);
    savedTop = scroll.scrollTop;
    onDistance(false);
  };
  const reconcile = () => {
    frame = 0;
    if (disposed) return;
    if (following) bottom();
    else onDistance(distanceFromBottom(scroll) > BOTTOM_THRESHOLD_PX);
  };
  const schedule = () => {
    if (!frame) frame = requestAnimationFrame(reconcile);
  };
  const input = () => {
    manualUntil = performance.now() + 250;
    // Pause before the browser applies the gesture. Its scroll event decides
    // whether the reader has actually left the 24px bottom zone.
    following = false;
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      frame = 0;
      onScroll();
    });
  };
  const onScroll = () => {
    const distance = distanceFromBottom(scroll);
    if (pointerDown || performance.now() < manualUntil) {
      following = distance <= BOTTOM_THRESHOLD_PX;
      savedTop = scroll.scrollTop;
    } else if (
      !following &&
      distance <= BOTTOM_THRESHOLD_PX &&
      savedTop !== scroll.scrollTop
    ) {
      // The SDK may force the newest edge when a response card is inserted.
      // A detached reader must retain their position instead.
      scroll.scrollTop = savedTop;
      return;
    } else if (!following) {
      savedTop = scroll.scrollTop;
    }
    onDistance(!following && distanceFromBottom(scroll) > BOTTOM_THRESHOLD_PX);
  };
  const pointerStart = () => {
    pointerDown = true;
    input();
  };
  const pointerEnd = () => {
    pointerDown = false;
    manualUntil = performance.now() + 250;
  };
  const navigate = () => {
    following = false;
    manualUntil = 0;
    savedTop = scroll.scrollTop;
    onScroll();
  };
  const resize = new ResizeObserver(schedule);
  const observeChildren = () => {
    resize.disconnect();
    resize.observe(scroll);
    Array.from(scroll.children).forEach((child) => resize.observe(child));
    schedule();
  };
  const mutations = new MutationObserver((records) => {
    if (records.some((record) => record.target === scroll)) observeChildren();
    else schedule();
  });
  mutations.observe(scroll, {
    childList: true,
    subtree: true,
    characterData: true,
  });
  scroll.addEventListener("scroll", onScroll);
  scroll.addEventListener("wheel", input, { passive: true });
  scroll.addEventListener("touchmove", input, { passive: true });
  scroll.addEventListener("pointerdown", pointerStart);
  document.addEventListener("pointerup", pointerEnd);
  document.addEventListener("pointercancel", pointerEnd);
  scroll.addEventListener("keydown", input);
  scroll.addEventListener("chat-history-navigated", navigate);
  observeChildren();
  bottom();
  return {
    resume() {
      following = true;
      manualUntil = 0;
      bottom();
      schedule();
    },
    dispose() {
      disposed = true;
      cancelAnimationFrame(frame);
      resize.disconnect();
      mutations.disconnect();
      scroll.removeEventListener("scroll", onScroll);
      scroll.removeEventListener("wheel", input);
      scroll.removeEventListener("touchmove", input);
      scroll.removeEventListener("pointerdown", pointerStart);
      document.removeEventListener("pointerup", pointerEnd);
      document.removeEventListener("pointercancel", pointerEnd);
      scroll.removeEventListener("keydown", input);
      scroll.removeEventListener("chat-history-navigated", navigate);
    },
  };
}

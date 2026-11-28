/** Follow initial layout changes only until the user takes control. */
export function followInitialHistoryPosition(
  scroll: HTMLElement,
  position: () => void,
): () => void {
  const surface =
    scroll.closest<HTMLElement>(".qwenpaw-chat-anywhere-layout-right") ??
    scroll;
  let active = true;
  const align = () => {
    if (active && scroll.clientHeight > 0) {
      position();
    }
  };
  const stop = () => {
    active = false;
    observer?.disconnect();
    surface.removeEventListener("wheel", stop, true);
    surface.removeEventListener("pointerdown", stop, true);
    surface.removeEventListener("touchstart", stop, true);
    surface.removeEventListener("keydown", stop, true);
    scroll.removeEventListener("chat-message-window-rendered", align);
    scroll.removeEventListener("chat-history-navigated", stop);
  };
  const observer =
    typeof ResizeObserver === "undefined" ? null : new ResizeObserver(align);
  observer?.observe(scroll);
  if (scroll.firstElementChild) observer?.observe(scroll.firstElementChild);
  surface.addEventListener("wheel", stop, { capture: true, passive: true });
  surface.addEventListener("pointerdown", stop, true);
  surface.addEventListener("touchstart", stop, {
    capture: true,
    passive: true,
  });
  surface.addEventListener("keydown", stop, true);
  scroll.addEventListener("chat-message-window-rendered", align);
  scroll.addEventListener("chat-history-navigated", stop);
  align();
  return stop;
}

export function followInitialHistoryBottom(scroll: HTMLElement): () => void {
  return followInitialHistoryPosition(scroll, () => {
    scroll.scrollTop = scroll.scrollHeight;
  });
}

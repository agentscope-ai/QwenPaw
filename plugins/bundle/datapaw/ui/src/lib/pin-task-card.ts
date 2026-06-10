import { TASK_GRAPH_MESSAGE_ID } from "./task-card-storage";

/** DOM marker on the task graph card root (TaskGraphPanel wrapper). */
export const TASK_GRAPH_CARD_ATTR = "data-datapaw-task-graph-card";

/** Applied to the chat message row that contains the task card (sticky at stream bottom). */
export const TASK_GRAPH_MESSAGE_ATTR = "data-datapaw-task-graph-message";

export function isTaskGraphMessageId(id: unknown): boolean {
  return (
    typeof id === "string" &&
    (id === TASK_GRAPH_MESSAGE_ID || id.startsWith("task_graph_"))
  );
}

export type TaskCardMessagesApi = {
  getMessages?: () => Array<{ id?: string }>;
  getMessage?: (id: string) => Record<string, unknown>;
  removeMessage?: (msg: { id: string }) => void;
  updateMessage?: (msg: Record<string, unknown> & { id: string }) => void;
};

function findBubbleListAnchor(): HTMLElement | null {
  const selectors = [
    ".qwenpaw-chat-anywhere-message-list .qwenpaw-bubble-list",
    '[class*="chat-anywhere-message-list"] [class*="bubble-list"]',
    ".qwenpaw-bubble-list",
    '[class*="bubble-list"]',
  ];
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el instanceof HTMLElement) return el;
  }
  return null;
}

/** Move the task card message row to the end of the bubble list (chat stream bottom). */
export function pinTaskCardDomToBottom(): boolean {
  const bubbleList = findBubbleListAnchor();
  if (!bubbleList) return false;

  const cardEl = bubbleList.querySelector(`[${TASK_GRAPH_CARD_ATTR}]`);
  if (!cardEl) return false;

  const messageItem =
    cardEl.closest('[class*="bubble-item"]') ??
    cardEl.closest('[class*="message-item"]');
  if (!(messageItem instanceof HTMLElement)) return false;

  if (bubbleList.lastElementChild !== messageItem) {
    bubbleList.appendChild(messageItem);
  }
  messageItem.setAttribute(TASK_GRAPH_MESSAGE_ATTR, "true");
  return true;
}

export function schedulePinTaskCardDomToBottom(): void {
  if (typeof window === "undefined") return;
  window.requestAnimationFrame(() => {
    pinTaskCardDomToBottom();
    window.requestAnimationFrame(pinTaskCardDomToBottom);
  });
}

/** DOM pin only — never reorder via removeMessage + updateMessage. */
export function pinTaskCardToBottom(
  _messagesApi?: TaskCardMessagesApi | null | undefined,
): void {
  pinTaskCardDomToBottom();
}

let bottomPinObserver: MutationObserver | null = null;
let bottomPinDebounce = 0;
let streamPinTimer: ReturnType<typeof setTimeout> | null = null;

export function schedulePinTaskCardDuringStream(): void {
  if (streamPinTimer) return;
  streamPinTimer = window.setTimeout(() => {
    streamPinTimer = null;
    schedulePinTaskCardDomToBottom();
  }, 250);
}

export function installTaskCardBottomPin(
  getMessagesApi: () => TaskCardMessagesApi | null | undefined,
): () => void {
  const schedulePin = () => {
    window.clearTimeout(bottomPinDebounce);
    bottomPinDebounce = window.setTimeout(() => {
      pinTaskCardToBottom(getMessagesApi());
    }, 80);
  };

  const attachObserver = (): boolean => {
    if (bottomPinObserver) return true;
    const anchor = findBubbleListAnchor();
    if (!anchor) return false;
    bottomPinObserver = new MutationObserver(schedulePin);
    bottomPinObserver.observe(anchor, { childList: true, subtree: true });
    return true;
  };

  schedulePin();

  if (!attachObserver()) {
    let attempts = 0;
    const timer = window.setInterval(() => {
      attempts += 1;
      if (attachObserver() || attempts >= 100) {
        window.clearInterval(timer);
      }
    }, 200);
  }

  return () => {
    window.clearTimeout(bottomPinDebounce);
    bottomPinObserver?.disconnect();
    bottomPinObserver = null;
  };
}

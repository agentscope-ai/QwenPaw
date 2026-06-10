const PIN_STYLE_ID = "datapaw-task-card-pin-style";

/** DOM marker on the task graph card root (TaskGraphPanel wrapper). */
export const TASK_GRAPH_CARD_ATTR = "data-datapaw-task-graph-card";

/** Sticky row marker at the bottom of the chat message stream. */
export const TASK_GRAPH_MESSAGE_ATTR = "data-datapaw-task-graph-message";

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

function injectPinStyles(): void {
  if (typeof document === "undefined") return;
  if (document.getElementById(PIN_STYLE_ID)) return;

  const style = document.createElement("style");
  style.id = PIN_STYLE_ID;
  style.textContent = `
[${TASK_GRAPH_CARD_ATTR}] {
  width: 100%;
}
`;
  document.head.appendChild(style);
}

/** Move task card row to the end of the scrollable bubble list. */
export function pinTaskCardDomToBottom(): boolean {
  injectPinStyles();
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

export function pinTaskCardToBottom(
  _messagesApi?: TaskCardMessagesApi | null | undefined,
): void {
  pinTaskCardDomToBottom();
}

let bottomPinObserver: MutationObserver | null = null;
let bottomPinDebounce = 0;
let bottomPinRefCount = 0;
let streamPinTimer: ReturnType<typeof setTimeout> | null = null;
let bootstrapStarted = false;
let domObserversAttached = false;

export function schedulePinTaskCardDuringStream(): void {
  if (streamPinTimer) return;
  streamPinTimer = window.setTimeout(() => {
    streamPinTimer = null;
    schedulePinTaskCardDomToBottom();
  }, 200);
}

function getHostMessagesApi(): TaskCardMessagesApi | null | undefined {
  const bridge = (
    window as {
      QwenPaw?: {
        host?: {
          chatBridge?: {
            _ref?: { current?: { messages?: TaskCardMessagesApi } };
          };
        };
      };
    }
  ).QwenPaw?.host?.chatBridge;

  const ref = bridge?._ref;
  return ref?.current?.messages ?? undefined;
}

export function bootstrapTaskCardBottomPin(): void {
  if (bootstrapStarted || typeof window === "undefined") return;
  bootstrapStarted = true;

  injectPinStyles();

  installTaskCardBottomPin(() => getHostMessagesApi());

  let attempts = 0;
  const timer = window.setInterval(() => {
    attempts += 1;
    pinTaskCardDomToBottom();
    if (attempts >= 40) window.clearInterval(timer);
  }, 250);
}

export function installTaskCardBottomPin(
  getMessagesApi: () => TaskCardMessagesApi | null | undefined,
): () => void {
  bottomPinRefCount += 1;

  const schedulePin = () => {
    window.clearTimeout(bottomPinDebounce);
    bottomPinDebounce = window.setTimeout(() => {
      pinTaskCardToBottom(getMessagesApi());
    }, 80);
  };

  const attachObservers = (): boolean => {
    if (domObserversAttached) return true;

    const bubbleList = findBubbleListAnchor();
    if (!bubbleList) return false;

    bottomPinObserver = new MutationObserver(schedulePin);
    bottomPinObserver.observe(bubbleList, { childList: true, subtree: true });
    domObserversAttached = true;
    return true;
  };

  schedulePin();

  if (!attachObservers()) {
    let attempts = 0;
    const timer = window.setInterval(() => {
      attempts += 1;
      if (attachObservers() || attempts >= 100) {
        window.clearInterval(timer);
      }
    }, 200);
  }

  return () => {
    bottomPinRefCount = Math.max(0, bottomPinRefCount - 1);
    if (bottomPinRefCount > 0) return;
    window.clearTimeout(bottomPinDebounce);
    bottomPinObserver?.disconnect();
    bottomPinObserver = null;
    domObserversAttached = false;
  };
}

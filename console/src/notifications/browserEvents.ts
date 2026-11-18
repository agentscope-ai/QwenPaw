import type { SystemNotificationEvent } from "./notificationEvents";
import { shouldNotifyEvent } from "./notificationEvents";
import { getNotificationPreferences } from "./preferences";

const SENT_KEY = "qwenpaw.systemNotifications.sent";
const LOCK = "qwenpaw:system-notifications";

/** Only new snapshots notify; disabled or foreground events are not replayed. */
export class BrowserEventNotifier {
  private seeded = false;
  private known = new Set<string>();
  private disposed = false;
  private active = new Set<Notification>();
  private conversationTitle: () => string;
  private open: (event: SystemNotificationEvent) => void;

  constructor(
    conversationTitle: () => string,
    open: (event: SystemNotificationEvent) => void,
  ) {
    this.conversationTitle = conversationTitle;
    this.open = open;
  }

  update(events: SystemNotificationEvent[]): void {
    const fresh = this.seeded
      ? events.filter((event) => !this.known.has(event.id))
      : [];
    this.seeded = true;
    this.known = new Set(
      [...this.known, ...events.map((event) => event.id)].slice(-1000),
    );
    for (const event of fresh) {
      if (
        !shouldNotifyEvent(
          event,
          getNotificationPreferences(),
          document.hidden || !document.hasFocus(),
        )
      )
        continue;
      const send = () => this.send(event);
      void (
        navigator.locks
          ? navigator.locks.request(LOCK, send)
          : Promise.resolve().then(send)
      ).catch((error: unknown) => {
        this.known.delete(event.id);
        console.warn("Could not show system notification", error);
      });
    }
  }

  private send(event: SystemNotificationEvent): void {
    if (
      this.disposed ||
      typeof window.Notification !== "function" ||
      Notification.permission !== "granted" ||
      !shouldNotifyEvent(
        event,
        getNotificationPreferences(),
        document.hidden || !document.hasFocus(),
      )
    )
      return;
    let sent: Record<string, number> = {};
    try {
      const parsed: unknown = JSON.parse(
        localStorage.getItem(SENT_KEY) || "{}",
      );
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed))
        sent = parsed as Record<string, number>;
    } catch {
      /* Ignore an invalid deduplication cache. */
    }
    if (sent[event.id] > Date.now()) return;
    const notification = new Notification(
      event.category === "conversation"
        ? this.conversationTitle()
        : event.title,
      { body: event.body, tag: `qwenpaw-event:${event.id}` },
    );
    this.active.add(notification);
    notification.onclick = () => {
      window.focus();
      this.open(event);
      notification.close();
    };
    notification.onclose = () => this.active.delete(notification);
    sent = Object.fromEntries(
      Object.entries(sent)
        .filter(([, until]) => until > Date.now())
        .slice(-499),
    );
    sent[event.id] = Date.now() + 300_000;
    try {
      localStorage.setItem(SENT_KEY, JSON.stringify(sent));
    } catch {
      /* Already displayed. */
    }
  }

  closeAll(): void {
    for (const notification of this.active) notification.close();
    this.active.clear();
  }

  dispose(): void {
    this.disposed = true;
    this.closeAll();
  }
}

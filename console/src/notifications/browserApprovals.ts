import type { PendingApproval } from "../api/modules/console";
import { notificationsEnabled } from "./preferences";

const SENT_KEY = "qwenpaw.approvalNotifications.sent";
const LOCK_NAME = "qwenpaw:approval-notifications";

export function approvalExpiresAt(approval: PendingApproval): number {
  return (approval.created_at + approval.timeout_seconds) * 1000;
}

/** A snapshot consumer; the first successful snapshot only seeds known IDs. */
export class BrowserApprovalNotifier {
  private seeded = false;
  private known = new Set<string>();
  private pending = new Map<string, PendingApproval>();
  private delivering = new Set<string>();
  private active = new Map<
    string,
    { notification: Notification; timer: ReturnType<typeof setTimeout> }
  >();
  private disposed = false;
  private text: () => { title: string; body: (tool: string) => string };
  private openApproval: (approval: PendingApproval) => void;

  constructor(
    text: () => { title: string; body: (tool: string) => string },
    openApproval: (approval: PendingApproval) => void,
  ) {
    this.text = text;
    this.openApproval = openApproval;
    document.addEventListener("visibilitychange", this.reconsider);
    window.addEventListener("blur", this.reconsider);
  }

  update(approvals: PendingApproval[]): void {
    this.pending = new Map(
      approvals
        .filter((a) => approvalExpiresAt(a) > Date.now())
        .map((a) => [a.request_id, a]),
    );
    for (const id of this.active.keys()) {
      if (!this.pending.has(id)) this.close(id);
    }
    this.known.forEach((id) => {
      if (!this.pending.has(id)) this.known.delete(id);
    });
    if (!this.seeded) {
      this.seeded = true;
      this.known = new Set(this.pending.keys());
      return;
    }
    this.notifyPending();
  }

  reconsider = (): void => {
    if (this.seeded) this.notifyPending();
  };

  private notifyPending(): void {
    const fresh = [...this.pending.values()].filter(
      (approval) =>
        !this.known.has(approval.request_id) &&
        !this.delivering.has(approval.request_id),
    );
    for (const approval of fresh) {
      this.delivering.add(approval.request_id);
      let retry = false;
      const send = () => this.send(approval);
      const delivery = navigator.locks
        ? navigator.locks.request(LOCK_NAME, send)
        : Promise.resolve().then(send);
      void delivery
        .then((shown) => {
          if (shown) this.known.add(approval.request_id);
          else retry = this.canAttempt(approval);
        })
        .catch((error: unknown) => {
          console.warn("Could not show approval notification", error);
        })
        .finally(() => {
          this.delivering.delete(approval.request_id);
          if (retry && this.pending.has(approval.request_id)) {
            this.notifyPending();
          }
        });
    }
  }

  closeAll(): void {
    for (const id of this.active.keys()) this.close(id);
  }

  dispose(): void {
    this.disposed = true;
    document.removeEventListener("visibilitychange", this.reconsider);
    window.removeEventListener("blur", this.reconsider);
    this.closeAll();
  }

  private close(id: string): void {
    const item = this.active.get(id);
    if (!item) return;
    this.active.delete(id);
    clearTimeout(item.timer);
    item.notification.close();
  }

  private canNotify(): boolean {
    return (
      !this.disposed &&
      notificationsEnabled() &&
      typeof window.Notification === "function" &&
      Notification.permission === "granted" &&
      (document.hidden || !document.hasFocus())
    );
  }

  private canAttempt(approval: PendingApproval): boolean {
    return (
      this.canNotify() &&
      this.pending.has(approval.request_id) &&
      approvalExpiresAt(approval) > Date.now()
    );
  }

  private send(approval: PendingApproval): boolean {
    if (!this.canAttempt(approval)) return false;
    let sent: Record<string, number> = {};
    try {
      sent = JSON.parse(localStorage.getItem(SENT_KEY) || "{}");
      if (!sent || typeof sent !== "object" || Array.isArray(sent)) sent = {};
    } catch {
      // An invalid cache must not prevent a new approval from notifying.
    }
    if (sent[approval.request_id] > Date.now()) return true;
    const { title, body } = this.text();
    const notification = new Notification(title, {
      body: body(approval.tool_display_name || approval.tool_name),
      tag: `qwenpaw-approval:${approval.request_id}`,
    });
    notification.onclick = () => {
      window.focus();
      this.openApproval(approval);
      this.close(approval.request_id);
    };
    notification.onclose = () => this.close(approval.request_id);
    this.active.set(approval.request_id, {
      notification,
      timer: setTimeout(
        () => this.close(approval.request_id),
        approvalExpiresAt(approval) - Date.now(),
      ),
    });
    sent = Object.fromEntries(
      Object.entries(sent)
        .filter(([, expires]) => expires > Date.now())
        .slice(-499),
    );
    sent[approval.request_id] = approvalExpiresAt(approval);
    try {
      localStorage.setItem(SENT_KEY, JSON.stringify(sent));
    } catch {
      // The notification is already visible; do not risk showing it twice.
    }
    return true;
  }
}

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
    const fresh = [...this.pending.values()].filter(
      (a) => !this.known.has(a.request_id),
    );
    this.known = new Set(this.pending.keys());
    if (!this.seeded) {
      this.seeded = true;
      return;
    }
    for (const approval of fresh) {
      const send = () => this.send(approval);
      const delivery = navigator.locks
        ? navigator.locks.request(LOCK_NAME, send)
        : Promise.resolve().then(send);
      void delivery.catch((error: unknown) => {
        console.warn("Could not show approval notification", error);
      });
    }
  }

  closeAll(): void {
    for (const id of this.active.keys()) this.close(id);
  }

  dispose(): void {
    this.disposed = true;
    this.closeAll();
  }

  private close(id: string): void {
    const item = this.active.get(id);
    if (!item) return;
    this.active.delete(id);
    clearTimeout(item.timer);
    item.notification.close();
  }

  private send(approval: PendingApproval): void {
    if (
      this.disposed ||
      !notificationsEnabled() ||
      typeof window.Notification !== "function" ||
      Notification.permission !== "granted" ||
      (!document.hidden && document.hasFocus()) ||
      !this.pending.has(approval.request_id) ||
      approvalExpiresAt(approval) <= Date.now()
    ) {
      return;
    }
    let sent: Record<string, number> = {};
    try {
      sent = JSON.parse(localStorage.getItem(SENT_KEY) || "{}");
      if (!sent || typeof sent !== "object" || Array.isArray(sent)) sent = {};
    } catch {
      // An invalid cache must not prevent a new approval from notifying.
    }
    if (sent[approval.request_id] > Date.now()) return;
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
    localStorage.setItem(SENT_KEY, JSON.stringify(sent));
  }
}

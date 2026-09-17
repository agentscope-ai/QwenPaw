/**
 * registry/audit.ts — single override log shared by all QwenPaw registries
 * (console-wide menu/route/slot + chat extensions).
 *
 * Ring buffer (default 500 entries). Plugin authors can read via
 * `window.QwenPaw.audit.overrides()` for debugging / change attribution.
 *
 * OverrideRecord carries two interchangeable id fields:
 *   - `targetId` — preferred by console-wide registries (menuId / routeId / slotName)
 *   - `field`    — preferred by chat-extension registries (scalar / list field name)
 * Either works; this store normalises printing so consumers see consistent output.
 */
import type { OverrideRecord } from "./types";

const DEFAULT_CAP = 500;

function idOf(rec: OverrideRecord): string {
  return rec.targetId ?? rec.field ?? "";
}

class AuditStore {
  private buf: OverrideRecord[] = [];
  private readonly cap: number;

  constructor(cap = DEFAULT_CAP) {
    this.cap = cap;
  }

  record(rec: OverrideRecord): void {
    this.buf.push(rec);
    if (this.buf.length > this.cap) {
      this.buf.splice(0, this.buf.length - this.cap);
    }
    const id = idOf(rec);
    if (
      rec.kind === "menu.conflict" ||
      rec.kind === "route.conflict" ||
      rec.kind === "slot.error" ||
      rec.kind === "chat.error"
    ) {
      console.warn(
        `[QwenPaw audit] ${rec.kind} ${id} by ${rec.pluginId}` +
          (rec.detail ? `: ${rec.detail}` : ""),
      );
    } else {
      console.info(
        `[QwenPaw audit] ${rec.kind} ${id} by ${rec.pluginId}` +
          (rec.supersededPluginId
            ? ` (superseded ${rec.supersededPluginId})`
            : ""),
      );
    }
  }

  /** Return a copy — callers can sort/filter without mutating internal state. */
  overrides(): OverrideRecord[] {
    return this.buf.slice();
  }

  clear(): void {
    this.buf = [];
  }
}

export const auditStore = new AuditStore();

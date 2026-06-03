/**
 * registry/audit.ts — single override log shared by Menu / Route / Slot registries.
 *
 * Ring buffer (default 500 entries). Plugin authors can read via
 * `window.QwenPaw.audit.overrides()` for debugging / change attribution.
 */
import type { OverrideRecord } from "./types";

const DEFAULT_CAP = 500;

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
    if (
      rec.kind === "menu.conflict" ||
      rec.kind === "route.conflict" ||
      rec.kind === "slot.error"
    ) {
      console.warn(
        `[QwenPaw audit] ${rec.kind} ${rec.targetId} by ${rec.pluginId}` +
          (rec.detail ? `: ${rec.detail}` : ""),
      );
    } else {
      console.info(
        `[QwenPaw audit] ${rec.kind} ${rec.targetId} by ${rec.pluginId}` +
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

/**
 * registry/audit.ts — unified override audit log.
 *
 * Ring buffer (default 500 entries). Both chatExtensionsRegistry and
 * PluginSlotBoundary push records here. Exposed to plugins as
 * `window.QwenPaw.audit.overrides()`.
 */
import type { OverrideRecord } from "./types";

const DEFAULT_CAP = 500;

class AuditStore {
  private buf: OverrideRecord[] = [];
  private cap: number;

  constructor(cap = DEFAULT_CAP) {
    this.cap = cap;
  }

  record(rec: OverrideRecord): void {
    this.buf.push(rec);
    if (this.buf.length > this.cap) {
      this.buf.splice(0, this.buf.length - this.cap);
    }
    if (rec.kind === "chat.error") {
      console.error(
        `[plugin:${rec.pluginId}] ${rec.kind} on ${rec.field}: ${rec.detail ?? ""}`,
      );
    } else {
      console.info(
        `[plugin:${rec.pluginId}] ${rec.kind} on ${rec.field}` +
          (rec.supersededPluginId ? ` (superseded ${rec.supersededPluginId})` : ""),
      );
    }
  }

  overrides(): OverrideRecord[] {
    return this.buf.slice();
  }

  clear(): void {
    this.buf = [];
  }
}

export const auditStore = new AuditStore();

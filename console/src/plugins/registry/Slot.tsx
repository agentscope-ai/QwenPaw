/**
 * registry/Slot.tsx — <Slot name kind children?> layout fill point.
 *
 * - kind="fill": renders `children` (host default) first, then all plugin fills
 *   sorted by topo + order. Multiple plugins compose.
 * - kind="replace": renders the latest plugin replace if any, else `children`.
 *
 * Every plugin-provided render is wrapped in <SlotErrorBoundary> so a single
 * crash logs to audit and degrades to null instead of taking down the whole
 * layout.
 */
import React from "react";
import { useSyncExternalStore } from "react";
import { slotRegistry, subscribe } from "./store";
import type { SlotKind, SlotName } from "./types";
import { auditStore } from "./audit";

interface SlotProps {
  name: SlotName;
  kind: SlotKind;
  /** Host's own content for this slot. Always rendered for fill, used as fallback for replace. */
  children?: React.ReactNode;
}

export function Slot({ name, kind, children }: SlotProps) {
  const entries = useSyncExternalStore(
    subscribe,
    () => slotRegistry.snapshot(name),
  );

  if (kind === "replace") {
    const replaceEntry = entries.find((e) => e.kind === "replace");
    if (!replaceEntry) return <>{children}</>;
    return (
      <SlotErrorBoundary slot={name} pluginId={replaceEntry.source}>
        {replaceEntry.render()}
      </SlotErrorBoundary>
    );
  }

  // fill mode
  const visibleFills = entries.filter((e) => e.kind === "fill");
  return (
    <>
      {children}
      {visibleFills.map((e) => (
        <SlotErrorBoundary
          key={e.registrationId}
          slot={name}
          pluginId={e.source}
        >
          {e.render()}
        </SlotErrorBoundary>
      ))}
    </>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// SlotErrorBoundary
// ─────────────────────────────────────────────────────────────────────────────

interface BoundaryProps {
  slot: string;
  pluginId: string;
  fallback?: React.ReactNode;
  children: React.ReactNode;
}

interface BoundaryState {
  errored: boolean;
}

export class SlotErrorBoundary extends React.Component<
  BoundaryProps,
  BoundaryState
> {
  state: BoundaryState = { errored: false };

  static getDerivedStateFromError(): BoundaryState {
    return { errored: true };
  }

  componentDidCatch(error: Error): void {
    auditStore.record({
      kind: "slot.error",
      targetId: this.props.slot,
      pluginId: this.props.pluginId,
      detail: error.message,
      timestamp: Date.now(),
    });
  }

  render(): React.ReactNode {
    if (this.state.errored) return this.props.fallback ?? null;
    return this.props.children;
  }
}

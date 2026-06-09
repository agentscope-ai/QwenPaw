/**
 * registry/PluginSlotBoundary.tsx — error boundary for plugin-contributed JSX.
 *
 * A plugin throwing inside its component should never tear down the host
 * Chat tree. This boundary catches the error, writes it to the audit log,
 * and renders an optional fallback (default: render nothing).
 */
import React from "react";
import { auditStore } from "./audit";

interface Props {
  pluginId: string;
  slot: string;
  fallback?: React.ReactNode;
  children: React.ReactNode;
}

interface State {
  errored: boolean;
}

export class PluginSlotBoundary extends React.Component<Props, State> {
  state: State = { errored: false };

  static getDerivedStateFromError(): State {
    return { errored: true };
  }

  componentDidCatch(error: Error): void {
    auditStore.record({
      kind: "chat.error",
      field: this.props.slot,
      pluginId: this.props.pluginId,
      detail: error.message,
      timestamp: Date.now(),
    });
  }

  render(): React.ReactNode {
    if (this.state.errored) {
      return this.props.fallback ?? null;
    }
    return this.props.children;
  }
}

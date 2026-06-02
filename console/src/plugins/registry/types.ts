/**
 * registry/types.ts — shared shapes for the chat extension registry.
 *
 * These types are the host-side ground truth. Plugin TS projects should
 * reference the ambient `Window.QwenPaw` declaration in `plugins/types/qwenpaw.d.ts`,
 * which intentionally exposes a stable subset and does NOT re-export
 * `@agentscope-ai/chat` vendor types.
 */
import type React from "react";

// ─────────────────────────────────────────────────────────────────────────────
// Disposable
// ─────────────────────────────────────────────────────────────────────────────

export interface Disposable {
  dispose(): void;
}

/** Combine multiple Disposables into one. */
export function combineDisposables(...d: Disposable[]): Disposable {
  return {
    dispose() {
      for (const it of d) {
        try {
          it.dispose();
        } catch (err) {
          console.warn("[QwenPaw] Disposable threw on dispose:", err);
        }
      }
    },
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Localized<T>
//   Accept either a raw value or a `(locale) => value` callback.
//   The registry stores the raw shape verbatim; the consumer (ChatPage useMemo)
//   resolves the function form using the active i18n locale.
// ─────────────────────────────────────────────────────────────────────────────

export type Localized<T> = T | ((locale: string) => T);

export function resolveLocalized<T>(value: Localized<T> | undefined, locale: string): T | undefined {
  if (value === undefined) return undefined;
  return typeof value === "function" ? (value as (l: string) => T)(locale) : value;
}

// ─────────────────────────────────────────────────────────────────────────────
// Chat scalar fields (last-writer-wins)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * SDK's welcome.render signature — receives the resolved welcome props plus
 * `onSubmit` and returns the entire welcome surface. Plugins may also pass a
 * plain `React.ReactNode`; install.ts wraps it into a fn before storage.
 */
export interface WelcomeRenderProps {
  greeting?: React.ReactNode;
  description?: React.ReactNode;
  avatar?: string | React.ReactNode;
  prompts?: Array<{ label?: React.ReactNode; value: string }>;
  onSubmit: (data: { query: string; fileList?: unknown[] }) => void;
}

export type WelcomeRenderFn = (props: WelcomeRenderProps) => React.ReactElement;

/**
 * Plugin-facing data shapes for request/response cards.
 * Kept loose (`unknown`-ish records) to avoid leaking vendor types — plugin
 * authors who want strong typing can cast inside their handlers.
 */
export type ChatRequestData = Record<string, unknown>;
export type ChatResponseData = Record<string, unknown>;

export type ChatRequestRenderFn = (ctx: {
  data: ChatRequestData;
  fallback: () => React.ReactElement;
}) => React.ReactNode;

export type ChatResponseRenderFn = (ctx: {
  data: ChatResponseData;
  isLast?: boolean;
  fallback: () => React.ReactElement;
}) => React.ReactNode;

export type ChatRequestSlotFn = (ctx: { data: ChatRequestData }) => React.ReactNode;
export type ChatResponseSlotFn = (ctx: {
  data: ChatResponseData;
  isLast?: boolean;
}) => React.ReactNode;

export interface ChatSlotItem<F> {
  id: string;
  render: F;
  order?: number;
}

export type { ChatScalarField, ChatListField } from "./slotKeys";
import type { ChatScalarField, ChatListField } from "./slotKeys";

export interface ChatScalarValues {
  "welcome.greeting"?: Localized<React.ReactNode>;
  "welcome.description"?: Localized<React.ReactNode>;
  "welcome.avatar"?: Localized<string | React.ReactNode>;
  "welcome.nick"?: Localized<string | React.ReactNode>;
  "welcome.prompts"?: Localized<Array<{ label?: React.ReactNode; value: string }>>;
  /** Whole-section override of the welcome panel. Wins over the partial fields above. */
  "welcome.render"?: WelcomeRenderFn;
  "header.leftTitle"?: Localized<React.ReactNode>;
  "header.leftLogo"?: Localized<string | React.ReactNode>;
  /** Whole-section override of theme.leftHeader. Wins over leftTitle/leftLogo. */
  "header.leftHeader.render"?: React.ReactNode;
  "theme.colorPrimary"?: string;
  "sender.placeholder"?: Localized<string>;
  "sender.disclaimer"?: Localized<React.ReactNode>;
  /** Whole-bubble replacement for user requests. Wins over additive prepend/append slots? No — slots always render. */
  "request.render"?: ChatRequestRenderFn;
  /** Whole-bubble replacement for assistant responses. */
  "response.render"?: ChatResponseRenderFn;
}

// ─────────────────────────────────────────────────────────────────────────────
// Chat list fields (additive)
// ─────────────────────────────────────────────────────────────────────────────

// ChatListField re-exported above from ./slotKeys

export interface ChatNodeItem {
  id: string;
  node: React.ReactNode;
  order?: number;
}

export interface ChatSuggestionsItem {
  id: string;
  items: Localized<Array<{ label?: React.ReactNode; value: string }>>;
}

/**
 * Loose shape matching `IAgentScopeRuntimeWebUIActionsOptions.list[number]`
 * but kept host-owned to avoid leaking the vendor type to plugins.
 */
export interface ChatActionSpec {
  id: string;
  icon?: React.ReactElement;
  /** Either `render` or `onClick`; `render` wins if both supplied (SDK behaviour). */
  render?: (ctx: { data: unknown }) => React.ReactElement;
  onClick?: (ctx: { data: unknown }) => void;
}

export interface ChatActionItem {
  id: string;
  pluginId: string;
  item: ChatActionSpec;
}

export interface ChatToolRendererItem {
  id: string;
  toolName: string;
  render: React.FC<{ result: unknown; sessionId: string; messageId: string } & Record<string, unknown>>;
}

export interface ChatCardItem {
  id: string;
  cardName: string;
  render: React.FC<Record<string, unknown>>;
}

// ─────────────────────────────────────────────────────────────────────────────
// Audit
// ─────────────────────────────────────────────────────────────────────────────

export type AuditKind =
  | "chat.scalar.set"
  | "chat.scalar.superseded"
  | "chat.scalar.dispose"
  | "chat.list.add"
  | "chat.list.dispose"
  | "chat.error";

export interface OverrideRecord {
  kind: AuditKind;
  field: ChatScalarField | ChatListField | string;
  pluginId: string;
  supersededPluginId?: string;
  /** Free-form details (error message, slot id, etc). */
  detail?: string;
  timestamp: number;
}

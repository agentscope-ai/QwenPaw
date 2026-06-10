/**
 * registry/types.ts — public shapes for the QwenPaw plugin extension registries.
 *
 * Three console-wide concepts:
 *   - Menu  → sidebar entries with location/parentId/before/after/order
 *   - Route → pages with add/replace/wrap
 *   - Slot  → named layout fill points (header.left, sider.bottom, …)
 *
 * Plus the chat-surface customization shapes consumed by chatExtensions:
 *   - Localized<T> for i18n-aware values
 *   - Welcome / Request / Response render + slot fn signatures
 *   - ChatScalarValues + supporting card/action item shapes
 *
 * Plugin-facing API surface lives in:
 *   - sdk.ts                  (console-wide: menu/route/slot/audit)
 *   - hostSdk/install.ts      (chat: chat.welcome/leftHeader/sender/...)
 *
 * Both surfaces share the single audit log in `./audit.ts`.
 */
import type React from "react";

// ─────────────────────────────────────────────────────────────────────────────
// Disposable
// ─────────────────────────────────────────────────────────────────────────────

export interface Disposable {
  dispose(): void;
}

/** Combine multiple Disposables into one. Errors per-dispose are swallowed + logged. */
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
// Localized<T> — accept either a raw value or a `(locale) => value` callback.
// The registry stores the raw shape verbatim; the consumer (ChatPage useMemo)
// resolves the function form using the active i18n locale.
// ─────────────────────────────────────────────────────────────────────────────

export type Localized<T> = T | ((locale: string) => T);

export function resolveLocalized<T>(
  value: Localized<T> | undefined,
  locale: string,
): T | undefined {
  if (value === undefined) return undefined;
  return typeof value === "function"
    ? (value as (l: string) => T)(locale)
    : value;
}

// ─────────────────────────────────────────────────────────────────────────────
// Menu (console-wide)
// ─────────────────────────────────────────────────────────────────────────────

export type MenuLocation =
  | "primary.agentScoped" // Sidebar Menu #1 (agent-bound entries: inbox, control, agent-group)
  | "primary.settings" //   Sidebar Menu #2 (global settings + plugins-group)
  | "userMenu"; //          Reserved for future avatar-dropdown items

export interface MenuItem {
  /** Globally unique id, e.g. "core.workspace" / "cloudpaw.a2a". */
  id: string;
  /** Which Sidebar bucket. Defaults to "primary.settings". */
  location?: MenuLocation;
  /**
   * If set, this item is a CHILD of the named parent (groups: "core.control-group",
   * "core.agent-group", "core.settings-group", "plugins-group", …).
   * Items without parentId render at top level within their location bucket.
   */
  parentId?: string;
  /** Relative-position constraint: render before the item with this id. */
  before?: string;
  /** Relative-position constraint: render after the item with this id. */
  after?: string;
  /** Numeric fallback when before/after can't disambiguate. Lower renders first. */
  order?: number;
  /**
   * Display label. String for static, function for i18n + dynamic decoration
   * (e.g. unread badge). Adapter wraps `null` returns in a Fragment.
   */
  label: string | (() => React.ReactNode);
  /**
   * Icon. ComponentType for SDK / lucide icons (rendered with size=16); ReactNode for
   * plain emoji/img. We accept `ComponentType<any>` to allow any icon library
   * (Spark, lucide, antd) whose props accept a `size` field even if typed loosely.
   */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  icon?: React.ComponentType<any> | React.ReactNode;
  /** Route id to navigate to when clicked. If absent, item is non-interactive (group header / divider). */
  route?: string;
  /** External URL to open in a new tab when clicked. Mutually exclusive with `route`. */
  href?: string;
  /** Hide this entry when callback returns false. Defaults to always visible. */
  visible?: () => boolean;
  /** Render as group header (children appear nested under it). */
  isGroup?: boolean;
  /** Render as horizontal divider. id is still required for de-dup. */
  divider?: boolean;
}

// ─────────────────────────────────────────────────────────────────────────────
// Route (console-wide)
// ─────────────────────────────────────────────────────────────────────────────

/** A registered route entry (added via builtinRoutes or QwenPaw.route.add). */
export interface Route {
  /** Stable id, e.g. "core.chat" / "cloudpaw.a2a". */
  id: string;
  /** URL path. Supports react-router patterns, including "/chat/*". */
  path: string;
  /** Lazy or eager component. */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  component: React.ComponentType<any>;
}

/**
 * Onion-style wrapper. Receives the inner component (current resolved render)
 * and returns the new component to render. Multiple wraps compose;
 * later-registered wrappers wrap the outside (see resolveRoute in store.ts).
 */
export type RouteWrapper = (
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  Inner: React.ComponentType<any>,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
) => React.ComponentType<any>;

// ─────────────────────────────────────────────────────────────────────────────
// Slot (console-wide)
// ─────────────────────────────────────────────────────────────────────────────

/** A free-form name like "header.left" / "sider.bottom". Host curates the list. */
export type SlotName = string;

export type SlotKind = "fill" | "replace";

export interface SlotOpts {
  /** Stable id for this fill; lets other fills target with before/after. */
  id?: string;
  /** Numeric fallback. Lower renders first. */
  order?: number;
  /** Render only when this returns true. */
  visible?: () => boolean;
  /** Render strictly before another fill (same slot). fill-mode only. */
  before?: string;
  /** Render strictly after another fill (same slot). fill-mode only. */
  after?: string;
}

/**
 * Slot render function. Receives the host's default content for this slot
 * (i.e. the `children` passed to the <Slot> JSX element) so a
 * conditional plugin can `return defaultContent` to opt out of replacement
 * in some scenarios without having to re-implement the default itself.
 * Plugins that always replace can ignore the parameter.
 */
export type SlotRenderer = (
  defaultContent?: React.ReactNode,
) => React.ReactNode;

export interface SlotInfo {
  name: SlotName;
  kind: SlotKind;
  source: string;
  id?: string;
  order?: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Chat scalar fields (last-writer-wins) — consumed by chatExtensions registry
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

export type ChatRequestSlotFn = (ctx: {
  data: ChatRequestData;
}) => React.ReactNode;
export type ChatResponseSlotFn = (ctx: {
  data: ChatResponseData;
  isLast?: boolean;
}) => React.ReactNode;

export interface ChatSlotItem<F> {
  id: string;
  render: F;
  order?: number;
}

// Chat scalar / list field name unions are defined in `./slotKeys.ts` for
// single-source-of-truth ergonomics; re-exported here for caller convenience.
export type { ChatScalarField, ChatListField } from "./slotKeys";
import type { ChatScalarField, ChatListField } from "./slotKeys";

export interface ChatScalarValues {
  "welcome.greeting"?: Localized<React.ReactNode>;
  "welcome.description"?: Localized<React.ReactNode>;
  "welcome.avatar"?: Localized<string | React.ReactNode>;
  "welcome.nick"?: Localized<string | React.ReactNode>;
  "welcome.prompts"?: Localized<
    Array<{ label?: React.ReactNode; value: string }>
  >;
  /** Whole-section override of the welcome panel. Wins over the partial fields above. */
  "welcome.render"?: WelcomeRenderFn;
  "header.leftTitle"?: Localized<React.ReactNode>;
  "header.leftLogo"?: Localized<string | React.ReactNode>;
  /** Whole-section override of theme.leftHeader. Wins over leftTitle/leftLogo. */
  "header.leftHeader.render"?: React.ReactNode;
  "theme.colorPrimary"?: string;
  "sender.placeholder"?: Localized<string>;
  "sender.disclaimer"?: Localized<React.ReactNode>;
  /** Whole-bubble replacement for user requests. Wins over additive prepend/append slots. */
  "request.render"?: ChatRequestRenderFn;
  /** Whole-bubble replacement for assistant responses. */
  "response.render"?: ChatResponseRenderFn;
}

// ─────────────────────────────────────────────────────────────────────────────
// Chat list item shapes (additive) — consumed by chatExtensions registry
// ─────────────────────────────────────────────────────────────────────────────

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
  render: React.FC<
    { result: unknown; sessionId: string; messageId: string } & Record<
      string,
      unknown
    >
  >;
}

export interface ChatCardItem {
  id: string;
  cardName: string;
  render: React.FC<Record<string, unknown>>;
}

// ─────────────────────────────────────────────────────────────────────────────
// Audit — unified across console + chat registries
// ─────────────────────────────────────────────────────────────────────────────

export type AuditKind =
  // Console-wide registry events
  | "menu.add"
  | "menu.replace"
  | "menu.dispose"
  | "menu.conflict"
  | "route.add"
  | "route.replace"
  | "route.wrap"
  | "route.dispose"
  | "route.conflict"
  | "slot.fill"
  | "slot.replace"
  | "slot.dispose"
  | "slot.error"
  // Chat surface registry events
  | "chat.scalar.set"
  | "chat.scalar.superseded"
  | "chat.scalar.dispose"
  | "chat.list.add"
  | "chat.list.dispose"
  | "chat.error";

export interface OverrideRecord {
  kind: AuditKind;
  /** What was acted on: menuId / routeId / slotName / scalar field / list field / etc. */
  field?: ChatScalarField | ChatListField | string;
  /**
   * Compat alias for `field` used by the console-wide registries.
   * Kept so consumers reading either name continue to work.
   */
  targetId?: string;
  pluginId: string;
  supersededPluginId?: string;
  /** Free-form details (conflict reason, error message, slot id, …). */
  detail?: string;
  timestamp: number;
}

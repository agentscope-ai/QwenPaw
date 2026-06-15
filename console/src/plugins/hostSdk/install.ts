/**
 * hostSdk/install.ts — attach `window.QwenPaw.chat`, `window.QwenPaw.host.*`
 * (hooks + fetch), and `window.QwenPaw.audit` to the global namespace.
 *
 * Call AFTER `installHostExternals()` from main.tsx.
 *
 * Public chat API (3 verbs to cover all intents):
 *   - set(pluginId, partial)  → shallow-merge specific option fields
 *   - render(pluginId, node)  → whole-section replacement (welcome / leftHeader)
 *   - add(pluginId, item)     → append to additive lists (rightHeader / sender.prefix / actions / …)
 */
import type React from "react";
import { chatExtensions } from "../registry/chatExtensions";
import { auditStore } from "../registry/audit";
import { pluginSystem } from "../hostExternals";
import { combineDisposables } from "../registry/types";
import { ChatScalar } from "../registry/slotKeys";
import type {
  ChatActionSpec,
  ChatNodeItem,
  ChatRequestPayloadTransform,
  ChatRequestPayloadTransformItem,
  ChatRequestRenderFn,
  ChatRequestSlotFn,
  ChatResponseRenderFn,
  ChatResponseSlotFn,
  ChatScalarField,
  ChatScalarValues,
  ChatSlotItem,
  ChatSuggestionsItem,
  Disposable,
  OverrideRecord,
  WelcomeRenderFn,
  WelcomeRenderProps,
} from "../registry/types";
import {
  useHostTheme,
  useHostLocale,
  useHostSelectedAgent,
  useHostCurrentSession,
  getSelectedAgentId,
  getCurrentSessionId,
} from "./hooks";
import { hostFetch } from "./fetch";

// ─────────────────────────────────────────────────────────────────────────────
// Plugin-facing API surface
// ─────────────────────────────────────────────────────────────────────────────

export type WelcomeRenderValue = WelcomeRenderFn | React.ReactNode;

interface WelcomePartial {
  greeting?: ChatScalarValues["welcome.greeting"];
  description?: ChatScalarValues["welcome.description"];
  avatar?: ChatScalarValues["welcome.avatar"];
  nick?: ChatScalarValues["welcome.nick"];
  prompts?: ChatScalarValues["welcome.prompts"];
}

interface LeftHeaderPartial {
  logo?: ChatScalarValues["header.leftLogo"];
  title?: ChatScalarValues["header.leftTitle"];
}

interface ThemePartial {
  colorPrimary?: ChatScalarValues["theme.colorPrimary"];
}

interface SenderPartial {
  placeholder?: ChatScalarValues["sender.placeholder"];
  disclaimer?: ChatScalarValues["sender.disclaimer"];
}

interface ResponsePartial {
  avatar?: ChatScalarValues["welcome.avatar"];
  nick?: ChatScalarValues["welcome.nick"];
}

export interface QwenPawChatNamespace {
  welcome: {
    set(pluginId: string, partial: WelcomePartial): Disposable;
    render(pluginId: string, value: WelcomeRenderValue): Disposable;
  };
  theme: {
    set(pluginId: string, partial: ThemePartial): Disposable;
  };
  leftHeader: {
    set(pluginId: string, partial: LeftHeaderPartial): Disposable;
    render(pluginId: string, node: React.ReactNode): Disposable;
  };
  rightHeader: {
    add(
      pluginId: string,
      node: React.ReactNode,
      opts?: { id?: string; order?: number },
    ): Disposable;
  };
  sender: {
    set(pluginId: string, partial: SenderPartial): Disposable;
    addPrefix(
      pluginId: string,
      node: React.ReactNode,
      opts?: { id?: string; order?: number },
    ): Disposable;
    addSuggestion(
      pluginId: string,
      item: { id?: string; items: ChatSuggestionsItem["items"] },
    ): Disposable;
  };
  actions: { add(pluginId: string, spec: ChatActionSpec): Disposable };
  requestActions: { add(pluginId: string, spec: ChatActionSpec): Disposable };
  requestPayload: {
    add(
      pluginId: string,
      fn: ChatRequestPayloadTransform,
      opts?: { id?: string; order?: number },
    ): Disposable;
  };
  request: {
    /** Whole-bubble replacement for the user request card. Wins over host default; prepend/append still render around it. */
    render(pluginId: string, fn: ChatRequestRenderFn): Disposable;
    /** Append a custom component above the user bubble. Returning null skips this bubble. */
    prepend(
      pluginId: string,
      fn: ChatRequestSlotFn,
      opts?: { id?: string; order?: number },
    ): Disposable;
    /** Append a custom component below the user bubble. */
    append(
      pluginId: string,
      fn: ChatRequestSlotFn,
      opts?: { id?: string; order?: number },
    ): Disposable;
  };
  response: {
    /** Configure the default assistant identity. Reuses welcome.avatar/nick because the vendor ResponseCard reads those fields. */
    set(pluginId: string, partial: ResponsePartial): Disposable;
    /** Whole-bubble replacement for the assistant response card. */
    render(pluginId: string, fn: ChatResponseRenderFn): Disposable;
    /** Append a custom component above the AI bubble. */
    prepend(
      pluginId: string,
      fn: ChatResponseSlotFn,
      opts?: { id?: string; order?: number },
    ): Disposable;
    /** Append a custom component below the AI bubble. */
    append(
      pluginId: string,
      fn: ChatResponseSlotFn,
      opts?: { id?: string; order?: number },
    ): Disposable;
  };
  toolRender(
    pluginId: string,
    toolName: string,
    render: React.FC<Record<string, unknown>>,
  ): Disposable;
  card(
    pluginId: string,
    cardName: string,
    render: React.FC<Record<string, unknown>>,
  ): Disposable;
  disposeAll(pluginId: string): void;
}

export interface QwenPawAuditNamespace {
  overrides(): OverrideRecord[];
}

// ─────────────────────────────────────────────────────────────────────────────
// Internal helpers
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Apply a `set(partial)` call by fanning out to setScalar() per field.
 * Returns a combined Disposable that reverts every field this call wrote.
 * Fields are stored independently in their own LIFO stacks, so different
 * fields from different plugins coexist without overwriting each other.
 */
function applyPartial<T extends object>(
  pluginId: string,
  partial: T,
  fieldMap: Record<keyof T, ChatScalarField>,
): Disposable {
  const disposables: Disposable[] = [];
  for (const k of Object.keys(partial) as Array<keyof T>) {
    const value = (partial as Record<keyof T, unknown>)[k];
    if (value === undefined) continue;
    const field = fieldMap[k];
    // The runtime carries the typed value through to setScalar — but TS
    // can't see the structural mapping, so we cast at the boundary.
    disposables.push(
      chatExtensions.setScalar(
        pluginId,
        field,
        value as unknown as ChatScalarValues[typeof field],
      ),
    );
  }
  return combineDisposables(...disposables);
}

/** Normalize a plugin-supplied welcome.render value into the SDK's fn shape. */
function normalizeWelcomeRender(value: WelcomeRenderValue): WelcomeRenderFn {
  if (typeof value === "function") {
    return value as WelcomeRenderFn;
  }
  // Plain ReactNode → wrap into a fn that ignores SDK props and renders the node verbatim.
  const node = value;
  return ((_props: WelcomeRenderProps) =>
    node as unknown as React.ReactElement) as WelcomeRenderFn;
}

// ─────────────────────────────────────────────────────────────────────────────
// Build the namespace
// ─────────────────────────────────────────────────────────────────────────────

function makeChatNamespace(): QwenPawChatNamespace {
  let anonSeq = 0;
  const anonId = (kind: string) => {
    anonSeq += 1;
    return `${kind}.anon.${anonSeq}`;
  };

  const welcomeFieldMap: Record<keyof WelcomePartial, ChatScalarField> = {
    greeting: ChatScalar.welcomeGreeting,
    description: ChatScalar.welcomeDescription,
    avatar: ChatScalar.welcomeAvatar,
    nick: ChatScalar.welcomeNick,
    prompts: ChatScalar.welcomePrompts,
  };

  const leftHeaderFieldMap: Record<keyof LeftHeaderPartial, ChatScalarField> = {
    logo: ChatScalar.headerLeftLogo,
    title: ChatScalar.headerLeftTitle,
  };

  const themeFieldMap: Record<keyof ThemePartial, ChatScalarField> = {
    colorPrimary: ChatScalar.themeColorPrimary,
  };

  const senderFieldMap: Record<keyof SenderPartial, ChatScalarField> = {
    placeholder: ChatScalar.senderPlaceholder,
    disclaimer: ChatScalar.senderDisclaimer,
  };

  const responseFieldMap: Record<keyof ResponsePartial, ChatScalarField> = {
    avatar: ChatScalar.welcomeAvatar,
    nick: ChatScalar.welcomeNick,
  };

  return {
    welcome: {
      set: (pid, partial) => applyPartial(pid, partial, welcomeFieldMap),
      render: (pid, value) =>
        chatExtensions.setScalar(
          pid,
          ChatScalar.welcomeRender,
          normalizeWelcomeRender(value),
        ),
    },
    theme: {
      set: (pid, partial) => applyPartial(pid, partial, themeFieldMap),
    },
    leftHeader: {
      set: (pid, partial) => applyPartial(pid, partial, leftHeaderFieldMap),
      render: (pid, node) =>
        chatExtensions.setScalar(pid, ChatScalar.headerLeftHeaderRender, node),
    },
    rightHeader: {
      add: (pid, node, opts) => {
        const item: ChatNodeItem = {
          id: opts?.id ?? anonId(`${pid}.rightHeader`),
          node,
          order: opts?.order,
        };
        return chatExtensions.addRightHeader(pid, item);
      },
    },
    sender: {
      set: (pid, partial) => applyPartial(pid, partial, senderFieldMap),
      addPrefix: (pid, node, opts) => {
        const item: ChatNodeItem = {
          id: opts?.id ?? anonId(`${pid}.senderPrefix`),
          node,
          order: opts?.order,
        };
        return chatExtensions.addSenderPrefix(pid, item);
      },
      addSuggestion: (pid, { id, items }) => {
        const sug: ChatSuggestionsItem = {
          id: id ?? anonId(`${pid}.suggestion`),
          items,
        };
        return chatExtensions.addSenderSuggestions(pid, sug);
      },
    },
    actions: { add: (pid, action) => chatExtensions.addAction(pid, action) },
    requestActions: {
      add: (pid, action) => chatExtensions.addRequestAction(pid, action),
    },
    requestPayload: {
      add: (pid, fn, opts) => {
        const item: ChatRequestPayloadTransformItem = {
          id: opts?.id ?? anonId(`${pid}.request.payloadTransform`),
          transform: fn,
          order: opts?.order,
        };
        return chatExtensions.addRequestPayloadTransform(pid, item);
      },
    },
    request: {
      render: (pid, fn) =>
        chatExtensions.setScalar(pid, ChatScalar.requestRender, fn),
      prepend: (pid, fn, opts) => {
        const item: ChatSlotItem<ChatRequestSlotFn> = {
          id: opts?.id ?? anonId(`${pid}.request.prepend`),
          render: fn,
          order: opts?.order,
        };
        return chatExtensions.addRequestPrepend(pid, item);
      },
      append: (pid, fn, opts) => {
        const item: ChatSlotItem<ChatRequestSlotFn> = {
          id: opts?.id ?? anonId(`${pid}.request.append`),
          render: fn,
          order: opts?.order,
        };
        return chatExtensions.addRequestAppend(pid, item);
      },
    },
    response: {
      set: (pid, partial) => applyPartial(pid, partial, responseFieldMap),
      render: (pid, fn) =>
        chatExtensions.setScalar(pid, ChatScalar.responseRender, fn),
      prepend: (pid, fn, opts) => {
        const item: ChatSlotItem<ChatResponseSlotFn> = {
          id: opts?.id ?? anonId(`${pid}.response.prepend`),
          render: fn,
          order: opts?.order,
        };
        return chatExtensions.addResponsePrepend(pid, item);
      },
      append: (pid, fn, opts) => {
        const item: ChatSlotItem<ChatResponseSlotFn> = {
          id: opts?.id ?? anonId(`${pid}.response.append`),
          render: fn,
          order: opts?.order,
        };
        return chatExtensions.addResponseAppend(pid, item);
      },
    },
    toolRender: (pid, toolName, render) => {
      // Mirror to existing pluginSystem.toolRenderers so the old
      // `usePlugins().toolRenderConfig` path keeps producing the same map.
      pluginSystem.addToolRenderers(pid, { [toolName]: render });
      return chatExtensions.addToolRender(pid, toolName, render);
    },
    card: (pid, cardName, render) =>
      chatExtensions.addCard(pid, cardName, render),
    disposeAll: (pid) => chatExtensions.disposeAll(pid),
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Install
// ─────────────────────────────────────────────────────────────────────────────

export function installHostSdk(): void {
  if (typeof window === "undefined") return;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const ns = (window.QwenPaw as any) ?? ((window as any).QwenPaw = {});

  if (!ns.chat) {
    ns.chat = makeChatNamespace();
  }

  if (!ns.audit) {
    const auditNamespace: QwenPawAuditNamespace = {
      overrides: () => auditStore.overrides(),
    };
    ns.audit = auditNamespace;
  }

  // Extend window.QwenPaw.host with hooks + fetch.
  // hostExternals.ts attaches host first; we add new fields without
  // overwriting React / antd / antdIcons / getApiUrl / getApiToken.
  const host = ns.host ?? (ns.host = {});
  if (!host.useTheme) host.useTheme = useHostTheme;
  if (!host.useLocale) host.useLocale = useHostLocale;
  if (!host.useSelectedAgent) host.useSelectedAgent = useHostSelectedAgent;
  if (!host.useCurrentSession) host.useCurrentSession = useHostCurrentSession;
  if (!host.getSelectedAgentId) host.getSelectedAgentId = getSelectedAgentId;
  if (!host.getCurrentSessionId) host.getCurrentSessionId = getCurrentSessionId;
  if (!host.fetch) host.fetch = hostFetch;
}

/**
 * registry/chatExtensions.ts — singleton store for plugin-contributed Chat customizations.
 *
 * Two storage shapes:
 *
 *   1. Scalar fields (last-writer-wins):
 *      - Each ChatScalarField has its own LIFO stack of registrations.
 *      - `setScalar` pushes a new entry to the top of the stack.
 *      - The returned Disposable removes ONLY that specific entry (by stable
 *        registrationId), so disposing a superseded registration is a no-op for
 *        the current winner, and disposing the current winner falls back to the
 *        previous entry in the stack.
 *
 *   2. Additive lists (header.rightHeader, sender.prefix, actions, …):
 *      - Each list holds entries in registration order.
 *      - Consumers (ChatPage useMemo) stable-sort by `order` then registration time.
 *
 * The registry notifies subscribers on every mutation. ChatPage consumes via
 * `useChatExtensions.ts` which uses `useSyncExternalStore`.
 */
import type {
  ChatActionItem,
  ChatActionSpec,
  ChatCardItem,
  ChatListField,
  ChatNodeItem,
  ChatRequestPayloadTransformItem,
  ChatRequestSlotFn,
  ChatResponseSlotFn,
  ChatScalarField,
  ChatScalarValues,
  ChatSlotItem,
  ChatSuggestionsItem,
  ChatToolRendererItem,
  Disposable,
  Localized,
} from "./types";
import { auditStore } from "./audit";

// ─────────────────────────────────────────────────────────────────────────────
// Internal entry shapes
// ─────────────────────────────────────────────────────────────────────────────

interface ScalarEntry<F extends ChatScalarField> {
  registrationId: string;
  pluginId: string;
  field: F;
  value: ChatScalarValues[F];
  registeredAt: number;
}

interface ListEntry<T> {
  registrationId: string;
  pluginId: string;
  item: T;
  registeredAt: number;
}

/** Public read shape consumed by ChatPage hooks (one winner per scalar field). */
export interface ChatScalarSnapshot {
  "welcome.greeting"?: {
    pluginId: string;
    value: ChatScalarValues["welcome.greeting"];
  };
  "welcome.description"?: {
    pluginId: string;
    value: ChatScalarValues["welcome.description"];
  };
  "welcome.avatar"?: {
    pluginId: string;
    value: ChatScalarValues["welcome.avatar"];
  };
  "welcome.nick"?: {
    pluginId: string;
    value: ChatScalarValues["welcome.nick"];
  };
  "welcome.prompts"?: {
    pluginId: string;
    value: ChatScalarValues["welcome.prompts"];
  };
  "welcome.render"?: {
    pluginId: string;
    value: ChatScalarValues["welcome.render"];
  };
  "header.leftTitle"?: {
    pluginId: string;
    value: ChatScalarValues["header.leftTitle"];
  };
  "header.leftLogo"?: {
    pluginId: string;
    value: ChatScalarValues["header.leftLogo"];
  };
  "header.leftHeader.render"?: {
    pluginId: string;
    value: ChatScalarValues["header.leftHeader.render"];
  };
  "theme.colorPrimary"?: {
    pluginId: string;
    value: ChatScalarValues["theme.colorPrimary"];
  };
  "sender.placeholder"?: {
    pluginId: string;
    value: ChatScalarValues["sender.placeholder"];
  };
  "sender.disclaimer"?: {
    pluginId: string;
    value: ChatScalarValues["sender.disclaimer"];
  };
  "request.render"?: {
    pluginId: string;
    value: ChatScalarValues["request.render"];
  };
  "response.render"?: {
    pluginId: string;
    value: ChatScalarValues["response.render"];
  };
}

export interface ChatListSnapshot {
  "header.rightHeader": ListEntry<ChatNodeItem>[];
  "sender.prefix": ListEntry<ChatNodeItem>[];
  "sender.suggestions": ListEntry<ChatSuggestionsItem>[];
  actions: ListEntry<ChatActionItem>[];
  requestActions: ListEntry<ChatActionItem>[];
  cards: ListEntry<ChatCardItem>[];
  customToolRender: ListEntry<ChatToolRendererItem>[];
  "request.prepend": ListEntry<ChatSlotItem<ChatRequestSlotFn>>[];
  "request.append": ListEntry<ChatSlotItem<ChatRequestSlotFn>>[];
  "request.payloadTransforms": ListEntry<ChatRequestPayloadTransformItem>[];
  "response.prepend": ListEntry<ChatSlotItem<ChatResponseSlotFn>>[];
  "response.append": ListEntry<ChatSlotItem<ChatResponseSlotFn>>[];
}

// ─────────────────────────────────────────────────────────────────────────────
// Registry implementation
// ─────────────────────────────────────────────────────────────────────────────

class ChatExtensionsRegistry {
  // Each scalar field: a stack; top entry is the winner.
  private scalarStacks = new Map<
    ChatScalarField,
    ScalarEntry<ChatScalarField>[]
  >();
  // Each list field: append-only array.
  private listMaps: ChatListSnapshot = {
    "header.rightHeader": [],
    "sender.prefix": [],
    "sender.suggestions": [],
    actions: [],
    requestActions: [],
    cards: [],
    customToolRender: [],
    "request.prepend": [],
    "request.append": [],
    "request.payloadTransforms": [],
    "response.prepend": [],
    "response.append": [],
  };

  private listeners = new Set<() => void>();

  // Memoized snapshots — recreated only when state changes, so
  // useSyncExternalStore consumers don't see new refs on every read.
  private scalarSnapshot: ChatScalarSnapshot = {};
  private listSnapshot: ChatListSnapshot = { ...this.listMaps };
  private seq = 0;

  // ── Scalar ────────────────────────────────────────────────────────────────

  setScalar<F extends ChatScalarField>(
    pluginId: string,
    field: F,
    value: ChatScalarValues[F],
  ): Disposable {
    const stack = (this.scalarStacks.get(field) ?? []) as ScalarEntry<F>[];
    const prevTop = stack[stack.length - 1];
    const entry: ScalarEntry<F> = {
      registrationId: this.nextId(),
      pluginId,
      field,
      value,
      registeredAt: Date.now(),
    };
    stack.push(entry);
    this.scalarStacks.set(field, stack as ScalarEntry<ChatScalarField>[]);

    auditStore.record({
      kind: "chat.scalar.set",
      field,
      pluginId,
      supersededPluginId: prevTop?.pluginId,
      timestamp: entry.registeredAt,
    });
    if (prevTop && prevTop.pluginId !== pluginId) {
      auditStore.record({
        kind: "chat.scalar.superseded",
        field,
        pluginId: prevTop.pluginId,
        supersededPluginId: pluginId,
        timestamp: entry.registeredAt,
      });
    }

    this.rebuildScalarSnapshot();
    this.notify();

    let disposed = false;
    return {
      dispose: () => {
        if (disposed) return;
        disposed = true;
        const cur = (this.scalarStacks.get(field) ?? []) as ScalarEntry<F>[];
        const idx = cur.findIndex(
          (e) => e.registrationId === entry.registrationId,
        );
        if (idx < 0) return;
        cur.splice(idx, 1);
        this.scalarStacks.set(field, cur as ScalarEntry<ChatScalarField>[]);
        auditStore.record({
          kind: "chat.scalar.dispose",
          field,
          pluginId,
          timestamp: Date.now(),
        });
        this.rebuildScalarSnapshot();
        this.notify();
      },
    };
  }

  // ── Additive lists ────────────────────────────────────────────────────────

  addRightHeader(pluginId: string, item: ChatNodeItem): Disposable {
    return this.addToList("header.rightHeader", pluginId, item);
  }

  addSenderPrefix(pluginId: string, item: ChatNodeItem): Disposable {
    return this.addToList("sender.prefix", pluginId, item);
  }

  addSenderSuggestions(
    pluginId: string,
    item: ChatSuggestionsItem,
  ): Disposable {
    return this.addToList("sender.suggestions", pluginId, item);
  }

  addAction(pluginId: string, spec: ChatActionSpec): Disposable {
    return this.addToList("actions", pluginId, {
      id: spec.id,
      pluginId,
      item: spec,
    });
  }

  addRequestAction(pluginId: string, spec: ChatActionSpec): Disposable {
    return this.addToList("requestActions", pluginId, {
      id: spec.id,
      pluginId,
      item: spec,
    });
  }

  addToolRender(
    pluginId: string,
    toolName: string,
    render: ChatToolRendererItem["render"],
  ): Disposable {
    return this.addToList("customToolRender", pluginId, {
      id: `${pluginId}:${toolName}`,
      toolName,
      render,
    });
  }

  addCard(
    pluginId: string,
    cardName: string,
    render: ChatCardItem["render"],
  ): Disposable {
    return this.addToList("cards", pluginId, {
      id: `${pluginId}:${cardName}`,
      cardName,
      render,
    });
  }

  addRequestPrepend(
    pluginId: string,
    item: ChatSlotItem<ChatRequestSlotFn>,
  ): Disposable {
    return this.addToList("request.prepend", pluginId, item);
  }

  addRequestAppend(
    pluginId: string,
    item: ChatSlotItem<ChatRequestSlotFn>,
  ): Disposable {
    return this.addToList("request.append", pluginId, item);
  }

  addRequestPayloadTransform(
    pluginId: string,
    item: ChatRequestPayloadTransformItem,
  ): Disposable {
    return this.addToList("request.payloadTransforms", pluginId, item);
  }

  addResponsePrepend(
    pluginId: string,
    item: ChatSlotItem<ChatResponseSlotFn>,
  ): Disposable {
    return this.addToList("response.prepend", pluginId, item);
  }

  addResponseAppend(
    pluginId: string,
    item: ChatSlotItem<ChatResponseSlotFn>,
  ): Disposable {
    return this.addToList("response.append", pluginId, item);
  }

  private addToList<F extends ChatListField>(
    field: F,
    pluginId: string,
    item: ChatListSnapshot[F][number]["item"],
  ): Disposable {
    const registrationId = this.nextId();
    const registeredAt = Date.now();
    const entry: ListEntry<typeof item> = {
      registrationId,
      pluginId,
      item,
      registeredAt,
    };
    (this.listMaps[field] as ListEntry<typeof item>[]).push(entry);

    auditStore.record({
      kind: "chat.list.add",
      field,
      pluginId,
      detail: this.itemDescription(field, item),
      timestamp: registeredAt,
    });

    this.rebuildListSnapshot(field);
    this.notify();

    let disposed = false;
    return {
      dispose: () => {
        if (disposed) return;
        disposed = true;
        const arr = this.listMaps[field] as ListEntry<typeof item>[];
        const idx = arr.findIndex((e) => e.registrationId === registrationId);
        if (idx < 0) return;
        arr.splice(idx, 1);
        auditStore.record({
          kind: "chat.list.dispose",
          field,
          pluginId,
          timestamp: Date.now(),
        });
        this.rebuildListSnapshot(field);
        this.notify();
      },
    };
  }

  // ── Bulk dispose for plugin unload (future) ───────────────────────────────

  disposeAll(pluginId: string): void {
    let mutated = false;

    for (const [field, stack] of this.scalarStacks) {
      const filtered = stack.filter((e) => e.pluginId !== pluginId);
      if (filtered.length !== stack.length) {
        this.scalarStacks.set(field, filtered);
        mutated = true;
      }
    }

    for (const field of Object.keys(this.listMaps) as ChatListField[]) {
      const arr = this.listMaps[field] as ListEntry<unknown>[];
      const filtered = arr.filter((e) => e.pluginId !== pluginId);
      if (filtered.length !== arr.length) {
        (this.listMaps as unknown as Record<string, ListEntry<unknown>[]>)[
          field
        ] = filtered;
        mutated = true;
      }
    }

    if (mutated) {
      this.rebuildScalarSnapshot();
      for (const field of Object.keys(this.listMaps) as ChatListField[]) {
        this.rebuildListSnapshot(field);
      }
      this.notify();
    }
  }

  // ── Read API (snapshots are stable refs between mutations) ────────────────

  getScalarSnapshot(): ChatScalarSnapshot {
    return this.scalarSnapshot;
  }

  getListSnapshot(): ChatListSnapshot {
    return this.listSnapshot;
  }

  // ── Subscription ──────────────────────────────────────────────────────────

  subscribe(cb: () => void): () => void {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  }

  // ── Test helper ───────────────────────────────────────────────────────────

  /** Reset all state. Tests only. */
  __resetForTests(): void {
    this.scalarStacks.clear();
    for (const f of Object.keys(this.listMaps) as ChatListField[]) {
      (this.listMaps as unknown as Record<string, ListEntry<unknown>[]>)[f] =
        [];
    }
    this.rebuildScalarSnapshot();
    for (const f of Object.keys(this.listMaps) as ChatListField[]) {
      this.rebuildListSnapshot(f);
    }
    this.listeners.clear();
    this.seq = 0;
  }

  // ── Internals ─────────────────────────────────────────────────────────────

  private nextId(): string {
    this.seq += 1;
    return `r${this.seq}`;
  }

  private rebuildScalarSnapshot(): void {
    const next: ChatScalarSnapshot = {};
    for (const [field, stack] of this.scalarStacks) {
      const top = stack[stack.length - 1];
      if (top) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (next as any)[field] = { pluginId: top.pluginId, value: top.value };
      }
    }
    this.scalarSnapshot = next;
  }

  private rebuildListSnapshot(field: ChatListField): void {
    // Always rebuild the full snapshot object so consumers can compare by ref.
    this.listSnapshot = {
      "header.rightHeader": this.listMaps["header.rightHeader"].slice(),
      "sender.prefix": this.listMaps["sender.prefix"].slice(),
      "sender.suggestions": this.listMaps["sender.suggestions"].slice(),
      actions: this.listMaps.actions.slice(),
      requestActions: this.listMaps.requestActions.slice(),
      cards: this.listMaps.cards.slice(),
      customToolRender: this.listMaps.customToolRender.slice(),
      "request.prepend": this.listMaps["request.prepend"].slice(),
      "request.append": this.listMaps["request.append"].slice(),
      "request.payloadTransforms":
        this.listMaps["request.payloadTransforms"].slice(),
      "response.prepend": this.listMaps["response.prepend"].slice(),
      "response.append": this.listMaps["response.append"].slice(),
    };
    void field;
  }

  private notify(): void {
    for (const fn of this.listeners) {
      try {
        fn();
      } catch (err) {
        console.warn("[QwenPaw] chatExtensions listener threw:", err);
      }
    }
  }

  private itemDescription(field: ChatListField, item: unknown): string {
    if (field === "actions" || field === "requestActions") {
      const a = item as ChatActionItem;
      return a?.id ?? "(no id)";
    }
    if (field === "customToolRender") {
      return (item as ChatToolRendererItem).toolName;
    }
    if (field === "cards") {
      return (item as ChatCardItem).cardName;
    }
    if (field === "sender.suggestions") {
      return (item as ChatSuggestionsItem).id;
    }
    if (field === "request.payloadTransforms") {
      return (item as { id?: string }).id ?? "(no id)";
    }
    return (item as ChatNodeItem).id ?? "(no id)";
  }
}

// Suppress noisy unused-locale type warning when value resolution happens in consumers.
export type { Localized };

export const chatExtensions = new ChatExtensionsRegistry();

/**
 * registry/store.ts — Menu / Route / Slot singletons backed by a shared notify bus.
 *
 * Three sub-registries share one subscriber set (`notify`) so a single
 * `useSyncExternalStore` subscription wakes up consumers of any of them.
 * Snapshot methods return memoized stable refs between mutations to keep
 * downstream useMemo deps quiet.
 *
 * Conflict policy:
 *   - menu.add of duplicate id → no-op + audit "menu.conflict" + warn.
 *   - route.add of duplicate id OR path → no-op + audit "route.conflict".
 *   - menu.replace / route.replace → LIFO stack; dispose pops to prior winner.
 *   - route.wrap → list, reduceRight composition (last-registered wraps outermost).
 *   - slot.replace → LIFO winner among entries with kind="replace"; fills are
 *     skipped entirely when a replace is active.
 */
import type {
  Disposable,
  MenuItem,
  MenuLocation,
  Route,
  RouteWrapper,
  SlotInfo,
  SlotKind,
  SlotName,
  SlotOpts,
  SlotRenderer,
} from "./types";
import { auditStore } from "./audit";

// ─────────────────────────────────────────────────────────────────────────────
// Shared notify bus
// ─────────────────────────────────────────────────────────────────────────────

type Listener = () => void;
const listeners = new Set<Listener>();

function notify(): void {
  for (const fn of listeners) {
    try {
      fn();
    } catch (err) {
      console.warn("[QwenPaw registry] subscriber threw:", err);
    }
  }
}

export function subscribe(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

let seq = 0;
const nextId = () => {
  seq += 1;
  return `r${seq}`;
};

// ─────────────────────────────────────────────────────────────────────────────
// MenuRegistry
// ─────────────────────────────────────────────────────────────────────────────

interface MenuEntry {
  source: string;
  item: MenuItem;
  registrationId: string;
  registeredAt: number;
}

class MenuRegistryImpl {
  // Single source: each id has a STACK of entries (replace pushes, dispose pops).
  private stacks = new Map<string, MenuEntry[]>();
  private snapshots = new Map<MenuLocation | "*", MenuItem[]>();
  private allSnapshot: MenuItem[] = [];

  /** Used by builtinMenu.ts at module-load time. source = "core". */
  addBuiltin(items: MenuItem[]): void {
    for (const item of items) {
      this.addInternal("core", item, /*isReplace*/ false, /*silent*/ true);
    }
    this.invalidate();
    notify();
  }

  add(source: string, item: MenuItem): Disposable {
    return this.addInternal(source, item, false, false);
  }

  replace(source: string, targetId: string, item: MenuItem): Disposable {
    const stack = this.stacks.get(targetId);
    if (!stack || stack.length === 0) {
      // No prior — treat as add. Audit as conflict so reviewer notices.
      auditStore.record({
        kind: "menu.conflict",
        targetId,
        pluginId: source,
        detail: "replace target not found; falling back to add",
        timestamp: Date.now(),
      });
      return this.addInternal(source, { ...item, id: targetId }, false, false);
    }
    return this.addInternal(source, { ...item, id: targetId }, true, false);
  }

  remove(targetId: string): void {
    if (this.stacks.delete(targetId)) {
      this.invalidate();
      notify();
    }
  }

  refresh(): void {
    this.invalidate();
    notify();
  }

  snapshot(location?: MenuLocation): MenuItem[] {
    if (!location) {
      return this.allSnapshot;
    }
    const cached = this.snapshots.get(location);
    if (cached) return cached;
    const built = this.buildSnapshot(location);
    this.snapshots.set(location, built);
    return built;
  }

  /** Test-only. */
  __resetForTests(): void {
    this.stacks.clear();
    this.invalidate();
  }

  private addInternal(
    source: string,
    item: MenuItem,
    isReplace: boolean,
    silent: boolean,
  ): Disposable {
    const existing = this.stacks.get(item.id);
    if (existing && existing.length > 0 && !isReplace) {
      auditStore.record({
        kind: "menu.conflict",
        targetId: item.id,
        pluginId: source,
        supersededPluginId: existing[existing.length - 1].source,
        detail: "duplicate id; call replace() to override",
        timestamp: Date.now(),
      });
      return { dispose: () => {} };
    }
    const entry: MenuEntry = {
      source,
      item,
      registrationId: nextId(),
      registeredAt: Date.now(),
    };
    const stack = existing ?? [];
    const prevTop = stack[stack.length - 1];
    stack.push(entry);
    this.stacks.set(item.id, stack);

    if (!silent) {
      auditStore.record({
        kind: isReplace ? "menu.replace" : "menu.add",
        targetId: item.id,
        pluginId: source,
        supersededPluginId: prevTop?.source,
        timestamp: entry.registeredAt,
      });
      this.invalidate();
      notify();
    }

    let disposed = false;
    return {
      dispose: () => {
        if (disposed) return;
        disposed = true;
        const cur = this.stacks.get(item.id);
        if (!cur) return;
        const idx = cur.findIndex(
          (e) => e.registrationId === entry.registrationId,
        );
        if (idx < 0) return;
        cur.splice(idx, 1);
        if (cur.length === 0) {
          this.stacks.delete(item.id);
        }
        auditStore.record({
          kind: "menu.dispose",
          targetId: item.id,
          pluginId: source,
          timestamp: Date.now(),
        });
        this.invalidate();
        notify();
      },
    };
  }

  private invalidate(): void {
    this.snapshots.clear();
    this.allSnapshot = this.collectWinners();
  }

  private collectWinners(): MenuItem[] {
    const winners: MenuItem[] = [];
    for (const stack of this.stacks.values()) {
      const top = stack[stack.length - 1];
      if (top) winners.push(top.item);
    }
    return winners;
  }

  private buildSnapshot(location: MenuLocation): MenuItem[] {
    const winners = this.allSnapshot;
    const inBucket = winners.filter(
      (i) => (i.location ?? "primary.settings") === location,
    );
    const visible = inBucket.filter((i) => i.visible?.() !== false);
    return sortAndTree(visible);
  }
}

/**
 * Topo-sort by before/after with order tiebreak, then group children under
 * their parentId. Returns the top-level items (parents); children live inside
 * each parent under a `__children` ad-hoc field which the Sidebar adapter
 * unpacks. We attach via a wrapped item rather than mutating to keep
 * snapshot refs stable.
 */
function sortAndTree(items: MenuItem[]): MenuItem[] {
  const sorted = topoSort(items);
  const byId = new Map(sorted.map((i) => [i.id, i] as const));
  const childrenOf = new Map<string, MenuItem[]>();
  const topLevel: MenuItem[] = [];

  for (const item of sorted) {
    if (item.parentId && byId.has(item.parentId)) {
      const arr = childrenOf.get(item.parentId) ?? [];
      arr.push(item);
      childrenOf.set(item.parentId, arr);
    } else {
      topLevel.push(item);
    }
  }

  return topLevel.map((parent) => {
    const kids = childrenOf.get(parent.id);
    if (!kids) return parent;
    // Attach via a wrapper symbol so antd adapter can pull children out.
    return Object.assign({}, parent, { __children: kids } as Partial<MenuItem>);
  });
}

/**
 * Kahn's algorithm over before/after constraints. Ties broken by
 * `order` (numeric ascending, missing = Infinity) then by stable input order.
 */
function topoSort(items: MenuItem[]): MenuItem[] {
  const byId = new Map(items.map((i) => [i.id, i] as const));
  const adj = new Map<string, Set<string>>(); // id → ids that must come AFTER it
  const indeg = new Map<string, number>();
  for (const i of items) {
    adj.set(i.id, new Set());
    indeg.set(i.id, 0);
  }
  for (const i of items) {
    if (i.before && byId.has(i.before)) {
      adj.get(i.id)!.add(i.before);
      indeg.set(i.before, (indeg.get(i.before) ?? 0) + 1);
    }
    if (i.after && byId.has(i.after)) {
      adj.get(i.after)!.add(i.id);
      indeg.set(i.id, (indeg.get(i.id) ?? 0) + 1);
    }
  }
  const ready: MenuItem[] = items.filter((i) => (indeg.get(i.id) ?? 0) === 0);
  ready.sort(byOrder);
  const out: MenuItem[] = [];
  while (ready.length > 0) {
    const next = ready.shift()!;
    out.push(next);
    for (const childId of adj.get(next.id) ?? []) {
      const d = (indeg.get(childId) ?? 0) - 1;
      indeg.set(childId, d);
      if (d === 0) {
        const child = byId.get(childId);
        if (child) {
          ready.push(child);
          ready.sort(byOrder);
        }
      }
    }
  }
  // Cycle? Append remaining by order as fallback.
  if (out.length < items.length) {
    const remaining = items.filter((i) => !out.includes(i)).sort(byOrder);
    out.push(...remaining);
  }
  return out;
}

function byOrder(a: { order?: number }, b: { order?: number }): number {
  return (a.order ?? Infinity) - (b.order ?? Infinity);
}

export const menuRegistry = new MenuRegistryImpl();

// ─────────────────────────────────────────────────────────────────────────────
// RouteRegistry
// ─────────────────────────────────────────────────────────────────────────────

interface RouteEntry {
  source: string;
  route: Route;
  registrationId: string;
}

interface RouteOverrideEntry {
  source: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  component: React.ComponentType<any>;
  registrationId: string;
}

interface RouteWrapEntry {
  source: string;
  wrapper: RouteWrapper;
  registrationId: string;
}

interface ResolvedRoute {
  id: string;
  path: string;
  source: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  Component: React.ComponentType<any>;
}

class RouteRegistryImpl {
  private bases = new Map<string, RouteEntry>();
  private overrides = new Map<string, RouteOverrideEntry[]>(); // stack
  private wraps = new Map<string, RouteWrapEntry[]>(); // order = registration order
  private resolvedSnapshot: ResolvedRoute[] = [];

  /** Used by builtinRoutes.ts. source = "core". */
  addBuiltin(routes: Route[]): void {
    for (const r of routes) {
      this.addInternal("core", r, /*silent*/ true);
    }
    this.invalidate();
    notify();
  }

  add(source: string, route: Route): Disposable {
    return this.addInternal(source, route, false);
  }

  replace(
    source: string,
    targetId: string,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    component: React.ComponentType<any>,
  ): Disposable {
    const stack = this.overrides.get(targetId) ?? [];
    const entry: RouteOverrideEntry = {
      source,
      component,
      registrationId: nextId(),
    };
    const prev = stack[stack.length - 1];
    stack.push(entry);
    this.overrides.set(targetId, stack);
    auditStore.record({
      kind: "route.replace",
      targetId,
      pluginId: source,
      supersededPluginId: prev?.source,
      timestamp: Date.now(),
    });
    this.invalidate();
    notify();
    let disposed = false;
    return {
      dispose: () => {
        if (disposed) return;
        disposed = true;
        const cur = this.overrides.get(targetId) ?? [];
        const idx = cur.findIndex(
          (e) => e.registrationId === entry.registrationId,
        );
        if (idx < 0) return;
        cur.splice(idx, 1);
        if (cur.length === 0) this.overrides.delete(targetId);
        auditStore.record({
          kind: "route.dispose",
          targetId,
          pluginId: source,
          timestamp: Date.now(),
        });
        this.invalidate();
        notify();
      },
    };
  }

  wrap(source: string, targetId: string, wrapper: RouteWrapper): Disposable {
    const list = this.wraps.get(targetId) ?? [];
    const entry: RouteWrapEntry = {
      source,
      wrapper,
      registrationId: nextId(),
    };
    list.push(entry);
    this.wraps.set(targetId, list);
    auditStore.record({
      kind: "route.wrap",
      targetId,
      pluginId: source,
      timestamp: Date.now(),
    });
    this.invalidate();
    notify();
    let disposed = false;
    return {
      dispose: () => {
        if (disposed) return;
        disposed = true;
        const cur = this.wraps.get(targetId) ?? [];
        const idx = cur.findIndex(
          (e) => e.registrationId === entry.registrationId,
        );
        if (idx < 0) return;
        cur.splice(idx, 1);
        if (cur.length === 0) this.wraps.delete(targetId);
        auditStore.record({
          kind: "route.dispose",
          targetId,
          pluginId: source,
          timestamp: Date.now(),
        });
        this.invalidate();
        notify();
      },
    };
  }

  remove(targetId: string): void {
    const changed =
      this.bases.delete(targetId) ||
      this.overrides.delete(targetId) ||
      this.wraps.delete(targetId);
    if (changed) {
      this.invalidate();
      notify();
    }
  }

  snapshot(): ResolvedRoute[] {
    return this.resolvedSnapshot;
  }

  /** Test-only. */
  __resetForTests(): void {
    this.bases.clear();
    this.overrides.clear();
    this.wraps.clear();
    this.invalidate();
  }

  private addInternal(
    source: string,
    route: Route,
    silent: boolean,
  ): Disposable {
    if (this.bases.has(route.id)) {
      auditStore.record({
        kind: "route.conflict",
        targetId: route.id,
        pluginId: source,
        detail: "duplicate route id; ignored",
        timestamp: Date.now(),
      });
      return { dispose: () => {} };
    }
    // Path-uniqueness check across all bases
    for (const existing of this.bases.values()) {
      if (existing.route.path === route.path) {
        auditStore.record({
          kind: "route.conflict",
          targetId: route.id,
          pluginId: source,
          detail: `path ${route.path} already registered by ${existing.source} (${existing.route.id})`,
          timestamp: Date.now(),
        });
        return { dispose: () => {} };
      }
    }
    const entry: RouteEntry = {
      source,
      route,
      registrationId: nextId(),
    };
    this.bases.set(route.id, entry);
    if (!silent) {
      auditStore.record({
        kind: "route.add",
        targetId: route.id,
        pluginId: source,
        timestamp: Date.now(),
      });
      this.invalidate();
      notify();
    }
    let disposed = false;
    return {
      dispose: () => {
        if (disposed) return;
        disposed = true;
        const cur = this.bases.get(route.id);
        if (!cur || cur.registrationId !== entry.registrationId) return;
        this.bases.delete(route.id);
        auditStore.record({
          kind: "route.dispose",
          targetId: route.id,
          pluginId: source,
          timestamp: Date.now(),
        });
        this.invalidate();
        notify();
      },
    };
  }

  private invalidate(): void {
    this.resolvedSnapshot = this.resolveAll();
  }

  private resolveAll(): ResolvedRoute[] {
    const out: ResolvedRoute[] = [];
    for (const entry of this.bases.values()) {
      const overrideStack = this.overrides.get(entry.route.id);
      const overrideTop = overrideStack?.[overrideStack.length - 1];
      const base = overrideTop?.component ?? entry.route.component;
      const wraps = this.wraps.get(entry.route.id) ?? [];
      // reduce (left→right): first wrap is applied first (innermost), each
      // subsequent wrap wraps the previous result — last-registered ends up
      // outermost. Matches "later wrap takes the outside" per the doc.
      const Component = wraps.reduce<
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        React.ComponentType<any>
      >((Inner, w) => w.wrapper(Inner), base);
      out.push({
        id: entry.route.id,
        path: entry.route.path,
        source: overrideTop?.source ?? entry.source,
        Component,
      });
    }
    return out;
  }
}

export const routeRegistry = new RouteRegistryImpl();

// ─────────────────────────────────────────────────────────────────────────────
// SlotRegistry
// ─────────────────────────────────────────────────────────────────────────────

interface SlotEntry {
  source: string;
  kind: SlotKind;
  render: SlotRenderer;
  opts: SlotOpts;
  registrationId: string;
  registeredAt: number;
}

class SlotRegistryImpl {
  private slots = new Map<SlotName, SlotEntry[]>();
  private snapshots = new Map<SlotName, SlotEntry[]>();

  fill(
    source: string,
    name: SlotName,
    render: SlotRenderer,
    opts: SlotOpts = {},
  ): Disposable {
    return this.addInternal(source, name, "fill", render, opts);
  }

  replace(
    source: string,
    name: SlotName,
    render: SlotRenderer,
    opts: SlotOpts = {},
  ): Disposable {
    return this.addInternal(source, name, "replace", render, opts);
  }

  snapshot(name: SlotName): SlotEntry[] {
    const cached = this.snapshots.get(name);
    if (cached) return cached;
    const built = this.buildSnapshot(name);
    this.snapshots.set(name, built);
    return built;
  }

  /** Debug: every registered slot across the registry. */
  snapshotAll(): SlotInfo[] {
    const out: SlotInfo[] = [];
    for (const [name, entries] of this.slots) {
      for (const e of entries) {
        out.push({
          name,
          kind: e.kind,
          source: e.source,
          id: e.opts.id,
          order: e.opts.order,
        });
      }
    }
    return out;
  }

  /** Test-only. */
  __resetForTests(): void {
    this.slots.clear();
    this.snapshots.clear();
  }

  private addInternal(
    source: string,
    name: SlotName,
    kind: SlotKind,
    render: SlotRenderer,
    opts: SlotOpts,
  ): Disposable {
    const entry: SlotEntry = {
      source,
      kind,
      render,
      opts,
      registrationId: nextId(),
      registeredAt: Date.now(),
    };
    const arr = this.slots.get(name) ?? [];
    const priorReplace = arr.find((e) => e.kind === "replace");
    arr.push(entry);
    this.slots.set(name, arr);
    auditStore.record({
      kind: kind === "replace" ? "slot.replace" : "slot.fill",
      targetId: name,
      pluginId: source,
      supersededPluginId: kind === "replace" ? priorReplace?.source : undefined,
      detail: opts.id,
      timestamp: entry.registeredAt,
    });
    this.snapshots.delete(name);
    notify();
    let disposed = false;
    return {
      dispose: () => {
        if (disposed) return;
        disposed = true;
        const cur = this.slots.get(name) ?? [];
        const idx = cur.findIndex(
          (e) => e.registrationId === entry.registrationId,
        );
        if (idx < 0) return;
        cur.splice(idx, 1);
        if (cur.length === 0) this.slots.delete(name);
        this.snapshots.delete(name);
        auditStore.record({
          kind: "slot.dispose",
          targetId: name,
          pluginId: source,
          timestamp: Date.now(),
        });
        notify();
      },
    };
  }

  private buildSnapshot(name: SlotName): SlotEntry[] {
    const entries = (this.slots.get(name) ?? []).filter(
      (e) => e.opts.visible?.() !== false,
    );
    const replaceEntries = entries.filter((e) => e.kind === "replace");
    if (replaceEntries.length > 0) {
      // Only the LAST replace wins; fills are dropped.
      return [replaceEntries[replaceEntries.length - 1]];
    }
    return sortFillEntries(entries);
  }
}

function sortFillEntries(entries: SlotEntry[]): SlotEntry[] {
  // Topo sort by before/after on opts.id, with order/registeredAt tiebreak.
  const byId = new Map<string, SlotEntry>();
  for (const e of entries) {
    if (e.opts.id) byId.set(e.opts.id, e);
  }
  const adj = new Map<string, Set<string>>();
  const indeg = new Map<string, number>();
  const sentinel = (e: SlotEntry) => e.registrationId;
  for (const e of entries) {
    adj.set(sentinel(e), new Set());
    indeg.set(sentinel(e), 0);
  }
  for (const e of entries) {
    if (e.opts.before && byId.has(e.opts.before)) {
      const targetSentinel = sentinel(byId.get(e.opts.before)!);
      adj.get(sentinel(e))!.add(targetSentinel);
      indeg.set(targetSentinel, (indeg.get(targetSentinel) ?? 0) + 1);
    }
    if (e.opts.after && byId.has(e.opts.after)) {
      const targetSentinel = sentinel(byId.get(e.opts.after)!);
      adj.get(targetSentinel)!.add(sentinel(e));
      indeg.set(sentinel(e), (indeg.get(sentinel(e)) ?? 0) + 1);
    }
  }
  const compare = (a: SlotEntry, b: SlotEntry) => {
    const o = (a.opts.order ?? Infinity) - (b.opts.order ?? Infinity);
    return o !== 0 ? o : a.registeredAt - b.registeredAt;
  };
  const ready = entries.filter((e) => (indeg.get(sentinel(e)) ?? 0) === 0);
  ready.sort(compare);
  const out: SlotEntry[] = [];
  const bySentinel = new Map(entries.map((e) => [sentinel(e), e] as const));
  while (ready.length > 0) {
    const next = ready.shift()!;
    out.push(next);
    for (const child of adj.get(sentinel(next)) ?? []) {
      const d = (indeg.get(child) ?? 0) - 1;
      indeg.set(child, d);
      if (d === 0) {
        const childEntry = bySentinel.get(child);
        if (childEntry) {
          ready.push(childEntry);
          ready.sort(compare);
        }
      }
    }
  }
  if (out.length < entries.length) {
    const remaining = entries.filter((e) => !out.includes(e)).sort(compare);
    out.push(...remaining);
  }
  return out;
}

export const slotRegistry = new SlotRegistryImpl();
export type { SlotEntry };

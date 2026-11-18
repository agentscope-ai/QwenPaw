/**
 * ModelManageModal - the router that picks which model-management modal a
 * provider gets. Real caller: `src/pages/Settings/Models/index.tsx:20`
 * (barrel import) rendered at `:606`, with `open={!!modelsModalProvider}` and
 * `onProviderUpdated={(p) => setModelsModalProvider(p)}`.
 *
 * The whole component is one decision - `provider.id === "qwenpaw-local"` - so
 * the value here is in pinning BOTH branches plus what each branch receives.
 * Two things are worth locking down, and neither is visible from a
 * render-only test of either child:
 *
 *   1. The embedded local provider goes to LocalModelManageModal, everything
 *      else (including other local-flavoured providers) goes to
 *      RemoteModelManageModal. Routing by `id` string rather than by the
 *      `is_local` boolean is deliberate: `index.tsx:152` treats BOTH
 *      `qwenpaw-local` and `copaw-local` as "embedded", while this router only
 *      special-cases `qwenpaw-local`. So a provider with `is_local: true` that
 *      is not the embedded one must still land in the remote modal - asserted
 *      explicitly below, because that is the case a refactor to
 *      `if (provider.is_local)` would silently flip.
 *
 *   2. `onProviderUpdated` is forwarded to the remote modal but deliberately
 *      NOT to the local one. That asymmetry mirrors the two child prop
 *      interfaces: `LocalModelManageModalProps` (child source lines 116-121)
 *      has no such field, while `RemoteModelManageModalProps` (lines 42-48)
 *      declares it optional. The local modal manages its own embedded model
 *      list and never reports a provider object upward, so passing the
 *      callback there would be dead wiring.
 *
 * Harness notes:
 *   - Both children are stubbed with prop capture. Rendering the real ones
 *      would pull 1202 + 926 lines of modal, its own API mocks and timers,
 *      and each already has its own suite (`LocalModelManageModal.test.tsx`,
 *      `RemoteModelManageModal.test.tsx`). This file tests the routing only.
 *   - The fixture follows the repo's existing form
 *      (`RemoteModelManageModal.test.tsx:171`, `as unknown as ProviderInfo`);
 *      only `id` is read by the component under test, but the other fields are
 *      filled in so the object stays a believable ProviderInfo for the
 *      assertions that check it is forwarded by identity.
 */
import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import React from "react";

import type { ProviderInfo } from "../../../../../api/types";

const localCalls = vi.hoisted(() => ({ list: [] as unknown[] }));
const remoteCalls = vi.hoisted(() => ({ list: [] as unknown[] }));

vi.mock("./LocalModelManageModal", () => ({
  LocalModelManageModal: (props: unknown) => {
    localCalls.list.push(props);
    return React.createElement("div", { "data-role": "local-modal" });
  },
}));

vi.mock("./RemoteModelManageModal", () => ({
  RemoteModelManageModal: (props: unknown) => {
    remoteCalls.list.push(props);
    return React.createElement("div", { "data-role": "remote-modal" });
  },
}));

import { ModelManageModal } from "./ModelManageModal";

/** Built from the repo's existing ProviderInfo fixture shape. */
function makeProvider(id: string, over: Record<string, unknown> = {}) {
  return {
    id,
    name: id,
    api_key_prefix: "",
    chat_model: "qwen-max",
    models: [],
    extra_models: [],
    is_custom: false,
    is_local: false,
    support_model_discovery: true,
    support_connection_check: true,
    freeze_url: false,
    require_api_key: true,
    api_key: "",
    base_url: "https://api.example/v1",
    generate_kwargs: {},
    ...over,
  } as unknown as ProviderInfo;
}

const LOCAL_STUB = '[data-role="local-modal"]';
const REMOTE_STUB = '[data-role="remote-modal"]';

function renderRouter(
  provider: ProviderInfo,
  over: Partial<{
    open: boolean;
    onClose: () => void;
    onSaved: () => void;
    onProviderUpdated: (p: ProviderInfo) => void;
  }> = {},
) {
  const onClose = over.onClose ?? vi.fn();
  const onSaved = over.onSaved ?? vi.fn();
  const onProviderUpdated = over.onProviderUpdated ?? vi.fn();
  localCalls.list.length = 0;
  remoteCalls.list.length = 0;
  const rendered = render(
    <ModelManageModal
      provider={provider}
      open={over.open ?? true}
      onClose={onClose}
      onSaved={onSaved}
      onProviderUpdated={onProviderUpdated}
    />,
  );
  return { ...rendered, onClose, onSaved, onProviderUpdated };
}

describe("ModelManageModal - routing to the embedded local modal", () => {
  it("renders LocalModelManageModal for the qwenpaw-local provider", () => {
    const { container } = renderRouter(makeProvider("qwenpaw-local"));
    expect(container.querySelector(LOCAL_STUB)).toBeTruthy();
    expect(container.querySelector(REMOTE_STUB)).toBeNull();
  });

  it("never mounts the remote modal on the local branch", () => {
    renderRouter(makeProvider("qwenpaw-local"));
    expect(remoteCalls.list.length).toBe(0);
    expect(localCalls.list.length).toBe(1);
  });

  it("forwards provider, open, onClose and onSaved to the local modal", () => {
    const provider = makeProvider("qwenpaw-local");
    const onClose = vi.fn();
    const onSaved = vi.fn();
    renderRouter(provider, { open: true, onClose, onSaved });

    const props = localCalls.list[0] as Record<string, unknown>;
    expect(props.provider).toBe(provider);
    expect(props.open).toBe(true);
    expect(props.onClose).toBe(onClose);
    expect(props.onSaved).toBe(onSaved);
  });

  it("passes the open flag through as false when the caller closes it", () => {
    renderRouter(makeProvider("qwenpaw-local"), { open: false });
    const props = localCalls.list[0] as Record<string, unknown>;
    expect(props.open).toBe(false);
  });

  it("does NOT forward onProviderUpdated, which the local modal has no prop for", () => {
    renderRouter(makeProvider("qwenpaw-local"));
    const props = localCalls.list[0] as Record<string, unknown>;
    // LocalModelManageModalProps declares no such field; wiring it would be
    // dead code that hides a future refactor mistake.
    expect("onProviderUpdated" in props).toBe(false);
    expect(Object.keys(props).sort()).toEqual([
      "onClose",
      "onSaved",
      "open",
      "provider",
    ]);
  });
});

describe("ModelManageModal - routing to the remote modal", () => {
  it("renders RemoteModelManageModal for a cloud provider", () => {
    const { container } = renderRouter(makeProvider("dashscope"));
    expect(container.querySelector(REMOTE_STUB)).toBeTruthy();
    expect(container.querySelector(LOCAL_STUB)).toBeNull();
  });

  it("routes a custom provider to the remote modal", () => {
    renderRouter(makeProvider("custom-openai", { is_custom: true }));
    expect(remoteCalls.list.length).toBe(1);
    expect(localCalls.list.length).toBe(0);
  });

  it("routes copaw-local to the REMOTE modal, because only qwenpaw-local is special-cased", () => {
    // `index.tsx:152` counts copaw-local as embedded for list grouping, but
    // this router's condition is a literal id check. Pinning that keeps a
    // well-meaning "make it consistent" refactor from silently changing which
    // modal opens for that provider.
    const provider = makeProvider("copaw-local", { is_local: true });
    const { container } = renderRouter(provider);
    expect(container.querySelector(REMOTE_STUB)).toBeTruthy();
    expect(container.querySelector(LOCAL_STUB)).toBeNull();
  });

  it("routes by id, not by the is_local boolean", () => {
    // Counterpart of the case above: a local-flavoured provider that is not
    // the embedded one still goes remote.
    renderRouter(makeProvider("ollama", { is_local: true }));
    expect(remoteCalls.list.length).toBe(1);
    expect(localCalls.list.length).toBe(0);
  });

  it("forwards all five props to the remote modal", () => {
    const provider = makeProvider("dashscope");
    const onClose = vi.fn();
    const onSaved = vi.fn();
    const onProviderUpdated = vi.fn();
    renderRouter(provider, { open: true, onClose, onSaved, onProviderUpdated });

    const props = remoteCalls.list[0] as Record<string, unknown>;
    expect(props.provider).toBe(provider);
    expect(props.open).toBe(true);
    expect(props.onClose).toBe(onClose);
    expect(props.onSaved).toBe(onSaved);
    expect(props.onProviderUpdated).toBe(onProviderUpdated);
  });

  it("leaves onProviderUpdated undefined when the caller omits it", () => {
    const provider = makeProvider("dashscope");
    localCalls.list.length = 0;
    remoteCalls.list.length = 0;
    render(
      <ModelManageModal
        provider={provider}
        open
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
    );
    const props = remoteCalls.list[0] as Record<string, unknown>;
    // The child declares it optional, so omitting it must stay observable as
    // undefined rather than being replaced with a no-op wrapper.
    expect(props.onProviderUpdated).toBeUndefined();
  });
});

describe("ModelManageModal - switching providers re-routes", () => {
  it("swaps from the remote modal to the local one on rerender", () => {
    const provider = makeProvider("dashscope");
    const onClose = vi.fn();
    const onSaved = vi.fn();
    const { rerender, container } = render(
      <ModelManageModal
        provider={provider}
        open
        onClose={onClose}
        onSaved={onSaved}
        onProviderUpdated={vi.fn()}
      />,
    );
    expect(container.querySelector(REMOTE_STUB)).toBeTruthy();

    const local = makeProvider("qwenpaw-local");
    rerender(
      <ModelManageModal
        provider={local}
        open
        onClose={onClose}
        onSaved={onSaved}
        onProviderUpdated={vi.fn()}
      />,
    );
    expect(container.querySelector(LOCAL_STUB)).toBeTruthy();
    expect(container.querySelector(REMOTE_STUB)).toBeNull();
    const props = localCalls.list[localCalls.list.length - 1] as Record<
      string,
      unknown
    >;
    expect(props.provider).toBe(local);
  });
});

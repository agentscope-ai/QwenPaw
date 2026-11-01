// @vitest-environment jsdom
/**
 * ProviderCard - the two-way switch that stands in front of every provider
 * card in Settings > Models. Rendered from `pages/Settings/Models/index.tsx:292`
 * (`<ProviderCard ... />`, imported at `:15`) once per provider of four
 * different lists (cloud ungrouped, cloud grouped, local configured, custom).
 *
 * Visible contract under test:
 *
 *   1. routing is a single equality test on `provider.id === "qwenpaw-local"`:
 *      that one id goes to LocalProviderCard and EVERY other id goes to
 *      RemoteProviderCard, so the two branches are mutually exclusive and
 *      exactly one child mounts per render;
 *   2. the local branch receives a NARROWER prop set than the remote branch -
 *      only `provider` and `onOpenModels`. `onSaved` and `onOpenConfig` are
 *      deliberately not forwarded, because the embedded provider has no
 *      editable endpoint and no key to save; passing them through would let a
 *      future caller believe the local card can save;
 *   3. the remote branch receives all four props, and each callback reaches the
 *      child by identity (not a wrapper), so a parent that memoizes on the
 *      callback reference still works;
 *   4. the child is handed the very provider object the caller passed - identity,
 *      not a copy - because the children hand that same object back to
 *      `onOpenModels` / `onOpenConfig`;
 *   5. `activeModels` is declared in ProviderCardProps but is NOT forwarded to
 *      either child (measured, not assumed: neither destructures it). Pinned so
 *      that wiring it up later shows as a change rather than as silent drift;
 *   6. the component is `React.memo` WITHOUT a custom comparator: a re-render
 *      with prop-identical references does not re-run the body, while a
 *      structurally equal but newly allocated provider does. Both directions are
 *      pinned so that adding a comparator (or dropping the memo) shows up.
 *
 * Harness notes (measured facts):
 *
 * - both children are replaced with recorders that hand the props they receive
 *   back to the test. That is the only way to assert the prop-set asymmetry in
 *   (2) and the identity claims in (3)-(4): the real RemoteProviderCard pulls in
 *   the api client, the message hook, the OAuth modal and HubProviderUsage, so
 *   mounting it would turn a routing test into an integration test. Both children
 *   have their own suites (`LocalProviderCard.test.tsx`,
 *   `RemoteProviderCard.test.tsx`), so nothing is left uncovered by stubbing them
 *   here. `src/test/design-mock.ts` is untouched.
 * - the recorders return a stable element per call and count renders, which is
 *   what the memo cases in (6) read.
 * - ProviderCard itself calls no i18n, so no `react-i18next` mock is needed; the
 *   recorders deliberately render no label so that a mistaken extra render is
 *   visible as a count change and not as duplicate text.
 */
import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ProviderInfo } from "../../../../../api/types";

const h = vi.hoisted(() => ({
  localProps: null as Record<string, unknown> | null,
  remoteProps: null as Record<string, unknown> | null,
  localRenders: 0,
  remoteRenders: 0,
}));

vi.mock("./LocalProviderCard", () => ({
  LocalProviderCard: (props: Record<string, unknown>) => {
    h.localProps = props;
    h.localRenders += 1;
    return <div data-stub="local-provider-card" />;
  },
}));

vi.mock("./RemoteProviderCard", () => ({
  RemoteProviderCard: (props: Record<string, unknown>) => {
    h.remoteProps = props;
    h.remoteRenders += 1;
    return <div data-stub="remote-provider-card" />;
  },
}));

import { ProviderCard } from "./ProviderCard";

/**
 * A complete ProviderInfo. Each test states only what it varies; `id` defaults
 * to a remote provider so that the local branch has to be asked for explicitly.
 */
function providerOf(overrides: Partial<ProviderInfo> = {}): ProviderInfo {
  return {
    id: "openai",
    name: "OpenAI",
    api_key_prefix: "sk-",
    chat_model: "",
    models: [],
    extra_models: [],
    is_custom: false,
    is_local: false,
    support_model_discovery: true,
    support_connection_check: true,
    freeze_url: false,
    require_api_key: true,
    api_key: "sk-abc",
    base_url: "https://api.openai.com/v1",
    generate_kwargs: {},
    ...overrides,
  } as ProviderInfo;
}

function renderCard(
  provider: ProviderInfo,
  overrides: Record<string, unknown> = {},
) {
  const props = {
    provider,
    activeModels: null,
    onSaved: vi.fn(),
    onOpenConfig: vi.fn(),
    onOpenModels: vi.fn(),
    ...overrides,
  };
  const utils = render(
    <ProviderCard
      provider={props.provider}
      activeModels={props.activeModels}
      onSaved={props.onSaved}
      onOpenConfig={props.onOpenConfig}
      onOpenModels={props.onOpenModels}
    />,
  );
  return { ...props, ...utils };
}

const localStub = (container: HTMLElement) =>
  container.querySelector('[data-stub="local-provider-card"]');
const remoteStub = (container: HTMLElement) =>
  container.querySelector('[data-stub="remote-provider-card"]');

beforeEach(() => {
  h.localProps = null;
  h.remoteProps = null;
  h.localRenders = 0;
  h.remoteRenders = 0;
});

afterEach(() => {
  cleanup();
});

describe("ProviderCard routing", () => {
  it("routes the qwenpaw-local id to LocalProviderCard and mounts no remote card", () => {
    const { container } = renderCard(providerOf({ id: "qwenpaw-local" }));
    expect(localStub(container)).not.toBeNull();
    expect(remoteStub(container)).toBeNull();
  });

  it("routes every other id to RemoteProviderCard and mounts no local card", () => {
    const ids = ["openai", "hub-managed", "custom-1", "", "QWENPAW-LOCAL"];
    for (const id of ids) {
      const { container } = renderCard(providerOf({ id }));
      expect(remoteStub(container), `id ${JSON.stringify(id)}`).not.toBeNull();
      expect(localStub(container), `id ${JSON.stringify(id)}`).toBeNull();
      cleanup();
    }
  });

  it("mounts exactly one child card for one provider", () => {
    const { container } = renderCard(providerOf({ id: "qwenpaw-local" }));
    expect(container.querySelectorAll("[data-stub]").length).toBe(1);
  });
});

describe("ProviderCard prop sets", () => {
  it("hands the local branch only provider and onOpenModels", () => {
    renderCard(providerOf({ id: "qwenpaw-local" }));
    expect(h.localProps).not.toBeNull();
    expect(Object.keys(h.localProps ?? {}).sort()).toEqual([
      "onOpenModels",
      "provider",
    ]);
  });

  it("hands the remote branch all four props", () => {
    renderCard(providerOf());
    expect(h.remoteProps).not.toBeNull();
    expect(Object.keys(h.remoteProps ?? {}).sort()).toEqual([
      "onOpenConfig",
      "onOpenModels",
      "onSaved",
      "provider",
    ]);
  });

  it("forwards each callback to the remote branch by identity", () => {
    const onSaved = vi.fn();
    const onOpenConfig = vi.fn();
    const onOpenModels = vi.fn();
    renderCard(providerOf(), { onSaved, onOpenConfig, onOpenModels });
    expect(h.remoteProps?.onSaved).toBe(onSaved);
    expect(h.remoteProps?.onOpenConfig).toBe(onOpenConfig);
    expect(h.remoteProps?.onOpenModels).toBe(onOpenModels);
  });

  it("forwards onOpenModels to the local branch by identity", () => {
    const onOpenModels = vi.fn();
    renderCard(providerOf({ id: "qwenpaw-local" }), { onOpenModels });
    expect(h.localProps?.onOpenModels).toBe(onOpenModels);
  });

  it("hands the child the very provider object it was rendered with", () => {
    const provider = providerOf();
    renderCard(provider);
    expect(h.remoteProps?.provider).toBe(provider);
  });

  it("hands the local child the very provider object it was rendered with", () => {
    const provider = providerOf({ id: "qwenpaw-local" });
    renderCard(provider);
    expect(h.localProps?.provider).toBe(provider);
  });

  it("does not forward the declared-but-unused activeModels prop to either branch", () => {
    const activeModels = { active_llm: null };
    const local = renderCard(providerOf({ id: "qwenpaw-local" }), {
      activeModels,
    });
    expect(h.localProps).not.toBeNull();
    expect("activeModels" in (h.localProps ?? {})).toBe(false);
    cleanup();

    renderCard(providerOf(), { activeModels });
    expect(h.remoteProps).not.toBeNull();
    expect("activeModels" in (h.remoteProps ?? {})).toBe(false);
    expect(local.container).not.toBeNull();
  });
});

describe("ProviderCard memoization", () => {
  it("does not re-run the body when every prop reference is unchanged", () => {
    const provider = providerOf();
    const onSaved = vi.fn();
    const onOpenConfig = vi.fn();
    const onOpenModels = vi.fn();
    const { rerender } = render(
      <ProviderCard
        provider={provider}
        activeModels={null}
        onSaved={onSaved}
        onOpenConfig={onOpenConfig}
        onOpenModels={onOpenModels}
      />,
    );
    expect(h.remoteRenders).toBe(1);

    rerender(
      <ProviderCard
        provider={provider}
        activeModels={null}
        onSaved={onSaved}
        onOpenConfig={onOpenConfig}
        onOpenModels={onOpenModels}
      />,
    );
    expect(h.remoteRenders).toBe(1);
  });

  it("re-runs the body for a structurally equal but newly allocated provider", () => {
    const onSaved = vi.fn();
    const onOpenConfig = vi.fn();
    const onOpenModels = vi.fn();
    const { rerender } = render(
      <ProviderCard
        provider={providerOf()}
        activeModels={null}
        onSaved={onSaved}
        onOpenConfig={onOpenConfig}
        onOpenModels={onOpenModels}
      />,
    );
    expect(h.remoteRenders).toBe(1);

    rerender(
      <ProviderCard
        provider={providerOf()}
        activeModels={null}
        onSaved={onSaved}
        onOpenConfig={onOpenConfig}
        onOpenModels={onOpenModels}
      />,
    );
    expect(h.remoteRenders).toBe(2);
  });

  it("re-runs the body when a callback reference changes", () => {
    const provider = providerOf();
    const { rerender } = render(
      <ProviderCard
        provider={provider}
        activeModels={null}
        onSaved={vi.fn()}
        onOpenConfig={vi.fn()}
        onOpenModels={vi.fn()}
      />,
    );
    expect(h.remoteRenders).toBe(1);

    rerender(
      <ProviderCard
        provider={provider}
        activeModels={null}
        onSaved={vi.fn()}
        onOpenConfig={vi.fn()}
        onOpenModels={vi.fn()}
      />,
    );
    expect(h.remoteRenders).toBe(2);
  });

  it("re-runs the local body when the provider reference changes", () => {
    const onOpenModels = vi.fn();
    const { rerender } = render(
      <ProviderCard
        provider={providerOf({ id: "qwenpaw-local" })}
        activeModels={null}
        onSaved={vi.fn()}
        onOpenConfig={vi.fn()}
        onOpenModels={onOpenModels}
      />,
    );
    expect(h.localRenders).toBe(1);
    expect(h.remoteRenders).toBe(0);

    rerender(
      <ProviderCard
        provider={providerOf({ id: "qwenpaw-local" })}
        activeModels={null}
        onSaved={vi.fn()}
        onOpenConfig={vi.fn()}
        onOpenModels={onOpenModels}
      />,
    );
    expect(h.localRenders).toBe(2);
    expect(h.remoteRenders).toBe(0);
  });
});

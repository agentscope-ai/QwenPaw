/**
 * Unit tests for the OS-window scoped antd modal hook.
 *
 * What this file pins:
 * - Every one of the five dialog helpers (confirm / info / success / warning /
 *   error) forwards to the matching antd hook method, and nothing is crossed
 *   over (a `warning` call must not end up in `error`).
 * - Each helper injects `getContainer` so the dialog mounts inside the OS
 *   window instead of document.body. The container is the value from
 *   OsWindowContainerContext, resolved at call time.
 * - Outside an OS window the context is null, so `getContainer` is undefined
 *   and antd keeps its default body mount (the backward compatible path).
 * - The caller's own config wins over the injected container (the spread comes
 *   after), so a dialog that deliberately asks for document.body is honoured.
 * - The holder element from the antd hook is handed straight back, because
 *   dropping it means the dialogs never render.
 */
import React from "react";
import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => {
  const calls: Record<string, Array<Record<string, unknown>>> = {
    confirm: [],
    info: [],
    success: [],
    warning: [],
    error: [],
  };
  return {
    calls,
    holder: { kind: "holder-element" },
    instance: {} as Record<string, unknown>,
  };
});

vi.mock("antd", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("antd");
  const modal = {
    useModal: () => {
      const record = (name: string) => (config: Record<string, unknown>) => {
        h.calls[name].push(config);
        return { destroy: () => {} };
      };
      h.instance = {
        confirm: record("confirm"),
        info: record("info"),
        success: record("success"),
        warning: record("warning"),
        error: record("error"),
      };
      return [h.instance, h.holder];
    },
  };
  return { ...actual, Modal: Object.assign(actual.Modal as object, modal) };
});

const { OsWindowContainerContext } = await import("./osWindowContainer");
const { useOsModal } = await import("./useOsModal");

const renderWithContainer = (container: HTMLElement | null) =>
  renderHook(() => useOsModal(), {
    wrapper: ({ children }: { children: React.ReactNode }) => (
      <OsWindowContainerContext.Provider value={container}>
        {children}
      </OsWindowContainerContext.Provider>
    ),
  });

const totalCalls = () =>
  Object.values(h.calls).reduce((n, list) => n + list.length, 0);

describe("useOsModal", () => {
  let overlayRoot: HTMLElement;

  beforeEach(() => {
    Object.keys(h.calls).forEach((k) => {
      h.calls[k].length = 0;
    });
    overlayRoot = document.createElement("div");
    overlayRoot.id = "os-window-overlay";
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("hands back the antd holder untouched", () => {
    const { result } = renderWithContainer(overlayRoot);
    expect(result.current.holder).toBe(h.holder);
  });

  it("routes each helper to the matching antd method and only that one", () => {
    const { result } = renderWithContainer(overlayRoot);
    (["confirm", "info", "success", "warning", "error"] as const).forEach(
      (name, index) => {
        result.current[name]({ title: `t-${index}` });
      },
    );
    (["confirm", "info", "success", "warning", "error"] as const).forEach(
      (name, index) => {
        expect(h.calls[name]).toHaveLength(1);
        expect(h.calls[name][0].title).toBe(`t-${index}`);
      },
    );
    expect(totalCalls()).toBe(5);
  });

  it("injects the OS window container into every helper", () => {
    const { result } = renderWithContainer(overlayRoot);
    (["confirm", "info", "success", "warning", "error"] as const).forEach(
      (name) => {
        result.current[name]({});
      },
    );
    (["confirm", "info", "success", "warning", "error"] as const).forEach(
      (name) => {
        expect(h.calls[name][0].getContainer).toBe(overlayRoot);
      },
    );
  });

  it("leaves getContainer undefined outside an OS window", () => {
    const { result } = renderWithContainer(null);
    result.current.confirm({ title: "classic-layout" });
    expect(h.calls.confirm).toHaveLength(1);
    // The key is present with an undefined value: antd then uses its default
    // body mount, which is the backward compatible path for MainLayout.
    expect("getContainer" in h.calls.confirm[0]).toBe(true);
    expect(h.calls.confirm[0].getContainer).toBeUndefined();
    expect(h.calls.confirm[0].title).toBe("classic-layout");
  });

  it("lets an explicit getContainer from the caller win", () => {
    const { result } = renderWithContainer(overlayRoot);
    const own = document.createElement("section");
    result.current.info({ title: "pinned", getContainer: () => own });
    expect(h.calls.info[0].getContainer).not.toBe(overlayRoot);
    expect(typeof h.calls.info[0].getContainer).toBe("function");
    expect((h.calls.info[0].getContainer as () => HTMLElement)()).toBe(own);
    expect(h.calls.info[0].title).toBe("pinned");
  });

  it("picks up a container that only appears after the first render", () => {
    // The window overlay root mounts after the hook has already run, so the
    // value must be read from the latest render rather than captured once.
    const holder: { current: HTMLElement | null } = { current: null };
    const { result, rerender } = renderHook(() => useOsModal(), {
      wrapper: ({ children }: { children: React.ReactNode }) => (
        <OsWindowContainerContext.Provider value={holder.current}>
          {children}
        </OsWindowContainerContext.Provider>
      ),
    });
    result.current.confirm({ title: "before-mount" });
    expect(h.calls.confirm).toHaveLength(1);
    expect(h.calls.confirm[0].getContainer).toBeUndefined();

    const later = document.createElement("div");
    holder.current = later;
    rerender();
    result.current.confirm({ title: "after-mount" });
    expect(h.calls.confirm).toHaveLength(2);
    expect(h.calls.confirm[1].getContainer).toBe(later);
  });

  it("keeps the rest of the caller config intact", () => {
    const { result } = renderWithContainer(overlayRoot);
    const onOk = () => {};
    result.current.confirm({
      title: "delete",
      content: "are you sure",
      okText: "yes",
      cancelText: "no",
      okButtonProps: { danger: true },
      onOk,
    });
    const sent = h.calls.confirm[0];
    expect(sent.title).toBe("delete");
    expect(sent.content).toBe("are you sure");
    expect(sent.okText).toBe("yes");
    expect(sent.cancelText).toBe("no");
    expect(sent.okButtonProps).toEqual({ danger: true });
    expect(sent.onOk).toBe(onOk);
    expect(Object.keys(sent).sort()).toEqual(
      [
        "cancelText",
        "content",
        "getContainer",
        "okButtonProps",
        "okText",
        "onOk",
        "title",
      ].sort(),
    );
  });
});

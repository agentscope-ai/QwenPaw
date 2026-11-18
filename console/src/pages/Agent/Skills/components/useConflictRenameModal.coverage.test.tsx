/**
 * Unit tests for the useConflictRenameModal hook.
 *
 * The hook owns a promise-based modal: showConflictRenameModal(items) opens a
 * dialog with one prefilled input per conflicting skill and the returned
 * promise settles to a key -> trimmed-name map on confirm, or to null on
 * cancel. These tests assert that contract only.
 *
 * Two harness notes:
 *
 * 1. The shared @agentscope-ai/design stub renders Modal as a pass-through
 *    div that ignores `open`, so with the stub alone the dialog would always
 *    be present and every open/closed assertion would be testing the stub
 *    rather than the hook. The factory below overrides Modal with one that
 *    honours `open` and exposes onOk/onCancel as real buttons. Note that
 *    vi.importActual("@agentscope-ai/design") resolves through the vitest
 *    alias to that same shared stub (it is not the real component library),
 *    which is enough here: the hook only needs Modal and a plain Input.
 *
 * 2. src/test/setup.ts does not initialise i18next, so t(key) returns the key
 *    itself and t(key, options) drops the interpolation options. The row label
 *    therefore carries no observable text, and these tests deliberately do not
 *    assert on it: that string belongs to the i18n layer, not to this hook's
 *    contract. Row identity is asserted through the inputs instead.
 */
import { describe, it, expect, vi } from "vitest";
import {
  render,
  screen,
  fireEvent,
  act,
  waitFor,
} from "@testing-library/react";
import React from "react";

vi.mock("@agentscope-ai/design", async () => {
  const actual = await vi.importActual<any>("@agentscope-ai/design");
  const Modal = ({ open, title, children, onOk, onCancel, zIndex }: any) => {
    if (!open) return null;
    return React.createElement(
      "div",
      { role: "dialog", "data-zindex": String(zIndex) },
      React.createElement("h2", null, title),
      children,
      React.createElement(
        "button",
        { type: "button", "data-testid": "crm-ok", onClick: onOk },
        "confirm",
      ),
      React.createElement(
        "button",
        { type: "button", "data-testid": "crm-cancel", onClick: onCancel },
        "cancel",
      ),
    );
  };
  return { ...actual, Modal };
});

const { useConflictRenameModal } = await import("./useConflictRenameModal");
type ConflictItem = import("./useConflictRenameModal").ConflictItem;

const CONFLICTS: ConflictItem[] = [
  { key: "skill-a", label: "alpha", suggested_name: "alpha_1" },
  { key: "skill-b", label: "beta", suggested_name: "beta_1" },
];

/**
 * Renders the hook the way its consumers do: the returned node is mounted
 * beside a trigger button, and the promise result is handed to a spy so tests
 * can assert on the settlement value.
 */
function renderHookHarness(items: ConflictItem[] = CONFLICTS) {
  const onResolved = vi.fn();
  let show!: (
    incoming: ConflictItem[],
  ) => Promise<Record<string, string> | null>;

  function Harness() {
    const hook = useConflictRenameModal();
    show = hook.showConflictRenameModal;
    return React.createElement(
      "div",
      null,
      React.createElement(
        "button",
        {
          type: "button",
          "data-testid": "crm-trigger",
          onClick: () => {
            void hook.showConflictRenameModal(items).then(onResolved);
          },
        },
        "trigger",
      ),
      hook.conflictRenameModal,
    );
  }

  render(React.createElement(Harness));

  const open = async () => {
    await act(async () => {
      screen.getByTestId("crm-trigger").click();
    });
  };
  const confirm = async () => {
    await act(async () => {
      fireEvent.click(screen.getByTestId("crm-ok"));
    });
    await waitFor(() => expect(onResolved).toHaveBeenCalled());
  };
  const cancel = async () => {
    await act(async () => {
      fireEvent.click(screen.getByTestId("crm-cancel"));
    });
    await waitFor(() => expect(onResolved).toHaveBeenCalled());
  };
  const inputs = () =>
    Array.from(document.querySelectorAll<HTMLInputElement>("input"));
  const dialogs = () => document.querySelectorAll('[role="dialog"]');

  return {
    onResolved,
    open,
    confirm,
    cancel,
    inputs,
    dialogs,
    get show() {
      return show;
    },
  };
}

describe("useConflictRenameModal", () => {
  it("renders no dialog until showConflictRenameModal is called", () => {
    const { dialogs } = renderHookHarness();
    expect(dialogs()).toHaveLength(0);
    expect(document.querySelector("input")).toBeNull();
  });

  it("opens one dialog and keeps the trigger usable", async () => {
    const { dialogs, open } = renderHookHarness();
    await open();
    expect(dialogs()).toHaveLength(1);
    expect(screen.getByTestId("crm-trigger")).toBeInTheDocument();
  });

  it("renders one prefilled input per conflict, in the order given", async () => {
    const { inputs, open } = renderHookHarness();
    await open();
    expect(inputs()).toHaveLength(2);
    expect(inputs().map((input) => input.value)).toEqual(["alpha_1", "beta_1"]);
  });

  it("passes an explicit stacking order above the page chrome", async () => {
    const { dialogs, open } = renderHookHarness();
    await open();
    expect(dialogs()[0].getAttribute("data-zindex")).toBe("2100");
  });

  it("resolves with every suggested name keyed by conflict key on confirm", async () => {
    const { onResolved, open, confirm } = renderHookHarness();
    await open();
    await confirm();
    expect(onResolved).toHaveBeenCalledWith({
      "skill-a": "alpha_1",
      "skill-b": "beta_1",
    });
  });

  it("resolves with the typed name instead of the suggestion for an edited row", async () => {
    const { onResolved, inputs, open, confirm } = renderHookHarness();
    await open();
    fireEvent.change(inputs()[0], { target: { value: "renamed-skill" } });
    expect(inputs()[0].value).toBe("renamed-skill");
    await confirm();
    expect(onResolved).toHaveBeenCalledWith({
      "skill-a": "renamed-skill",
      "skill-b": "beta_1",
    });
  });

  it("trims surrounding whitespace from a typed name before resolving", async () => {
    const { onResolved, inputs, open, confirm } = renderHookHarness();
    await open();
    fireEvent.change(inputs()[1], { target: { value: "  padded-name  " } });
    await confirm();
    expect(onResolved).toHaveBeenCalledWith({
      "skill-a": "alpha_1",
      "skill-b": "padded-name",
    });
  });

  it("leaves a row out of the map when its name is cleared to whitespace", async () => {
    const { onResolved, inputs, open, confirm } = renderHookHarness();
    await open();
    fireEvent.change(inputs()[0], { target: { value: "   " } });
    await confirm();
    const resolved = onResolved.mock.calls[0][0];
    expect(resolved).toEqual({ "skill-b": "beta_1" });
    expect(Object.keys(resolved)).not.toContain("skill-a");
  });

  it("leaves every row out when all names are cleared", async () => {
    const { onResolved, inputs, open, confirm } = renderHookHarness();
    await open();
    fireEvent.change(inputs()[0], { target: { value: "" } });
    fireEvent.change(inputs()[1], { target: { value: " \t " } });
    await confirm();
    expect(onResolved).toHaveBeenCalledWith({});
  });

  it("resolves null on cancel and reports nothing about the typed names", async () => {
    const { onResolved, inputs, open, cancel } = renderHookHarness();
    await open();
    fireEvent.change(inputs()[0], { target: { value: "discarded" } });
    await cancel();
    expect(onResolved).toHaveBeenCalledWith(null);
  });

  it("closes the dialog after confirm", async () => {
    const { dialogs, open, confirm } = renderHookHarness();
    await open();
    expect(dialogs()).toHaveLength(1);
    await confirm();
    expect(dialogs()).toHaveLength(0);
  });

  it("closes the dialog after cancel", async () => {
    const { dialogs, open, cancel } = renderHookHarness();
    await open();
    expect(dialogs()).toHaveLength(1);
    await cancel();
    expect(dialogs()).toHaveLength(0);
  });

  it("prefills freshly suggested names when reopened after a confirm", async () => {
    const { inputs, open, confirm, show } = renderHookHarness();
    await open();
    fireEvent.change(inputs()[0], { target: { value: "stale-edit" } });
    await confirm();

    await act(async () => {
      void show([
        { key: "skill-c", label: "gamma", suggested_name: "gamma_1" },
      ]);
    });
    expect(inputs()).toHaveLength(1);
    expect(inputs()[0].value).toBe("gamma_1");
  });

  it("keeps the dialog closed for an empty conflict list", async () => {
    const { dialogs, open } = renderHookHarness([]);
    await open();
    expect(dialogs()).toHaveLength(0);
  });

  it("does not settle the promise while the dialog stays closed", async () => {
    const { onResolved, open } = renderHookHarness([]);
    await open();
    await act(async () => {
      await Promise.resolve();
    });
    expect(onResolved).not.toHaveBeenCalled();
  });
});

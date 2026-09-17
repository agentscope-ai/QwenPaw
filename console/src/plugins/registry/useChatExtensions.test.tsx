/**
 * useChatExtensions.test.tsx — React-side integration of the registry.
 *
 * Renders a tiny component that consumes the hooks, then mutates the
 * registry and asserts the component re-renders with new values.
 * Avoids the heavy ChatPage mock setup (worker-crash-prone).
 */
import { describe, it, expect, beforeEach } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { chatExtensions } from "./chatExtensions";
import { auditStore } from "./audit";
import {
  useChatScalarSnapshot,
  useChatListSnapshot,
} from "./useChatExtensions";
import { PluginSlotBoundary } from "./PluginSlotBoundary";
import { resolveLocalized } from "./types";

beforeEach(() => {
  chatExtensions.__resetForTests();
  auditStore.clear();
});

function Probe() {
  const scalar = useChatScalarSnapshot();
  const lists = useChatListSnapshot();
  return (
    <div>
      <span data-testid="greeting">
        {String(
          resolveLocalized(scalar["welcome.greeting"]?.value, "en") ?? "",
        )}
      </span>
      <span data-testid="nick">
        {String(resolveLocalized(scalar["welcome.nick"]?.value, "en") ?? "")}
      </span>
      <span data-testid="rightHeader-count">
        {String(lists["header.rightHeader"].length)}
      </span>
      <span data-testid="actions-count">{String(lists.actions.length)}</span>
    </div>
  );
}

describe("useChatExtensions hooks", () => {
  it("re-renders Probe when a plugin sets a scalar", () => {
    render(<Probe />);
    expect(screen.getByTestId("greeting").textContent).toBe("");

    act(() => {
      chatExtensions.setScalar("p1", "welcome.greeting", "Hello P1");
    });

    expect(screen.getByTestId("greeting").textContent).toBe("Hello P1");
  });

  it("last-writer-wins propagates to the Probe", () => {
    render(<Probe />);
    act(() => {
      chatExtensions.setScalar("p1", "welcome.greeting", "P1");
      chatExtensions.setScalar("p2", "welcome.greeting", "P2");
    });
    expect(screen.getByTestId("greeting").textContent).toBe("P2");
  });

  it("dispose() of the winner falls back to the prior", () => {
    let disposeP2!: () => void;
    render(<Probe />);
    act(() => {
      chatExtensions.setScalar("p1", "welcome.greeting", "P1");
      const d = chatExtensions.setScalar("p2", "welcome.greeting", "P2");
      disposeP2 = () => d.dispose();
    });
    expect(screen.getByTestId("greeting").textContent).toBe("P2");
    act(() => disposeP2());
    expect(screen.getByTestId("greeting").textContent).toBe("P1");
  });

  it("additive list mutations propagate", () => {
    render(<Probe />);
    expect(screen.getByTestId("actions-count").textContent).toBe("0");
    act(() => {
      chatExtensions.addAction("p1", { id: "a1", onClick: () => {} });
      chatExtensions.addAction("p2", { id: "a2", onClick: () => {} });
    });
    expect(screen.getByTestId("actions-count").textContent).toBe("2");
  });
});

describe("PluginSlotBoundary", () => {
  function Boom(): never {
    throw new Error("kaboom");
  }

  it("renders children when they don't throw", () => {
    render(
      <PluginSlotBoundary slot="test" pluginId="p1">
        <span data-testid="child">ok</span>
      </PluginSlotBoundary>,
    );
    expect(screen.getByTestId("child")).toBeInTheDocument();
  });

  it("renders fallback and writes audit when child throws", () => {
    render(
      <PluginSlotBoundary
        slot="header.rightHeader"
        pluginId="evil"
        fallback={<span data-testid="fb">fallback</span>}
      >
        <Boom />
      </PluginSlotBoundary>,
    );
    expect(screen.getByTestId("fb")).toBeInTheDocument();
    expect(
      auditStore
        .overrides()
        .some(
          (r) =>
            r.kind === "chat.error" &&
            r.pluginId === "evil" &&
            r.field === "header.rightHeader",
        ),
    ).toBe(true);
  });
});

/**
 * Slot.test.tsx — <Slot> component + SlotErrorBoundary.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { render, act } from "@testing-library/react";
import { Slot } from "../Slot";
import { slotRegistry } from "../store";
import { auditStore } from "../audit";

beforeEach(() => {
  slotRegistry.__resetForTests();
  auditStore.clear();
});

describe("<Slot kind='fill'>", () => {
  it("renders children (host default) when no fills", () => {
    const { getByTestId } = render(
      <Slot name="x" kind="fill">
        <span data-testid="default">D</span>
      </Slot>,
    );
    expect(getByTestId("default")).toBeInTheDocument();
  });

  it("renders children then plugin fills in order", () => {
    slotRegistry.fill("p1", "x", () => <span data-testid="p1">P1</span>, {
      order: 100,
    });
    slotRegistry.fill("p2", "x", () => <span data-testid="p2">P2</span>, {
      order: 200,
    });
    const { getByTestId, container } = render(
      <Slot name="x" kind="fill">
        <span data-testid="default">D</span>
      </Slot>,
    );
    expect(getByTestId("default")).toBeInTheDocument();
    expect(getByTestId("p1")).toBeInTheDocument();
    expect(getByTestId("p2")).toBeInTheDocument();
    const texts = Array.from(container.querySelectorAll("span")).map(
      (e) => e.textContent,
    );
    expect(texts).toEqual(["D", "P1", "P2"]);
  });

  it("re-renders when a fill is added after mount", () => {
    const { container } = render(<Slot name="x" kind="fill" />);
    expect(container.textContent).toBe("");
    act(() => {
      slotRegistry.fill("p1", "x", () => <span>P1</span>);
    });
    expect(container.textContent).toBe("P1");
  });
});

describe("<Slot kind='replace'>", () => {
  it("renders children when no replace", () => {
    const { getByTestId } = render(
      <Slot name="x" kind="replace">
        <span data-testid="default">D</span>
      </Slot>,
    );
    expect(getByTestId("default")).toBeInTheDocument();
  });

  it("plugin replace overrides children", () => {
    slotRegistry.replace("p1", "x", () => <span data-testid="plugin">P</span>);
    const { getByTestId, queryByTestId } = render(
      <Slot name="x" kind="replace">
        <span data-testid="default">D</span>
      </Slot>,
    );
    expect(getByTestId("plugin")).toBeInTheDocument();
    expect(queryByTestId("default")).not.toBeInTheDocument();
  });
});

describe("SlotErrorBoundary", () => {
  function Boom(): never {
    throw new Error("plugin boom");
  }

  it("catches throwing plugin render + writes audit + falls back", () => {
    slotRegistry.fill("evil", "x", () => <Boom />, { id: "evil.boom" });
    const { container } = render(
      <Slot name="x" kind="fill">
        <span data-testid="default">D</span>
      </Slot>,
    );
    // Default still rendered; plugin output replaced by null (fallback).
    expect(container.textContent).toBe("D");
    expect(
      auditStore
        .overrides()
        .some((r) => r.kind === "slot.error" && r.pluginId === "evil"),
    ).toBe(true);
  });
});

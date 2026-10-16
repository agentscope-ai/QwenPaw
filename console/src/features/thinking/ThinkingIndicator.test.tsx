import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { FxTierProvider } from "../../contexts/FxTierContext";
import { ThinkingIndicator } from "./ThinkingIndicator";
import type { ThinkingControlSpec } from "./types";

// jsdom has no layout, so useInView reports false and the decorative loop
// would never start; mock it visible so the loop actually runs in tests.
vi.mock("motion/react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("motion/react")>();
  return { ...actual, useInView: () => true };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
const control: ThinkingControlSpec = {
  kind: "budget",
  efforts: [],
  supports_off: true,
  budget_min: 1000,
  budget_max: 10000,
};

it("expresses exact budgets as accessible depth without exposing raw numbers", () => {
  const { rerender } = render(
    <ThinkingIndicator
      control={control}
      value={{ level: "budget", budget_tokens: 1000 }}
    />,
  );
  expect(
    screen.getByRole("img", { name: "thinkingControl.light" }),
  ).toBeInTheDocument();
  rerender(
    <ThinkingIndicator
      control={control}
      value={{ level: "budget", budget_tokens: 10000 }}
    />,
  );
  expect(
    screen.getByRole("img", { name: "thinkingControl.intensive" }),
  ).toBeInTheDocument();
  expect(screen.queryByText("10000")).not.toBeInTheDocument();
});

it.each(["off", "inherit"] as const)(
  "shows the resolved %s state without a fabricated water level",
  (level) => {
    render(<ThinkingIndicator control={control} value={{ level }} />);
    expect(
      screen.getByRole("img", { name: `thinkingControl.${level}` }),
    ).toBeInTheDocument();
  },
);

it.each(["unknown", "unsupported"] as const)(
  "does not imply thinking for %s models",
  (kind) => {
    render(
      <ThinkingIndicator
        control={{ ...control, kind }}
        value={{ level: "high" }}
      />,
    );
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  },
);

it("keeps the static liquid fill but no infinite wave loop in the off tier", async () => {
  localStorage.setItem("qwenpaw-fx-tier", "off");
  try {
    const { container } = render(
      <FxTierProvider>
        <ThinkingIndicator
          control={control}
          value={{ level: "budget", budget_tokens: 5000 }}
        />
      </FxTierProvider>,
    );
    // The state cue (img + liquid fill) stays visible...
    expect(
      screen.getByRole("img", { name: "thinkingControl.balanced" }),
    ).toBeInTheDocument();
    // ...while the infinite wave/rotation loops are static. Sample every
    // SVG transform twice: with an active infinite loop at least one
    // transform keeps moving between samples.
    const collect = () =>
      Array.from(container.querySelectorAll("svg *")).map(
        (node) => (node as SVGElement).style.transform,
      );
    await new Promise((resolve) => setTimeout(resolve, 80));
    const first = collect();
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(collect()).toEqual(first);
  } finally {
    localStorage.removeItem("qwenpaw-fx-tier");
  }
});

it("uses independent clipping and gradient IDs for multiple model controls", () => {
  const { container } = render(
    <>
      <ThinkingIndicator
        control={control}
        value={{ level: "budget", budget_tokens: 2000 }}
      />
      <ThinkingIndicator
        control={control}
        value={{ level: "budget", budget_tokens: 8000 }}
      />
    </>,
  );
  const ids = Array.from(container.querySelectorAll("[id]"), (node) => node.id);
  expect(new Set(ids).size).toBe(ids.length);
});

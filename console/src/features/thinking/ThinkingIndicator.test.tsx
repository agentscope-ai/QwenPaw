import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ThinkingIndicator } from "./ThinkingIndicator";
import type { ThinkingControlSpec } from "./types";

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
  "hides %s without removing the reserved slot",
  (level) => {
    const { container } = render(
      <ThinkingIndicator control={control} value={{ level }} />,
    );
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(container.firstElementChild).toBeEmptyDOMElement();
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

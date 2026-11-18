import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { NumberStepper } from "./NumberStepper";
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
function Example() {
  const [value, setValue] = useState<number | null>(0.5);
  return (
    <NumberStepper
      aria-label="Delay"
      value={value}
      onChange={setValue}
      min={0.5}
      max={1}
      step={0.25}
    />
  );
}
describe("NumberStepper", () => {
  it("clamps steps at both bounds and preserves precise entry", () => {
    render(<Example />);
    expect(
      screen.getByRole("button", { name: "common.decrease" }),
    ).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "common.increase" }));
    expect(screen.getByRole("spinbutton", { name: "Delay" })).toHaveValue(
      "0.75",
    );
    fireEvent.click(screen.getByRole("button", { name: "common.increase" }));
    expect(
      screen.getByRole("button", { name: "common.increase" }),
    ).toBeDisabled();
    fireEvent.change(screen.getByRole("spinbutton"), {
      target: { value: "0.8" },
    });
    expect(screen.getByRole("spinbutton")).toHaveValue("0.80");
  });
});

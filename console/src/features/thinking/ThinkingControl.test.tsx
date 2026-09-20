import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ThinkingControl } from "./ThinkingControl";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe("ThinkingControl", () => {
  it("preserves exact numeric budgets and commits once editing ends", () => {
    const changed = vi.fn();
    render(
      <ThinkingControl
        control={{
          kind: "budget",
          efforts: [],
          supports_off: true,
          budget_min: 1024,
          budget_max: 32768,
        }}
        value={{ level: "budget", budget_tokens: 4096 }}
        onChange={changed}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "thinkingControl.budget" }),
    );
    const input = screen.getByRole("spinbutton", {
      name: "thinkingControl.budget",
    });
    fireEvent.change(input, { target: { value: "12345" } });
    expect(changed).not.toHaveBeenCalled();
    fireEvent.blur(input);
    expect(changed).toHaveBeenCalledWith({
      level: "budget",
      budget_tokens: 12345,
    });
    fireEvent.click(
      screen.getByRole("button", { name: "thinkingControl.reset" }),
    );
    expect(changed).toHaveBeenLastCalledWith({ level: "inherit" });
  });
  it("uses only model-declared efforts and omits unsupported off", () => {
    const changed = vi.fn();
    render(
      <ThinkingControl
        control={{
          kind: "effort",
          efforts: ["low", "high", "max"],
          supports_off: false,
        }}
        value={{ level: "low" }}
        onChange={changed}
      />,
    );
    const slider = screen.getByRole("slider");
    fireEvent.keyDown(slider, { key: "End", keyCode: 35 });
    fireEvent.keyUp(slider, { key: "End", keyCode: 35 });
    expect(changed).toHaveBeenLastCalledWith({ level: "max" });
    expect(
      screen.queryByRole("button", { name: "thinkingControl.off" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
  });
});

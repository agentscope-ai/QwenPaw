import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PolicySelector } from "./PolicySelector";

const options = [
  {
    value: "foreground",
    label: "Foreground",
    description: "Wait for tool output",
  },
  {
    value: "background",
    label: "Background",
    description: "Continue other work",
  },
];

describe("PolicySelector", () => {
  it("exposes the selected option and calls the requested choice", () => {
    const onChange = vi.fn();
    render(
      <PolicySelector
        label="Execution"
        value="foreground"
        options={options}
        onChange={onChange}
      />,
    );
    expect(
      (screen.getByRole("radio", { name: "Foreground" }) as HTMLInputElement)
        .checked,
    ).toBe(true);
    expect(screen.getByText("Wait for tool output")).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: "Background" }));
    expect(onChange).toHaveBeenCalledWith("background");
  });
  it("keeps disabled choices out of normal interaction", () => {
    render(
      <PolicySelector
        label="Execution"
        value="foreground"
        options={options}
        onChange={vi.fn()}
        disabled
      />,
    );
    for (const input of screen.getAllByRole("radio"))
      expect((input as HTMLInputElement).disabled).toBe(true);
  });
  it("disables an unavailable option without disabling the active choice", () => {
    render(
      <PolicySelector
        label="Execution"
        value="foreground"
        options={options.map((option) => ({
          ...option,
          disabled: option.value === "background",
        }))}
        onChange={vi.fn()}
      />,
    );
    expect(
      (screen.getByRole("radio", { name: "Background" }) as HTMLInputElement)
        .disabled,
    ).toBe(true);
    expect(
      (screen.getByRole("radio", { name: "Foreground" }) as HTMLInputElement)
        .disabled,
    ).toBe(false);
  });
});

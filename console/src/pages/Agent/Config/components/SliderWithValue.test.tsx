import { describe, it, expect, vi } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";
import { SliderWithValue } from "./SliderWithValue";

// JSDOM does not implement the animated custom element lifecycle.
vi.mock("@number-flow/react", () => ({
  default: ({
    value,
    format,
  }: {
    value: number;
    format: Intl.NumberFormatOptions;
  }) => <span>{new Intl.NumberFormat("en", format).format(value)}</span>,
}));

describe("SliderWithValue", () => {
  it("renders without crashing", () => {
    const { container } = renderWithProviders(
      <SliderWithValue value={0.5} min={0} max={1} step={0.01} />,
    );
    expect(container).toBeTruthy();
  });

  it("displays formatted value: toString for >= 1, two decimals for < 1", () => {
    const { rerender } = renderWithProviders(
      <SliderWithValue value={0.75} min={0} max={2} step={0.01} />,
    );
    expect(screen.getByText("0.75")).toBeInTheDocument();

    rerender(<SliderWithValue value={2} min={0} max={2} step={0.01} />);
    expect(screen.getByText("2")).toBeInTheDocument();

    // toString preserves decimals (does not truncate to integer)
    rerender(<SliderWithValue value={1.5} min={0} max={2} step={0.01} />);
    expect(screen.getByText("1.5")).toBeInTheDocument();
  });

  it("calls onChange when slider value changes", () => {
    const handleChange = vi.fn();
    renderWithProviders(
      <SliderWithValue
        value={0.5}
        min={0}
        max={1}
        step={0.01}
        onChange={handleChange}
      />,
    );

    const slider = screen.getByRole("slider");
    fireEvent.keyDown(slider, { key: "ArrowRight", keyCode: 39 });
    expect(handleChange).toHaveBeenCalledWith(0.51);
  });
});

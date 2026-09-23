import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { NumberSlider } from "./NumberSlider";

vi.mock("@number-flow/react", () => ({
  default: ({ value }: { value: number }) => <span>{value}</span>,
}));
function Example() {
  const [value, setValue] = useState(10);
  return (
    <NumberSlider
      value={value}
      onChange={setValue}
      min={0}
      max={100}
      label="Display length"
    />
  );
}
describe("NumberSlider", () => {
  it("keeps keyboard adjustment and exact input in sync", async () => {
    render(<Example />);
    const slider = screen.getByRole("slider", { name: "Display length" });
    fireEvent.keyDown(slider, { key: "ArrowRight", keyCode: 39 });
    await waitFor(() => expect(slider).toHaveAttribute("aria-valuenow", "11"));
    fireEvent.click(screen.getByRole("button", { name: "Display length" }));
    fireEvent.change(
      screen.getByRole("spinbutton", { name: "Display length" }),
      { target: { value: "45" } },
    );
    expect(slider).toHaveAttribute("aria-valuenow", "45");
    fireEvent.keyDown(screen.getByRole("spinbutton"), {
      key: "Enter",
      keyCode: 13,
    });
    expect(
      screen.getByRole("button", { name: "Display length" }),
    ).toHaveTextContent("45");
  });
});

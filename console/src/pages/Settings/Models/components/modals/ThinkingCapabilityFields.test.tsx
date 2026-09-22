import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ThinkingCapabilityFields } from "./ThinkingCapabilityFields";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe("manual thinking declarations", () => {
  it("clears an inherited default when the user changes budget bounds", () => {
    const onChange = vi.fn();
    render(
      <ThinkingCapabilityFields
        value={{
          kind: "budget",
          efforts: [],
          supports_off: false,
          budget_min: 10,
          budget_max: 8000,
          budget_default: 4096,
        }}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByText("thinkingControl.declaration"));
    fireEvent.change(screen.getByLabelText("thinkingControl.maximum"), {
      target: { value: "2000" },
    });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ budget_max: 2000, budget_default: undefined }),
    );
  });

  it("keeps missing metadata automatic without inventing controls", () => {
    render(<ThinkingCapabilityFields onChange={vi.fn()} />);
    fireEvent.click(screen.getByText("thinkingControl.declaration"));
    expect(
      screen.getByText("thinkingControl.type.unknown"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
  });
});

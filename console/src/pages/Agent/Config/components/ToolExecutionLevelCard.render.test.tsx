import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import { ToolExecutionLevelCard } from "./ToolExecutionLevelCard";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback || _key,
  }),
}));

describe("ToolExecutionLevelCard", () => {
  it("emits one change when a radio option is selected", () => {
    const onChange = vi.fn();
    renderWithProviders(
      <ToolExecutionLevelCard value="AUTO" onChange={onChange} />,
    );

    fireEvent.click(screen.getByRole("radio", { name: /SMART/i }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("SMART");
  });
});

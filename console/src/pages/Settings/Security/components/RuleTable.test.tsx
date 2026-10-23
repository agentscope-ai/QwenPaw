import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RuleTable } from "./RuleTable";
import type { MergedRule } from "../useToolGuard";
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string }) =>
      options?.defaultValue || key,
  }),
}));
vi.mock("@number-flow/react", () => ({
  default: ({ value }: { value: number }) => <span>{value}</span>,
}));
const rule = {
  id: "rule-a",
  category: "files",
  severity: "HIGH",
  description: "Protect files",
  source: "builtin",
  disabled: false,
  autoDeny: false,
} as MergedRule;
describe("RuleTable categories", () => {
  it("opens a category, filters descriptions, and keeps the two controls distinct", async () => {
    const toggle = vi.fn(),
      deny = vi.fn();
    render(
      <RuleTable
        rules={[rule]}
        enabled
        onToggleRule={toggle}
        onToggleAutoDeny={deny}
        onPreviewRule={vi.fn()}
        onEditRule={vi.fn()}
        onDeleteRule={vi.fn()}
      />,
    );
    expect(screen.queryByText("rule-a")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /files/ }));
    const dialog = within(await screen.findByRole("dialog"));
    fireEvent.click(
      dialog.getByRole("switch", { name: "security.rules.autoDeny: rule-a" }),
    );
    expect(deny).toHaveBeenCalledWith("rule-a", false);
    expect(toggle).not.toHaveBeenCalled();
    fireEvent.click(
      dialog.getByRole("switch", { name: "security.enabled: rule-a" }),
    );
    expect(toggle).toHaveBeenCalledWith("rule-a", false);
    fireEvent.change(dialog.getByRole("textbox"), {
      target: { value: "missing" },
    });
    expect(dialog.queryByText("rule-a")).not.toBeInTheDocument();
    fireEvent.change(dialog.getByRole("textbox"), {
      target: { value: "Protect" },
    });
    expect(dialog.getByText("rule-a")).toBeInTheDocument();
  });
  it("does not present configured rules as active while the master protection is off", async () => {
    render(
      <RuleTable
        rules={[rule]}
        enabled={false}
        onToggleRule={vi.fn()}
        onToggleAutoDeny={vi.fn()}
        onPreviewRule={vi.fn()}
        onEditRule={vi.fn()}
        onDeleteRule={vi.fn()}
      />,
    );
    const category = screen.getByRole("button", { name: /files/ });
    expect(within(category).getByText("0")).toBeInTheDocument();
    expect(within(category).getByText("common.disabled")).toBeInTheDocument();
    fireEvent.click(category);
    const dialog = within(await screen.findByRole("dialog"));
    expect(
      dialog.getByRole("switch", { name: "security.enabled: rule-a" }),
    ).toBeDisabled();
    expect(
      dialog.getByRole("switch", { name: "security.enabled: rule-a" }),
    ).toBeChecked();
  });
});

import type { ComponentProps } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PoolSkillCard } from "./PoolSkillCard";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@agentscope-ai/design", async () => {
  const { Button, Checkbox, Tooltip } = await import("antd");
  return { Button, Checkbox, Tooltip };
});

vi.mock("@/components/CommunityFeedback", () => ({
  CommunityFeedback: () => null,
  hasCommunityFeedback: () => false,
}));

function renderCard(
  overrides: Partial<ComponentProps<typeof PoolSkillCard>> = {},
) {
  const props = {
    skill: { name: "browser", source: "builtin" },
    isSelected: false,
    batchModeEnabled: false,
    onToggleSelect: vi.fn(),
    onEdit: vi.fn(),
    onBroadcast: vi.fn(),
    onDelete: vi.fn(),
    onAutomationQuickAction: vi.fn(),
    ...overrides,
  };
  return { ...render(<PoolSkillCard {...props} />), props };
}

describe("PoolSkillCard click handling", () => {
  it.each(["label", "icon"])(
    "deletes through the portalled menu %s without opening the card",
    async (target) => {
      const user = userEvent.setup();
      const { container, props } = renderCard();

      await user.click(screen.getByRole("button", { name: "common.actions" }));

      expect(props.onEdit).not.toHaveBeenCalled();
      const menuItem = await screen.findByRole("menuitem", {
        name: "skillPool.delete",
      });
      expect(container).not.toContainElement(menuItem);
      await user.click(
        target === "icon" ? menuItem.querySelector("svg")! : menuItem,
      );

      expect(props.onDelete).toHaveBeenCalledExactlyOnceWith(props.skill);
      expect(props.onEdit).not.toHaveBeenCalled();
      expect(props.onToggleSelect).not.toHaveBeenCalled();
    },
  );

  it.each(["body", "title"])(
    "still opens the skill once when clicking its %s",
    async (target) => {
      const user = userEvent.setup();
      const { props } = renderCard();

      await user.click(
        target === "title"
          ? screen.getByRole("button", { name: "browser" })
          : screen.getByText("skillPool.builtin"),
      );

      expect(props.onEdit).toHaveBeenCalledExactlyOnceWith(props.skill);
      expect(props.onDelete).not.toHaveBeenCalled();
    },
  );

  it("selects the card in batch mode without opening skill details", async () => {
    const user = userEvent.setup();
    const { props } = renderCard({ batchModeEnabled: true });

    await user.click(screen.getByText("skillPool.builtin"));

    expect(props.onToggleSelect).toHaveBeenCalledExactlyOnceWith("browser");
    expect(props.onEdit).not.toHaveBeenCalled();
    expect(props.onDelete).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("button", { name: "common.actions" }),
    ).not.toBeInTheDocument();
  });
});

import type { ComponentProps } from "react";
import { render, screen, within } from "@testing-library/react";
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
  it("moves the four actions into the menu without switches or footer buttons", async () => {
    const user = userEvent.setup();
    const { container } = renderCard();

    expect(
      screen.queryByRole("button", { name: "skillPool.broadcast" }),
    ).not.toBeInTheDocument();
    expect(
      container.querySelector('[data-testid^="skill-automation-"]'),
    ).toBeNull();

    await user.click(screen.getByRole("button", { name: "common.actions" }));

    expect(
      screen.getAllByRole("menuitem").map((item) => item.textContent),
    ).toEqual([
      "skillPool.autoSync",
      "skillPool.builtinAutoUpdate",
      "skillPool.broadcast",
      "skillPool.delete",
    ]);
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  });

  it.each([
    ["skillPool.autoSync", "auto_sync"],
    ["skillPool.builtinAutoUpdate", "auto_update"],
  ] as const)("toggles %s without opening the card", async (label, setting) => {
    const user = userEvent.setup();
    const { props } = renderCard();

    await user.click(screen.getByRole("button", { name: "common.actions" }));
    await user.click(screen.getByRole("menuitem", { name: label }));

    expect(props.onAutomationQuickAction).toHaveBeenCalledExactlyOnceWith(
      props.skill,
      setting,
    );
    expect(props.onEdit).not.toHaveBeenCalled();
    expect(props.onToggleSelect).not.toHaveBeenCalled();
    expect(props.onDelete).not.toHaveBeenCalled();
  });

  it("broadcasts from the menu without opening skill details", async () => {
    const user = userEvent.setup();
    const { props } = renderCard();

    await user.click(screen.getByRole("button", { name: "common.actions" }));
    await user.click(
      screen.getByRole("menuitem", { name: "skillPool.broadcast" }),
    );

    expect(props.onBroadcast).toHaveBeenCalledExactlyOnceWith(props.skill);
    expect(props.onEdit).not.toHaveBeenCalled();
  });

  it("only marks the enabled setting and hides auto update for custom skills", async () => {
    const user = userEvent.setup();
    renderCard({
      skill: { name: "custom", source: "local", auto_sync: true },
    });

    await user.click(screen.getByRole("button", { name: "common.actions" }));

    expect(
      within(
        screen.getByRole("menuitem", { name: /skillPool.autoSync/ }),
      ).getByLabelText("common.enabled"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("menuitem", { name: /skillPool.builtinAutoUpdate/ }),
    ).not.toBeInTheDocument();
  });

  it("disables menu mutations while an automation update is pending", async () => {
    const user = userEvent.setup();
    const { props } = renderCard({ automationPending: true });

    await user.click(screen.getByRole("button", { name: "common.actions" }));
    for (const item of screen.getAllByRole("menuitem")) {
      expect(item).toHaveAttribute("aria-disabled", "true");
      await user.click(item);
    }

    expect(props.onAutomationQuickAction).not.toHaveBeenCalled();
    expect(props.onBroadcast).not.toHaveBeenCalled();
    expect(props.onDelete).not.toHaveBeenCalled();
    expect(props.onEdit).not.toHaveBeenCalled();
  });

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

describe("PoolSkillCard description", () => {
  it("explains a historical builtin without marking it as outdated", async () => {
    const user = userEvent.setup();
    renderCard({
      skill: { name: "legacy", source: "builtin", sync_status: "removed" },
    });

    const status = screen.getByText("skillPool.statusRemoved");
    expect(status).toHaveAttribute("tabindex", "0");
    expect(
      screen.queryByText("skillPool.statusOutdated"),
    ).not.toBeInTheDocument();

    await user.hover(status);

    expect(await screen.findByRole("tooltip")).toHaveTextContent(
      "skillPool.statusRemovedHint",
    );
  });

  it("shows the description after its status with one keyboard-accessible hint", async () => {
    const user = userEvent.setup();
    const description =
      "A long skill description that remains available in full.";
    renderCard({
      skill: {
        name: "browser",
        source: "builtin",
        description,
        sync_status: "outdated",
      },
    });

    const summary = screen.getByText(description);
    expect(
      screen
        .getByText("skillPool.statusOutdated")
        .compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    const help = screen.getByRole("button", { name: description });
    await user.tab(); // Actions
    await user.tab(); // Skill title
    await user.tab(); // Description help
    expect(help).toHaveFocus();
    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent(description);

    await user.hover(summary);

    expect(summary).not.toHaveAttribute("tabindex");
    expect(summary).not.toHaveAttribute("aria-describedby");
    expect(screen.getAllByRole("tooltip")).toEqual([tooltip]);
  });

  it("uses the existing fallback when the description is missing", () => {
    renderCard();

    expect(screen.getByText("skills.noDescription")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "skills.noDescription" }),
    ).toBeInTheDocument();
  });
});

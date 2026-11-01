import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SkillsToolbar } from "./SkillsToolbar";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@agentscope-ai/design", async () => {
  const antd = await vi.importActual<typeof import("antd")>("antd");
  return { Input: antd.Input, Select: antd.Select };
});

function ToolbarHarness({ allTags }: { allTags: string[] }) {
  const [searchTags, setSearchTags] = useState<string[]>([]);
  const [filterOpen, setFilterOpen] = useState(false);

  return (
    <SkillsToolbar
      searchQuery=""
      onSearchChange={vi.fn()}
      searchTags={searchTags}
      onTagsChange={setSearchTags}
      allTags={allTags}
      filterOpen={filterOpen}
      onFilterOpenChange={setFilterOpen}
      viewMode="card"
      onViewModeChange={vi.fn()}
    />
  );
}

describe("SkillsToolbar tag filter", () => {
  it("closes the empty tag popup when Escape is pressed", async () => {
    const user = userEvent.setup();
    render(<ToolbarHarness allTags={[]} />);

    const tagFilter = screen.getByRole("combobox", {
      name: "skills.filterByTag",
    });
    await user.pointer({ keys: "[MouseLeft]", target: tagFilter });
    expect(tagFilter).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("skills.noTags")).toBeInTheDocument();
    expect(tagFilter).toHaveFocus();

    await user.keyboard("{Escape}");

    expect(tagFilter).toHaveAttribute("aria-expanded", "false");
  });

  it("closes the populated tag popup when Escape is pressed", async () => {
    const user = userEvent.setup();
    render(<ToolbarHarness allTags={["automation"]} />);

    const tagFilter = screen.getByRole("combobox", {
      name: "skills.filterByTag",
    });
    await user.pointer({ keys: "[MouseLeft]", target: tagFilter });
    expect(tagFilter).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByRole("button", { name: "automation" }),
    ).toBeInTheDocument();
    expect(tagFilter).toHaveFocus();

    await user.keyboard("{Escape}");

    expect(tagFilter).toHaveAttribute("aria-expanded", "false");
  });

  it("keeps outside pointer dismissal working", async () => {
    const user = userEvent.setup();
    render(<ToolbarHarness allTags={["automation"]} />);

    const tagFilter = screen.getByRole("combobox", {
      name: "skills.filterByTag",
    });
    await user.pointer({ keys: "[MouseLeft]", target: tagFilter });
    expect(tagFilter).toHaveAttribute("aria-expanded", "true");

    await user.pointer({ keys: "[MouseLeft]", target: document.body });

    expect(tagFilter).toHaveAttribute("aria-expanded", "false");
  });
});

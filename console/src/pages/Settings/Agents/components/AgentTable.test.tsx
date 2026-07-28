import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AgentSummary } from "@/api/types/agents";
import { renderWithProviders } from "@/test/common_setup";
import { AgentTable } from "./AgentTable";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const agent = (id: string, pinned: boolean): AgentSummary => ({
  id,
  name: id,
  description: "",
  workspace_dir: "",
  enabled: true,
  pinned,
  startup_status: "running",
});

describe("AgentTable", () => {
  it("uses click-specific labels for pin actions", () => {
    renderWithProviders(
      <AgentTable
        agents={[agent("unpinned", false), agent("pinned", true)]}
        loading={false}
        reordering={false}
        onEdit={vi.fn()}
        onCopy={vi.fn()}
        onDelete={vi.fn()}
        onToggle={vi.fn()}
        onPin={vi.fn()}
        onReorder={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", { name: "agent.pinAgent" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "agent.unpinAgent" }),
    ).toBeInTheDocument();
  });

  it("keeps Copy enabled for default agent with template tooltip", () => {
    renderWithProviders(
      <AgentTable
        agents={[agent("default", true), agent("custom", false)]}
        loading={false}
        reordering={false}
        onEdit={vi.fn()}
        onCopy={vi.fn()}
        onDelete={vi.fn()}
        onToggle={vi.fn()}
        onPin={vi.fn()}
        onReorder={vi.fn()}
      />,
    );

    const defaultCopy = screen.getByTitle("agent.copyDefaultTooltip");
    expect(defaultCopy).toBeEnabled();
    expect(screen.getByTitle("agent.copyTooltip")).toBeEnabled();
  });
});

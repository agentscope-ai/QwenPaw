import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AgentSummary } from "@/api/types/agents";
import { renderWithProviders } from "@/test/common_setup";
import { AgentTable } from "./AgentTable";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const agent = (
  id: string,
  pinned: boolean,
  backend: AgentSummary["backend"] = "qwenpaw",
): AgentSummary => ({
  id,
  name: id,
  description: "",
  workspace_dir: "",
  enabled: true,
  backend,
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

  it("does not size the scroll area from the browser viewport", () => {
    const { container } = renderWithProviders(
      <AgentTable
        agents={[agent("a", false)]}
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

    // Regression guard: the table body height must come from the container
    // (measured), never from 100vh, so OS windows don't nest scrollbars.
    expect(container.innerHTML).not.toContain("100vh");
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

    expect(screen.getByTitle("agent.copyDefaultTooltip")).toBeEnabled();
    expect(screen.getByTitle("agent.copyTooltip")).toBeEnabled();
  });

  it("shows each agent runtime backend", () => {
    renderWithProviders(
      <AgentTable
        agents={[
          agent("native", false),
          agent("coding", false, "codex"),
          agent("qoder", false, "qoder"),
        ]}
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

    expect(screen.getByText(/QwenPaw/)).toBeInTheDocument();
    expect(screen.getByText(/Codex/)).toBeInTheDocument();
    expect(screen.getByText(/Qoder/)).toBeInTheDocument();
  });
});

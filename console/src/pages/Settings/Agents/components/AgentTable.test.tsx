import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
        onRename={vi.fn().mockResolvedValue(undefined)}
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
        onRename={vi.fn().mockResolvedValue(undefined)}
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
        onRename={vi.fn().mockResolvedValue(undefined)}
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
        onRename={vi.fn().mockResolvedValue(undefined)}
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

  it("edits an agent name inline without opening the edit modal", async () => {
    const onRename = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(
      <AgentTable
        agents={[agent("custom", false)]}
        loading={false}
        reordering={false}
        onRename={onRename}
        onCopy={vi.fn()}
        onDelete={vi.fn()}
        onToggle={vi.fn()}
        onPin={vi.fn()}
        onReorder={vi.fn()}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: "agent.editName" }),
    );
    const input = screen.getByRole("textbox", { name: "agent.name" });
    await userEvent.clear(input);
    await userEvent.type(input, "Renamed");
    await userEvent.click(
      screen.getByRole("button", { name: "agent.saveName" }),
    );

    expect(onRename).toHaveBeenCalledWith("custom", "Renamed");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("cancels an inline name edit without saving", async () => {
    const onRename = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(
      <AgentTable
        agents={[agent("custom", false)]}
        loading={false}
        reordering={false}
        onRename={onRename}
        onCopy={vi.fn()}
        onDelete={vi.fn()}
        onToggle={vi.fn()}
        onPin={vi.fn()}
        onReorder={vi.fn()}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: "agent.editName" }),
    );
    await userEvent.type(
      screen.getByRole("textbox", { name: "agent.name" }),
      "{Escape}",
    );

    expect(onRename).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("textbox", { name: "agent.name" }),
    ).not.toBeInTheDocument();
  });
});

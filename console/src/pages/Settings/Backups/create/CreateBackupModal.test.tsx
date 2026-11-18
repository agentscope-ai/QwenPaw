// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CreateBackupModal from "./CreateBackupModal";
const runner = vi.hoisted(() => ({
  loading: false,
  progress: 0,
  progressMsg: "",
  start: vi.fn(),
  reset: vi.fn(),
  resume: vi.fn(),
  cancel: vi.fn(),
}));
vi.mock("../shared/useBackupRunner", () => ({ useBackupRunner: () => runner }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@number-flow/react", () => ({
  default: ({ value }: { value: number }) => <span>{value}</span>,
}));
const agents = ["one", "two"].map((id) => ({
  id,
  name: id,
  description: "",
  workspace_dir: `/workspace/${id}`,
  enabled: true,
  backend: "qwenpaw",
}));

beforeEach(() => vi.clearAllMocks());
describe("backup scope selection", () => {
  it("uses every agent after switching from an empty partial selection to full", async () => {
    render(
      <CreateBackupModal
        open
        agents={agents}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />,
    );
    expect(
      (
        screen.getByPlaceholderText(
          "backup.namePlaceholder",
        ) as HTMLInputElement
      ).value,
    ).toMatch(/^Backup /);
    expect(runner.reset).toHaveBeenCalledTimes(1);
    fireEvent.click(
      screen.getByRole("radio", { name: "backup.partialBackup" }),
    );
    fireEvent.click(
      screen.getByRole("checkbox", { name: "backup.scopeAgents" }),
    );
    expect(
      screen.getByRole("checkbox", { name: "backup.scopeAgents" }),
    ).not.toBeChecked();
    fireEvent.click(screen.getByRole("radio", { name: "backup.fullBackup" }));
    fireEvent.click(screen.getByRole("button", { name: "common.confirm" }));
    expect(runner.start).toHaveBeenCalledWith(
      expect.objectContaining({
        agents: ["one", "two"],
        scope: {
          include_agents: true,
          include_global_config: true,
          include_skill_pool: true,
          include_secrets: true,
        },
      }),
    );
  });
  it("retains partial choices when comparing with the full scope", async () => {
    render(
      <CreateBackupModal
        open
        agents={agents}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByPlaceholderText("backup.namePlaceholder"), {
      target: { value: "Scope test" },
    });
    fireEvent.click(
      screen.getByRole("radio", { name: "backup.partialBackup" }),
    );
    fireEvent.click(
      screen.getByRole("checkbox", { name: "backup.scopeGlobalConfig" }),
    );
    fireEvent.click(screen.getByRole("radio", { name: "backup.fullBackup" }));
    fireEvent.click(
      screen.getByRole("radio", { name: "backup.partialBackup" }),
    );
    expect(
      screen.getByRole("checkbox", { name: "backup.scopeGlobalConfig" }),
    ).not.toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: "backup.scopeSecrets" }),
    ).not.toBeChecked();
    expect(runner.start).not.toHaveBeenCalled();
  });
});

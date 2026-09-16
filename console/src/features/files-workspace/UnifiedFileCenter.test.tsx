import { renderWithProviders } from "@/test/common_setup";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../../i18n";
import UnifiedFileCenter from "./UnifiedFileCenter";

vi.mock("./TemporaryAttachmentsPanel", () => ({
  default: () => <div>attachment-panel</div>,
}));
vi.mock("./PersonalLibraryPanel", () => ({
  default: () => <div>library-panel</div>,
}));
vi.mock("./ArtifactPanel", () => ({
  default: ({ onOpen }: { onOpen?: (locator: unknown) => void }) => <div>
    artifact-panel
    <button onClick={() => onOpen?.({
      category: "artifact",
      agentId: "agent-a",
      stableId: "d817638b-2710-422f-91b6-949908c4199b",
      relativePath: "report.md",
    })}>查看产物</button>
  </div>,
}));
vi.mock("./AgentConfigPanel", () => ({
  default: () => <div>agent-config-panel</div>,
}));
vi.mock("./MemoryPanel", () => ({
  default: () => <div>memory-panel</div>,
}));
vi.mock("./FilePreviewPane", () => ({
  default: ({ locator }: { locator: { relativePath: string } }) => <div>preview:{locator.relativePath}</div>,
}));

describe("UnifiedFileCenter", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("zh");
  });

  it("shows the five business file categories in their fixed order", () => {
    renderWithProviders(
      <UnifiedFileCenter
        agentId="agent-a"
        requestContext={{ agentId: "agent-a" }}
      />,
    );

    expect(
      screen.getAllByRole("tab").map((tab) => tab.textContent),
    ).toEqual(["临时附件", "个人资料库", "产物", "Agent 配置", "记忆"]);
    expect(screen.queryByRole("tab", { name: "档案" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "知识库" })).not.toBeInTheDocument();
  });

  it("opens the memory category selected by a deep link locator", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <UnifiedFileCenter
        agentId="agent-a"
        requestContext={{ agentId: "agent-a" }}
        initialLocator={{
          category: "memory",
          agentId: "agent-a",
          relativePath: "2026-09-15/topic.md",
          memoryScope: "private",
          memorySection: "daily",
        }}
      />,
    );

    expect(screen.getByText("memory-panel")).toBeVisible();
    await user.click(screen.getByRole("tab", { name: "产物" }));
    expect(screen.getByText("artifact-panel")).toBeVisible();
  });

  it("uses the shared preview pane when a category item is opened", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <UnifiedFileCenter agentId="agent-a" requestContext={{ agentId: "agent-a" }} />,
    );
    await user.click(screen.getByRole("tab", { name: "产物" }));
    await user.click(screen.getByRole("button", { name: "查看产物" }));
    expect(screen.getByText("preview:report.md")).toBeVisible();
  });
});

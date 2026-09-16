import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../../i18n";
import PersonalWorkspaceNavigator from "./PersonalWorkspaceNavigator";

vi.mock("./TemporaryAttachmentsPanel", () => ({
  default: () => <div>temporary-panel</div>,
}));
vi.mock("./FilesWorkspace", () => ({
  default: ({
    profileOnly,
    rootDirectory,
  }: {
    profileOnly?: boolean;
    rootDirectory?: string;
  }) => <div>workspace:{profileOnly ? "agent-profile" : rootDirectory}</div>,
}));
vi.mock("./ArtifactPanel", () => ({
  default: () => <div>artifact-panel</div>,
}));
vi.mock("./MemoryPanel", () => ({
  default: () => <div>memory-panel</div>,
}));

describe("PersonalWorkspaceNavigator", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("zh");
  });

  it("switches between the five unified file categories", async () => {
    const user = userEvent.setup();
    render(
      <PersonalWorkspaceNavigator
        agentId="agent-a"
        requestContext={{ agentId: "agent-a" }}
      />,
    );

    expect(screen.getByRole("tab", { name: "临时附件" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "个人资料库" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Agent 配置" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "产物" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "记忆" })).toBeVisible();
    expect(screen.getByText("temporary-panel")).toBeVisible();

    await user.click(screen.getByRole("tab", { name: "Agent 配置" }));
    const agentProfileWorkspace = screen.getByText("workspace:agent-profile");
    expect(agentProfileWorkspace).toBeVisible();
    expect(
      getComputedStyle(agentProfileWorkspace.parentElement as Element).display,
    ).toBe("flex");

    await user.click(screen.getByRole("tab", { name: "产物" }));

    expect(screen.getByText("artifact-panel")).toBeVisible();
  });

  it("fills the available Files page width instead of shrinking to tab content", () => {
    const { container } = render(
      <PersonalWorkspaceNavigator
        agentId="agent-a"
        requestContext={{ agentId: "agent-a" }}
      />,
    );

    expect(container.firstElementChild).toHaveStyle({
      flex: "1 1 auto",
      width: "100%",
      minWidth: "0",
    });

    const tabs = container.querySelector(".ant-tabs");
    expect(tabs).not.toBeNull();
    expect(getComputedStyle(tabs as Element).display).toBe("flex");
    expect(getComputedStyle(tabs as Element).flexDirection).toBe("column");
  });
});

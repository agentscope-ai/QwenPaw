import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/common_setup";

import FilesPage from "./index";

const mocks = vi.hoisted(() => ({
  openWorkspaceButton: vi.fn(),
}));

vi.mock("../../features/files-workspace/FilesWorkspace", () => ({
  default: () => <div>files-workspace</div>,
}));

vi.mock("../../features/files-workspace/OpenWorkspaceButton", () => ({
  OpenWorkspaceButton: ({ agentId }: { agentId: string | null }) => {
    mocks.openWorkspaceButton(agentId);
    return <div data-testid="open-workspace-agent">{agentId}</div>;
  },
}));

vi.mock("../../stores/agentStore", () => ({
  useAgentStore: () => ({ selectedAgent: "default" }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe("FilesPage", () => {
  it("opens the selected agent workspace", () => {
    renderWithProviders(<FilesPage />);

    expect(screen.getByTestId("open-workspace-agent")).toHaveTextContent(
      "default",
    );
  });
});

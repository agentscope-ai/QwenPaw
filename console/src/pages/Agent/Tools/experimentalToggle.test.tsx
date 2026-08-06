import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import type React from "react";
import type { ToolInfo } from "../../../api/modules/tools";

const hoisted = vi.hoisted(() => ({
  saveToolConfig: vi.fn().mockResolvedValue(undefined),
  loadTools: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("./useTools", () => ({
  useTools: () => ({
    tools: [
      {
        name: "browser",
        enabled: true,
        description: "Browser automation",
        async_execution: false,
        icon: "🌐",
        config_values: { experimental: false },
      } satisfies ToolInfo,
    ],
    loading: false,
    batchLoading: false,
    toggleEnabled: vi.fn(),
    toggleAsyncExecution: vi.fn(),
    enableAll: vi.fn(),
    disableAll: vi.fn(),
    loadTools: hoisted.loadTools,
    saveToolConfig: hoisted.saveToolConfig,
  }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@agentscope-ai/design", () => ({
  Card: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Switch: ({
    checked,
    onChange,
    checkedChildren,
    unCheckedChildren,
  }: {
    checked: boolean;
    onChange: (checked: boolean) => void;
    checkedChildren?: React.ReactNode;
    unCheckedChildren?: React.ReactNode;
  }) => (
    <button
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
    >
      {checked ? checkedChildren : unCheckedChildren}
    </button>
  ),
  Empty: () => <div />,
  Button: ({
    children,
    onClick,
  }: {
    children: React.ReactNode;
    onClick?: () => void;
  }) => <button onClick={onClick}>{children}</button>,
  Modal: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Form: Object.assign(
    ({ children }: { children: React.ReactNode }) => <form>{children}</form>,
    {
      useForm: () => [{}],
      Item: ({ children }: { children: React.ReactNode }) => (
        <div>{children}</div>
      ),
    },
  ),
  Input: Object.assign(() => <input />, { Password: () => <input /> }),
  InputNumber: () => <input />,
  Select: Object.assign(() => <select />, { Option: () => <option /> }),
}));

vi.mock("@/components/PageHeader", () => ({
  PageHeader: () => <div />,
}));

import ToolsPage, { BrowserExperimentalToggle } from "./index";

function ToggleHarness({
  initialExperimental,
}: {
  initialExperimental: boolean;
}) {
  const [experimental, setExperimental] = useState(initialExperimental);
  return (
    <BrowserExperimentalToggle
      toolName="browser"
      experimental={experimental}
      onChange={setExperimental}
    />
  );
}

describe("BrowserExperimentalToggle", () => {
  it("shows the selected unified-browser mode after enabling it", async () => {
    render(<ToggleHarness initialExperimental={false} />);

    fireEvent.click(
      screen.getByRole("button", { name: "tools.browserLegacyModeButton" }),
    );

    await waitFor(() => {
      expect(
        screen.getByRole("button", {
          name: "tools.browserUnifiedModeButton",
        }),
      ).toBeInTheDocument();
    });
  });

  it("shows the selected legacy compatibility mode after disabling it", async () => {
    render(<ToggleHarness initialExperimental />);

    fireEvent.click(
      screen.getByRole("button", {
        name: "tools.browserUnifiedModeButton",
      }),
    );

    await waitFor(() => {
      expect(
        screen.getByRole("button", {
          name: "tools.browserLegacyModeButton",
        }),
      ).toBeInTheDocument();
    });
  });

  it("hides the toggle for the retired browser_use identity", () => {
    const { container } = render(
      <BrowserExperimentalToggle
        toolName="browser_use"
        experimental={false}
        onChange={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("persists a Browser-card change through updateToolConfig's hook", async () => {
    render(<ToolsPage />);

    fireEvent.click(
      screen.getByRole("button", { name: "tools.browserLegacyModeButton" }),
    );

    await waitFor(() => {
      expect(hoisted.saveToolConfig).toHaveBeenCalledWith("browser", {
        experimental: true,
      });
    });
  });
});

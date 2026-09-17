import React from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  selectedAgent: "public-agent",
  agents: [
    {
      id: "public-agent",
      access_role: "user",
      can_edit: false,
    },
  ],
}));

const useChannelsMock = vi.hoisted(() => vi.fn());

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../../../stores/agentStore", () => ({
  useAgentStore: () => state,
}));

vi.mock("../../../api", () => ({
  default: {
    getAclAllPending: vi.fn().mockResolvedValue([]),
  },
}));

vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { success: vi.fn(), error: vi.fn() },
    modal: { confirm: vi.fn() },
  }),
}));

vi.mock("@/components/PageHeader", () => ({
  PageHeader: ({ center, extra }: { center?: React.ReactNode; extra?: React.ReactNode }) => (
    <header>
      {center}
      {extra}
    </header>
  ),
}));

vi.mock("@agentscope-ai/design", () => ({
  Form: {
    useForm: () => [{ setFieldsValue: vi.fn(), submit: vi.fn() }],
  },
}));

vi.mock("antd", () => ({
  Badge: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  Button: ({ children, onClick }: { children: React.ReactNode; onClick?: () => void }) => (
    <button onClick={onClick}>{children}</button>
  ),
  Space: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("@ant-design/icons", () => ({
  SafetyOutlined: () => null,
  AuditOutlined: () => null,
}));

vi.mock("./components", () => ({
  useChannels: useChannelsMock,
  getChannelLabel: (key: string) => key,
  ChannelCard: () => null,
  ChannelAvailableItem: () => null,
  ChannelDrawer: () => null,
  AccessControlDrawer: () => null,
  PendingApprovalsDrawer: () => null,
}));

import ChannelsPage from "./index";

describe("ChannelsPage personal binding mode", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    state.selectedAgent = "public-agent";
    state.agents = [
      { id: "public-agent", access_role: "user", can_edit: false },
    ];
    useChannelsMock.mockReturnValue({
      channels: {},
      orderedKeys: [],
      channelSchemas: {},
      isBuiltin: () => true,
      loading: false,
      fetchChannels: vi.fn(),
    });
  });

  it("public Agent user sees only their own channel bindings", () => {
    render(<ChannelsPage />);

    expect(screen.getByText("channels.myBindings")).toBeInTheDocument();
    expect(screen.queryByText("channels.agentChannels")).not.toBeInTheDocument();
    expect(screen.queryByText("channels.manageAccessControl")).not.toBeInTheDocument();
    expect(useChannelsMock).toHaveBeenCalledWith("user");
  });
});

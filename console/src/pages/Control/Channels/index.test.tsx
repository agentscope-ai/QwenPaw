// @vitest-environment jsdom
import type { ComponentProps, ReactNode } from "react";
import { act, fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";

const mocks = vi.hoisted(() => {
  const formValues: Record<string, unknown> = {};
  const formReset = vi.fn();
  const formSet = vi.fn();
  const formApi = {
    resetFields: () => {
      for (const key of Object.keys(formValues)) delete formValues[key];
      formReset();
    },
    setFieldsValue: (values: Record<string, unknown>) => {
      Object.assign(formValues, values);
      formSet(values);
    },
  };
  return {
    fetchChannels: vi.fn(),
    checkChannelConflict: vi.fn(),
    getAclAllPending: vi.fn(),
    setChannels: vi.fn(),
    updateChannelConfig: vi.fn(),
    useChannels: vi.fn(),
    formValues,
    formReset,
    formSet,
    formApi,
    modalConfirm: vi.fn(),
    channelDrawerProps: null as null | {
      open: boolean;
      initialValues?: Record<string, unknown>;
      onClose: () => void;
      onSubmit: (values: Record<string, unknown>) => Promise<void | boolean>;
    },
    aclDrawerProps: null as null | {
      open: boolean;
      ownerAgentId: string | null;
      canMutate: (ownerAgentId: string) => boolean;
      onStale: () => void;
    },
    pendingDrawerProps: null as null | {
      open: boolean;
      ownerAgentId: string | null;
      canMutate: (ownerAgentId: string) => boolean;
      onStale: () => void;
    },
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../../../api", () => ({
  default: {
    checkChannelConflict: (...args: unknown[]) =>
      mocks.checkChannelConflict(...args),
    getAclAllPending: (...args: unknown[]) => mocks.getAclAllPending(...args),
    updateChannelConfig: (...args: unknown[]) =>
      mocks.updateChannelConfig(...args),
  },
}));

vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ modal: { confirm: mocks.modalConfirm } }),
}));

vi.mock("@/components/PageHeader", () => ({
  PageHeader: ({
    center,
    extra,
  }: {
    center?: ReactNode;
    extra?: ReactNode;
  }) => (
    <header>
      {center}
      {extra}
    </header>
  ),
}));

vi.mock("@/components/interaction/Cascade", () => ({
  Cascade: ({ children }: { children?: ReactNode }) => <>{children}</>,
}));

vi.mock("@agentscope-ai/design", () => ({
  Form: {
    useForm: () => [mocks.formApi],
  },
}));

vi.mock("antd", () => ({
  App: ({ children }: { children?: ReactNode }) => <>{children}</>,
  Badge: ({ children }: { children?: ReactNode }) => <>{children}</>,
  Button: ({
    children,
    icon,
    ...props
  }: ComponentProps<"button"> & { icon?: ReactNode }) => (
    <button type="button" {...props}>
      {icon}
      {children}
    </button>
  ),
  Space: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
}));

vi.mock("./components", () => ({
  AccessControlDrawer: (props: NonNullable<typeof mocks.aclDrawerProps>) => {
    mocks.aclDrawerProps = props;
    return props.open ? <div data-testid="acl-drawer" /> : null;
  },
  ChannelAvailableItem: ({
    channelKey,
    onClick,
  }: {
    channelKey: string;
    onClick: () => void;
  }) => <button onClick={onClick}>{`available-${channelKey}`}</button>,
  ChannelCard: ({
    channelKey,
    onClick,
  }: {
    channelKey: string;
    onClick: () => void;
  }) => <button onClick={onClick}>{`channel-${channelKey}`}</button>,
  ChannelFormDrawer: (props: NonNullable<typeof mocks.channelDrawerProps>) => {
    mocks.channelDrawerProps = props;
    return props.open ? <div data-testid="channel-drawer" /> : null;
  },
  PendingApprovalsDrawer: (
    props: NonNullable<typeof mocks.pendingDrawerProps>,
  ) => {
    mocks.pendingDrawerProps = props;
    return props.open ? <div data-testid="pending-drawer" /> : null;
  },
  getChannelLabel: (key: string) => key,
  useChannels: () => mocks.useChannels(),
}));

import ChannelsPage from "./index";

function channelsState(overrides: Record<string, unknown> = {}) {
  return {
    agentId: "agent-a",
    channels: {},
    orderedKeys: [],
    channelSchemas: {},
    isBuiltin: vi.fn(() => true),
    loading: false,
    error: null,
    ready: true,
    canMutate: vi.fn(() => true),
    fetchChannels: mocks.fetchChannels,
    setChannels: mocks.setChannels,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.aclDrawerProps = null;
  mocks.pendingDrawerProps = null;
  mocks.channelDrawerProps = null;
  for (const key of Object.keys(mocks.formValues)) {
    delete mocks.formValues[key];
  }
  mocks.getAclAllPending.mockResolvedValue([]);
  mocks.checkChannelConflict.mockResolvedValue({ conflict: false });
  mocks.modalConfirm.mockReturnValue({ destroy: vi.fn(), update: vi.fn() });
  mocks.useChannels.mockReturnValue(channelsState());
});

describe("ChannelsPage load recovery", () => {
  it("blocks channel actions on failure and retries into a legitimate empty state", () => {
    mocks.useChannels.mockReturnValue(
      channelsState({
        error: new Error("offline"),
        ready: false,
        canMutate: vi.fn(() => false),
      }),
    );
    const view = renderWithProviders(<ChannelsPage />);

    expect(screen.getByRole("alert")).toHaveTextContent("channels.loadFailed");
    expect(
      screen.queryByRole("button", { name: "channels.goEnableChannels" }),
    ).toBeNull();
    expect(
      screen.getByRole("button", { name: "channels.pendingApprovals" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "channels.manageAccessControl" }),
    ).toBeDisabled();
    expect(mocks.updateChannelConfig).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
    expect(mocks.fetchChannels).toHaveBeenCalledOnce();

    mocks.useChannels.mockReturnValue(
      channelsState({
        channels: { dingtalk: { enabled: false, isBuiltin: true } },
        orderedKeys: ["dingtalk"],
      }),
    );
    view.rerender(<ChannelsPage />);

    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("channels.noEnabledChannels")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "channels.goEnableChannels" }),
    ).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "available-dingtalk" }));
    expect(screen.getByTestId("channel-drawer")).toBeInTheDocument();
  });

  it("does not render the empty CTA before the initial request succeeds", () => {
    mocks.useChannels.mockReturnValue(
      channelsState({ loading: true, ready: false }),
    );
    renderWithProviders(<ChannelsPage />);

    expect(screen.getByText("channels.loading")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "channels.goEnableChannels" }),
    ).toBeNull();
  });

  it("closes agent-owned drawers on switch and reloads safely for stale callbacks", () => {
    let currentAgent = "agent-a";
    mocks.useChannels.mockReturnValue(
      channelsState({
        agentId: currentAgent,
        canMutate: (ownerAgentId: string) => ownerAgentId === currentAgent,
      }),
    );
    const view = renderWithProviders(<ChannelsPage />);

    fireEvent.click(
      screen.getByRole("button", { name: "channels.manageAccessControl" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "channels.pendingApprovals" }),
    );
    expect(screen.getByTestId("acl-drawer")).toBeInTheDocument();
    expect(screen.getByTestId("pending-drawer")).toBeInTheDocument();
    const staleAcl = mocks.aclDrawerProps!;
    const stalePending = mocks.pendingDrawerProps!;

    currentAgent = "agent-b";
    mocks.useChannels.mockReturnValue(
      channelsState({
        agentId: currentAgent,
        loading: true,
        ready: false,
        canMutate: (ownerAgentId: string) => ownerAgentId === currentAgent,
      }),
    );
    view.rerender(<ChannelsPage />);

    expect(screen.queryByTestId("acl-drawer")).toBeNull();
    expect(screen.queryByTestId("pending-drawer")).toBeNull();
    expect(staleAcl.canMutate(staleAcl.ownerAgentId!)).toBe(false);
    expect(stalePending.canMutate(stalePending.ownerAgentId!)).toBe(false);
    staleAcl.onStale();
    stalePending.onStale();
    expect(mocks.fetchChannels).toHaveBeenCalledTimes(2);

    mocks.useChannels.mockReturnValue(
      channelsState({
        agentId: currentAgent,
        canMutate: (ownerAgentId: string) => ownerAgentId === currentAgent,
      }),
    );
    view.rerender(<ChannelsPage />);
    fireEvent.click(
      screen.getByRole("button", { name: "channels.manageAccessControl" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "channels.pendingApprovals" }),
    );
    expect(mocks.aclDrawerProps?.ownerAgentId).toBe("agent-b");
    expect(mocks.pendingDrawerProps?.ownerAgentId).toBe("agent-b");
    expect(screen.getByTestId("acl-drawer")).toBeInTheDocument();
    expect(screen.getByTestId("pending-drawer")).toBeInTheDocument();
  });

  it("provides only the current agent channel config to the form owner", async () => {
    let currentAgent = "agent-a";
    mocks.useChannels.mockReturnValue(
      channelsState({
        agentId: currentAgent,
        channels: {
          dingtalk: {
            enabled: true,
            isBuiltin: true,
            client_id: "agent-a-client",
            client_secret: "agent-a-secret",
            app_secret: "agent-a-app-secret",
            bot_token: "agent-a-bot-token",
            password: "agent-a-password",
          },
        },
        orderedKeys: ["dingtalk"],
        canMutate: (ownerAgentId: string) => ownerAgentId === currentAgent,
      }),
    );
    const view = renderWithProviders(<ChannelsPage />);

    fireEvent.click(screen.getByRole("button", { name: "channel-dingtalk" }));
    expect(mocks.channelDrawerProps?.initialValues).toMatchObject({
      client_secret: "agent-a-secret",
      app_secret: "agent-a-app-secret",
      bot_token: "agent-a-bot-token",
      password: "agent-a-password",
    });

    currentAgent = "agent-b";
    mocks.useChannels.mockReturnValue(
      channelsState({
        agentId: currentAgent,
        loading: true,
        ready: false,
        canMutate: (ownerAgentId: string) => ownerAgentId === currentAgent,
      }),
    );
    view.rerender(<ChannelsPage />);
    expect(screen.queryByTestId("channel-drawer")).not.toBeInTheDocument();

    mocks.useChannels.mockReturnValue(
      channelsState({
        agentId: currentAgent,
        channels: {
          dingtalk: {
            enabled: true,
            isBuiltin: true,
            client_id: "agent-b-client",
          },
        },
        orderedKeys: ["dingtalk"],
        canMutate: (ownerAgentId: string) => ownerAgentId === currentAgent,
      }),
    );
    view.rerender(<ChannelsPage />);
    fireEvent.click(screen.getByRole("button", { name: "channel-dingtalk" }));

    expect(mocks.channelDrawerProps?.initialValues).toMatchObject({
      client_id: "agent-b-client",
    });
    expect(mocks.channelDrawerProps?.initialValues).not.toHaveProperty(
      "client_secret",
    );
    expect(mocks.channelDrawerProps?.initialValues).not.toHaveProperty(
      "app_secret",
    );
    expect(mocks.channelDrawerProps?.initialValues).not.toHaveProperty(
      "bot_token",
    );
    expect(mocks.channelDrawerProps?.initialValues).not.toHaveProperty(
      "password",
    );

    await mocks.channelDrawerProps?.onSubmit({
      ...mocks.channelDrawerProps.initialValues,
    });
    expect(mocks.updateChannelConfig).toHaveBeenCalledOnce();
    expect(mocks.updateChannelConfig).toHaveBeenCalledWith(
      "dingtalk",
      expect.not.objectContaining({
        client_secret: expect.anything(),
        app_secret: expect.anything(),
        bot_token: expect.anything(),
        password: expect.anything(),
      }),
      "agent-b",
    );
  });

  it("removes persisted LiveKit fields from the final dev SIP PUT", async () => {
    mocks.useChannels.mockReturnValue(
      channelsState({
        channels: {
          sip: {
            enabled: false,
            isBuiltin: true,
            sip_mode: "livekit",
            sip_transport: "TLS",
            livekit_url: "wss://persisted.example.test",
            livekit_api_key: "persisted-key",
            livekit_api_secret: "persisted-secret",
            livekit_sip_trunk_id: "persisted-trunk",
            livekit_room_name: "persisted-room",
            livekit_output_sample_rate: 16000,
          },
        },
        orderedKeys: ["sip"],
      }),
    );
    const view = renderWithProviders(<ChannelsPage />);
    fireEvent.click(screen.getByRole("button", { name: "available-sip" }));

    await mocks.channelDrawerProps?.onSubmit({
      sip_mode: "dev",
      sip_transport: "TCP",
      bot_prefix: "adjacent-sentinel",
    });

    expect(mocks.updateChannelConfig).toHaveBeenCalledWith(
      "sip",
      expect.objectContaining({
        sip_mode: "dev",
        sip_transport: "TCP",
        bot_prefix: "adjacent-sentinel",
      }),
      "agent-a",
    );
    const payload = mocks.updateChannelConfig.mock.calls[0][1];
    expect(
      Object.keys(payload).filter((key) => key.startsWith("livekit_")),
    ).toEqual([]);

    const applyLocalUpdate = mocks.setChannels.mock.calls[0][1] as (
      current: Record<string, Record<string, unknown>>,
    ) => Record<string, Record<string, unknown>>;
    const savedChannels = applyLocalUpdate({
      sip: {
        enabled: false,
        isBuiltin: true,
        sip_mode: "livekit",
        livekit_api_secret: "persisted-secret",
      },
    });
    expect(savedChannels.sip).toMatchObject({
      isBuiltin: true,
      sip_mode: "dev",
      sip_transport: "TCP",
      bot_prefix: "adjacent-sentinel",
    });
    expect(
      Object.keys(savedChannels.sip).filter((key) =>
        key.startsWith("livekit_"),
      ),
    ).toEqual([]);

    act(() => mocks.channelDrawerProps?.onClose());
    mocks.useChannels.mockReturnValue(
      channelsState({
        channels: savedChannels,
        orderedKeys: ["sip"],
      }),
    );
    view.rerender(<ChannelsPage />);
    fireEvent.click(screen.getByRole("button", { name: "available-sip" }));
    expect(
      Object.keys(mocks.channelDrawerProps?.initialValues ?? {}).filter((key) =>
        key.startsWith("livekit_"),
      ),
    ).toEqual([]);

    mocks.updateChannelConfig.mockClear();
    await mocks.channelDrawerProps?.onSubmit({
      sip_mode: "dev",
      sip_transport: "UDP",
    });
    const resavedPayload = mocks.updateChannelConfig.mock.calls[0][1];
    expect(
      Object.keys(resavedPayload).filter((key) => key.startsWith("livekit_")),
    ).toEqual([]);
  });

  it.each(["agent-b", "agent-a"])(
    "invalidates agent A's pending conflict proposal after switching through %s",
    async (finalAgent) => {
      let resolveConflict!: (value: {
        conflict: boolean;
        agents: Array<{ agent_id: string; agent_name: string }>;
      }) => void;
      const pendingConflict = new Promise<{
        conflict: boolean;
        agents: Array<{ agent_id: string; agent_name: string }>;
      }>((resolve) => {
        resolveConflict = resolve;
      });
      mocks.checkChannelConflict.mockReturnValueOnce(pendingConflict);

      let currentAgent = "agent-a";
      const stateFor = (agentId: string, ready = true) =>
        channelsState({
          agentId,
          channels: ready
            ? { dingtalk: { enabled: true, isBuiltin: true } }
            : {},
          orderedKeys: ready ? ["dingtalk"] : [],
          loading: !ready,
          ready,
          canMutate: (ownerAgentId: string) => ownerAgentId === currentAgent,
        });
      mocks.useChannels.mockReturnValue(stateFor(currentAgent));
      const view = renderWithProviders(<ChannelsPage />);
      fireEvent.click(screen.getByRole("button", { name: "channel-dingtalk" }));
      const staleSubmit = mocks.channelDrawerProps!.onSubmit({ enabled: true });

      currentAgent = "agent-b";
      mocks.useChannels.mockReturnValue(stateFor(currentAgent, false));
      view.rerender(<ChannelsPage />);
      if (finalAgent === "agent-a") {
        currentAgent = "agent-a";
        mocks.useChannels.mockReturnValue(stateFor(currentAgent));
        view.rerender(<ChannelsPage />);
      }

      resolveConflict({
        conflict: true,
        agents: [{ agent_id: "other", agent_name: "Other" }],
      });
      await staleSubmit;

      expect(mocks.modalConfirm).not.toHaveBeenCalled();
      expect(mocks.updateChannelConfig).not.toHaveBeenCalled();
      expect(mocks.setChannels).not.toHaveBeenCalled();
    },
  );

  it("destroys an open conflict proposal when the agent changes", async () => {
    let confirmProps!: {
      onOk: () => void;
      afterClose: () => void;
    };
    const destroy = vi.fn(() => confirmProps.afterClose());
    mocks.checkChannelConflict.mockResolvedValue({
      conflict: true,
      agents: [{ agent_id: "other", agent_name: "Other" }],
    });
    mocks.modalConfirm.mockImplementation((props) => {
      confirmProps = props;
      return { destroy, update: vi.fn() };
    });

    let currentAgent = "agent-a";
    mocks.useChannels.mockReturnValue(
      channelsState({
        agentId: currentAgent,
        channels: { dingtalk: { enabled: true, isBuiltin: true } },
        orderedKeys: ["dingtalk"],
        canMutate: (ownerAgentId: string) => ownerAgentId === currentAgent,
      }),
    );
    const view = renderWithProviders(<ChannelsPage />);
    fireEvent.click(screen.getByRole("button", { name: "channel-dingtalk" }));
    const staleSubmit = mocks.channelDrawerProps!.onSubmit({ enabled: true });
    await vi.waitFor(() => expect(mocks.modalConfirm).toHaveBeenCalledOnce());

    currentAgent = "agent-b";
    mocks.useChannels.mockReturnValue(
      channelsState({
        agentId: currentAgent,
        loading: true,
        ready: false,
        canMutate: (ownerAgentId: string) => ownerAgentId === currentAgent,
      }),
    );
    view.rerender(<ChannelsPage />);
    await staleSubmit;
    confirmProps.onOk();

    expect(destroy).toHaveBeenCalledOnce();
    expect(mocks.updateChannelConfig).not.toHaveBeenCalled();
    expect(mocks.setChannels).not.toHaveBeenCalled();
  });
});

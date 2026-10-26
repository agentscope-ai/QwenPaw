// @vitest-environment jsdom
import type { ComponentProps } from "react";
import { createElement } from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { FormInstance } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";

const formCapture = vi.hoisted(() => ({
  current: null as FormInstance<Record<string, unknown>> | null,
}));
const mockMessage = vi.hoisted(() => ({
  destroy: vi.fn(),
  error: vi.fn(),
}));

vi.mock("@agentscope-ai/design", async () => {
  const antd = await vi.importActual<typeof import("antd")>("antd");
  const ActualForm = antd.Form;
  const WrappedForm = Object.assign(
    (props: ComponentProps<typeof ActualForm>) =>
      createElement(ActualForm, props),
    ActualForm,
    {
      useForm: () => {
        const result = ActualForm.useForm<Record<string, unknown>>();
        formCapture.current = result[0];
        return result;
      },
    },
  );
  return { ...antd, Form: WrappedForm };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

vi.mock("../../../../stores/agentStore", () => ({
  useAgentStore: Object.assign(
    () => ({
      selectedAgent: "agent-b",
      agents: [{ id: "agent-b", workspace_dir: "/ws" }],
    }),
    { subscribe: () => () => {} },
  ),
}));

vi.mock("../../../../utils/openExternalLink", () => ({
  openExternalLink: vi.fn(),
}));

vi.mock("../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: mockMessage }),
}));

vi.mock("./QrcodeAuthBlock", () => ({
  QrcodeAuthBlock: () => null,
}));

import { ChannelFormDrawer } from "./ChannelFormDrawer";
import { normalizeChannelSubmitValues } from "./channelConfig";

const schema = {
  label: "Custom",
  description: "Custom channel",
  plugin_id: "custom",
  config_fields: [{ name: "label", label: "Label", type: "text" as const }],
};

function drawerProps(initialValues: Record<string, unknown>) {
  return {
    open: true,
    activeKey: "custom",
    activeLabel: "Custom",
    saving: false,
    initialValues,
    isBuiltin: false,
    channelSchema: schema,
    onClose: vi.fn(),
    onSubmit: vi.fn().mockResolvedValue(undefined),
  };
}

beforeEach(() => {
  formCapture.current = null;
  vi.clearAllMocks();
});

describe("ChannelFormDrawer owner isolation", () => {
  it.each([undefined, "legacy-mode"])(
    "fails closed for SIP mode %s",
    (sipMode) => {
      const values = {
        sip_mode: sipMode,
        sip_transport: "TCP",
        livekit_api_secret: "must-not-survive",
      };

      const normalized = normalizeChannelSubmitValues("sip", values);

      expect(normalized).toEqual({
        sip_mode: sipMode,
        sip_transport: "TCP",
      });
      expect(values.livekit_api_secret).toBe("must-not-survive");
    },
  );

  it("remounts the real Ant form and excludes stale secrets from autosave", async () => {
    const agentA = drawerProps({
      enabled: true,
      label: "agent-a",
      client_secret: "agent-a-client-secret",
      app_secret: "agent-a-app-secret",
      bot_token: "agent-a-bot-token",
      password: "agent-a-password",
    });
    const view = render(
      <ChannelFormDrawer
        key="agent-a:custom"
        ownerKey="agent-a:custom"
        {...agentA}
      />,
    );

    await waitFor(() => {
      expect(formCapture.current?.getFieldsValue(true)).toMatchObject({
        client_secret: "agent-a-client-secret",
        app_secret: "agent-a-app-secret",
        bot_token: "agent-a-bot-token",
        password: "agent-a-password",
      });
    });

    const agentB = drawerProps({ enabled: true, label: "agent-b" });
    view.rerender(
      <ChannelFormDrawer
        key="agent-b:custom"
        ownerKey="agent-b:custom"
        {...agentB}
      />,
    );

    await waitFor(() => {
      const values = formCapture.current?.getFieldsValue(true);
      expect(values).toMatchObject({ label: "agent-b" });
      expect(values?.client_secret).toBeUndefined();
      expect(values?.app_secret).toBeUndefined();
      expect(values?.bot_token).toBeUndefined();
      expect(values?.password).toBeUndefined();
    });

    fireEvent.change(screen.getByRole("textbox", { name: "Label" }), {
      target: { value: "agent-b-updated" },
    });
    fireEvent.click(screen.getByRole("button", { name: "common.close" }));

    await waitFor(() => expect(agentB.onSubmit).toHaveBeenCalledOnce());
    expect(agentB.onSubmit).toHaveBeenCalledWith(
      expect.not.objectContaining({
        client_secret: expect.anything(),
        app_secret: expect.anything(),
        bot_token: expect.anything(),
        password: expect.anything(),
      }),
    );
  });

  it("removes hidden LiveKit values only when a dev SIP form submits", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <ChannelFormDrawer
        ownerKey="agent-b:sip"
        open
        activeKey="sip"
        activeLabel="SIP"
        saving={false}
        initialValues={{
          enabled: false,
          sip_mode: "livekit",
          sip_transport: "UDP",
          livekit_url: "wss://draft.example.test",
          livekit_api_key: "draft-key",
          livekit_api_secret: "draft-secret",
          livekit_sip_trunk_id: "draft-trunk",
          livekit_room_name: "draft-room",
          livekit_output_sample_rate: 16000,
        }}
        isBuiltin
        onClose={vi.fn()}
        onSubmit={onSubmit}
      />,
    );

    await waitFor(() =>
      expect(formCapture.current?.getFieldValue("livekit_api_secret")).toBe(
        "draft-secret",
      ),
    );
    act(() => formCapture.current?.setFieldValue("sip_mode", "dev"));
    fireEvent.change(document.querySelector("input#bot_prefix")!, {
      target: { value: "adjacent-sentinel" },
    });
    fireEvent.click(screen.getByRole("button", { name: "common.close" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledOnce());
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        sip_mode: "dev",
        sip_transport: "UDP",
        bot_prefix: "adjacent-sentinel",
      }),
    );
    expect(
      Object.keys(onSubmit.mock.calls[0][0]).filter((key) =>
        key.startsWith("livekit_"),
      ),
    ).toEqual([]);
  });
});

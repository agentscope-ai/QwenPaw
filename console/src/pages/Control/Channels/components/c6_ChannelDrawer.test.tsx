// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
} from "@testing-library/react";
import { Form } from "antd";
import type { FormInstance } from "antd";
import type { ChannelSchema } from "../../../../api/modules/channel";
import type { ChannelQrcodeConfig } from "./useChannelQrcode";

vi.mock("@agentscope-ai/design", async () => vi.importActual("antd"));
vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "en" },
  }),
}));
vi.mock("../../../../stores/agentStore", async () => {
  const { create } = await import("zustand");
  return {
    useAgentStore: create(() => ({
      selectedAgent: "c6-agent",
      agents: [{ id: "c6-agent", workspace_dir: "/ws" }],
    })),
  };
});
vi.mock("../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: {
      destroy: vi.fn(),
      success: vi.fn(),
      error: vi.fn(),
      warning: vi.fn(),
    },
  }),
}));
vi.mock("./QrcodeAuthBlock", () => ({
  QrcodeAuthBlock: (props: ChannelQrcodeConfig) => (
    <button
      data-testid={`c6-qr-${props.channel}`}
      data-poll={props.pollInterval}
      data-domain={props.params?.domain}
      onClick={() =>
        props.onSuccess(
          {
            app_id: "cli_qr",
            app_secret: "test-feishu",
            client_id: "client_qr",
            client_secret: "test-dingtalk",
          },
          { agentId: props.agentId, channel: props.channel, token: "c6-auth" },
          { take: () => true, cancel: vi.fn() },
        )
      }
    >
      QR
    </button>
  ),
}));

vi.mock("../../../../api/modules/channel", () => ({
  channelApi: {
    repairChannel: vi.fn().mockResolvedValue({ status: "inactive" }),
  },
}));
import { channelApi } from "../../../../api/modules/channel";
import { ChannelDrawer } from "./ChannelDrawer";

function c6Drawer(
  key: string,
  values: Record<string, unknown> = {},
  isBuiltin = false,
  channelSchema?: ChannelSchema,
) {
  let form!: FormInstance;
  const onSubmit = vi.fn();
  const onSubmitSnapshot = vi.fn().mockResolvedValue(true);
  function Harness() {
    [form] = Form.useForm();
    return (
      <ChannelDrawer
        open
        activeKey={key}
        activeLabel={key}
        form={form}
        saving={false}
        isBuiltin={isBuiltin}
        initialValues={values}
        onClose={() => {}}
        onSubmit={onSubmit}
        onSubmitSnapshot={onSubmitSnapshot}
        channelSchema={channelSchema}
      />
    );
  }
  const view = render(<Harness />);
  return { ...view, form, onSubmit, onSubmitSnapshot };
}

afterEach(cleanup);

describe("C6 official plugin form parity", () => {
  it.each([
    ["feishu", "app_secret", "app_id", "cli_qr", "2000"],
    ["dingtalk", "client_secret", "client_id", "client_qr", "5000"],
  ])(
    "%s retains QR and password fields with isBuiltin=false",
    async (key, secret, identity, expected, poll) => {
      const { form } = c6Drawer(key);
      const qr = screen.getByTestId(`c6-qr-${key}`);
      expect(qr.getAttribute("data-poll")).toBe(poll);
      expect(
        document.querySelector(`input#${secret}`)?.getAttribute("type"),
      ).toBe("password");
      fireEvent.click(qr);
      await waitFor(() => expect(form.getFieldValue(identity)).toBe(expected));
      expect(form.getFieldValue(secret)).toBe(
        key === "feishu" ? "test-feishu" : "test-dingtalk",
      );
    },
  );

  it.each(["message_type", "cron_message_type"])(
    "DingTalk %s controls required card template",
    async (field) => {
      const { form } = c6Drawer("dingtalk", {
        client_id: "saved",
        client_secret: "test-only",
        [field]: "card",
      });
      expect(screen.getByText("channels.fieldCardTemplateID")).toBeTruthy();
      await expect(
        form.validateFields(["card_template_id"]),
      ).rejects.toMatchObject({
        errorFields: [{ name: ["card_template_id"] }],
      });
    },
  );

  it("DingTalk markdown hides card-only fields", () => {
    c6Drawer("dingtalk", {
      message_type: "markdown",
      cron_message_type: "markdown",
    });
    expect(screen.queryByText("channels.fieldCardTemplateID")).toBeNull();
    expect(screen.getByTestId("c6-qr-dingtalk")).toBeTruthy();
  });

  it("Feishu keeps region default and saved international QR domain", async () => {
    const first = c6Drawer("feishu");
    expect(screen.getByTestId("c6-qr-feishu").getAttribute("data-domain")).toBe(
      "feishu",
    );
    expect(first.form.getFieldValue("domain")).toBe("feishu");
    first.unmount();
    c6Drawer("feishu", {
      domain: "lark",
      app_id: "saved",
      app_secret: "test-only",
    });
    await waitFor(() =>
      expect(
        screen.getByTestId("c6-qr-feishu").getAttribute("data-domain"),
      ).toBe("lark"),
    );
  });
});

function c6JsonSchema(
  required = false,
  defaultValue?: unknown,
  jsonType: "array" | "object" = "array",
): ChannelSchema {
  return {
    label: "Structured",
    description: "",
    plugin_id: "custom",
    config_fields: [
      {
        name: "options",
        label: "Options",
        type: "json",
        json_type: jsonType,
        required,
        ...(defaultValue === undefined ? {} : { default: defaultValue }),
      },
    ],
  };
}

describe("C6 review structured fields and failed runtime", () => {
  it("retains structured default [] as a typed form value", async () => {
    const { form } = c6Drawer("custom", {}, false, c6JsonSchema(false, []));
    expect(form.getFieldValue("options")).toEqual([]);
    await expect(form.validateFields(["options"])).resolves.toEqual({
      options: [],
    });
    expect(
      (document.querySelector("textarea#options") as HTMLTextAreaElement).value,
    ).toBe("[]");
  });

  it("permits an omitted optional structured field", async () => {
    const { form } = c6Drawer("custom", {}, false, c6JsonSchema());
    await expect(form.validateFields(["options"])).resolves.toEqual({
      options: undefined,
    });
  });

  it.each([
    ["array", []],
    ["object", {}],
  ] as const)("accepts required empty JSON %s", async (jsonType, value) => {
    const { form } = c6Drawer(
      "custom",
      { options: value },
      false,
      c6JsonSchema(true, undefined, jsonType),
    );
    await expect(form.validateFields(["options"])).resolves.toEqual({
      options: value,
    });
  });

  it.each([undefined, null])(
    "rejects missing/null required structured value %s",
    async (value) => {
      const { form } = c6Drawer(
        "custom",
        { options: value },
        false,
        c6JsonSchema(true),
      );
      await expect(form.validateFields(["options"])).rejects.toMatchObject({
        errorFields: [{ name: ["options"] }],
      });
    },
  );

  it("saves valid entered JSON as an array", async () => {
    const { onSubmitSnapshot } = c6Drawer(
      "custom",
      {},
      false,
      c6JsonSchema(true),
    );
    const input = document.querySelector(
      "textarea#options",
    ) as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: '[{"scope":"read"}]' } });
    await waitFor(
      () =>
        expect(onSubmitSnapshot).toHaveBeenCalledWith(
          expect.objectContaining({
            agentId: "c6-agent",
            channel: "custom",
            body: expect.objectContaining({ options: [{ scope: "read" }] }),
          }),
        ),
      { timeout: 2000 },
    );
  });

  it.each([false, true])(
    "shows runtime fault independently of repair metadata (%s)",
    async (hasRepair) => {
      const repair = { action: "repair" as const, plugin_id: "feishu" };
      c6Drawer("feishu", {}, false, {
        label: "Feishu",
        description: "",
        plugin_id: "feishu",
        config_fields: [],
        availability: "failed",
        diagnostic: "CHANNEL_DEPENDENCY_ORIGIN_INVALID",
        ...(hasRepair ? { repair } : {}),
      });
      expect(
        screen.getByText("CHANNEL_DEPENDENCY_ORIGIN_INVALID"),
      ).toBeTruthy();
      if (hasRepair) {
        fireEvent.click(screen.getByRole("button", { name: "repair" }));
        await waitFor(() =>
          expect(channelApi.repairChannel).toHaveBeenCalledWith(repair),
        );
      }
    },
  );
});

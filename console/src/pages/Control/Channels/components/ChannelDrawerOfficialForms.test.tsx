// @vitest-environment jsdom
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { Form, type FormInstance } from "antd";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChannelSchema } from "../../../../api/modules/channel";
import type { ChannelQrcodeConfig } from "./useChannelQrcode";

const h = vi.hoisted(() => ({
  t: (key: string, fallback?: unknown) =>
    typeof fallback === "string" ? fallback : key,
  i18n: { language: "en" },
  message: {
    destroy: vi.fn(),
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  },
  credentials: {
    wechat: {
      bot_token: "fixture-wechat-token",
      base_url: "https://wechat.fixture.test",
    },
    qq: {
      app_id: "fixture-qq-app",
      client_secret: "fixture-qq-secret",
      user_openid: "fixture-openid",
    },
    wecom: { bot_id: "fixture-wecom-bot", secret: "fixture-wecom-secret" },
  } as Record<string, Record<string, string>>,
}));
vi.mock("@agentscope-ai/design", async () => vi.importActual("antd"));
vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({ t: h.t, i18n: h.i18n }),
}));
vi.mock("../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: h.message }),
}));
vi.mock("../../../../stores/agentStore", async () => {
  const { create } = await import("zustand");
  return {
    useAgentStore: create(() => ({
      selectedAgent: "official-agent",
      agents: [{ id: "official-agent", workspace_dir: "/fixture" }],
    })),
  };
});
// Only the external QR ceremony is replaced: the real drawer must fill,
// validate, transfer custody, enqueue and submit the scoped immutable job.
vi.mock("./QrcodeAuthBlock", () => ({
  QrcodeAuthBlock: (props: ChannelQrcodeConfig) => (
    <button
      type="button"
      onClick={() => {
        let taken = false;
        let cancelled = false;
        props.onSuccess(
          h.credentials[props.channel],
          {
            agentId: props.agentId,
            channel: props.channel,
            token: `fixture-auth-${props.channel}`,
          },
          {
            take: () => {
              if (cancelled) return false;
              taken = true;
              return true;
            },
            cancel: () => {
              if (!taken) cancelled = true;
            },
          },
        );
      }}
    >
      Authorize {props.channel}
    </button>
  ),
}));

import { ChannelDrawer } from "./ChannelDrawer";

function drawer(
  key: string,
  initialValues: Record<string, unknown> = {},
  isBuiltin = false,
  channelSchema?: ChannelSchema,
) {
  let form!: FormInstance;
  const save = vi.fn().mockResolvedValue(true);
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
        initialValues={initialValues}
        channelSchema={channelSchema}
        onClose={() => {}}
        onSubmit={() => {
          throw new Error("Expected snapshot submission");
        }}
        onSubmitSnapshot={save}
      />
    );
  }
  const view = render(<Harness />);
  return { ...view, form, save };
}

async function closeAndSave(save: ReturnType<typeof vi.fn>) {
  fireEvent.click(screen.getByRole("button", { name: "common.close" }));
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  return save.mock.calls[0][0];
}
function changePrefix() {
  fireEvent.change(document.querySelector("input#bot_prefix")!, {
    target: { value: "changed-prefix" },
  });
}

afterEach(cleanup);

describe("official forms independent of builtin packaging", () => {
  it.each<[string, string, Record<string, string>]>([
    [
      "wechat",
      "bot_token",
      {
        bot_token: "fixture-wechat-token",
        base_url: "https://wechat.fixture.test",
      },
    ],
    [
      "qq",
      "client_secret",
      {
        app_id: "fixture-qq-app",
        client_secret: "fixture-qq-secret",
        user_openid: "fixture-openid",
      },
    ],
    [
      "wecom",
      "secret",
      { bot_id: "fixture-wecom-bot", secret: "fixture-wecom-secret" },
    ],
  ])(
    "%s keeps QR, masked fields and scoped credential saves when isBuiltin=false",
    async (key, secretField, body) => {
      const { form, save } = drawer(key);
      expect(
        document.querySelector(`input#${secretField}`)?.getAttribute("type"),
      ).toBe("password");
      fireEvent.click(screen.getByRole("button", { name: `Authorize ${key}` }));
      await waitFor(() =>
        expect(form.getFieldValue(secretField)).toBe(body[secretField]),
      );
      const job = await closeAndSave(save);
      expect(job).toMatchObject({
        agentId: "official-agent",
        channel: key,
        authSession: `fixture-auth-${key}`,
        body,
      });
    },
  );

  it("Matrix exposes password mode and encryption and saves a password without the old token", async () => {
    const { save } = drawer("matrix", {
      homeserver: "https://matrix.fixture.test",
      user_id: "@bot:fixture.test",
      password: "old-password",
      access_token: "old-token",
      encryption: false,
    });
    expect(screen.getByLabelText("channels.fieldAuthMethod")).toBeTruthy();
    const password = screen.getByPlaceholderText("channels.fieldPassword");
    expect(password.getAttribute("type")).toBe("password");
    fireEvent.change(password, { target: { value: "new-password" } });
    fireEvent.click(
      screen.getByRole("switch", {
        name: /channels.fieldEnableEndtoEndEncryption/,
      }),
    );
    const job = await closeAndSave(save);
    expect(job.body).toMatchObject({
      password: "new-password",
      access_token: "",
      encryption: true,
    });
    expect(job.body).not.toHaveProperty("auth_method");
  });

  it("Telegram retains its official masked credential form and saves with isBuiltin=false", async () => {
    const { save } = drawer("telegram", { bot_token: "old-token" });
    const token = screen.getByPlaceholderText(
      "Telegram bot token from BotFather",
    );
    expect(token.getAttribute("type")).toBe("password");
    fireEvent.change(token, { target: { value: "new-telegram-token" } });
    expect((await closeAndSave(save)).body.bot_token).toBe(
      "new-telegram-token",
    );
  });
});

describe("Matrix credential preservation at actual save boundary", () => {
  it.each([undefined, "legacy-sso"])(
    "preserves both credentials and encryption for auth_method=%s",
    async (mode) => {
      const { form, save } = drawer(
        "matrix",
        {
          homeserver: "https://matrix.fixture.test",
          user_id: "@bot:fixture.test",
          password: "preserved-password",
          access_token: "preserved-token",
          encryption: true,
        },
        true,
      );
      // The opening effect chooses password for saved passwords. Model the
      // absent/unknown form snapshot explicitly after that effect has settled.
      act(() => form.setFieldsValue({ auth_method: mode }));
      expect(form.getFieldsValue(true)).toMatchObject({
        password: "preserved-password",
        access_token: "preserved-token",
        encryption: true,
      });
      changePrefix();
      const job = await closeAndSave(save);
      expect(job.body).toMatchObject({
        password: "preserved-password",
        access_token: "preserved-token",
        encryption: true,
        bot_prefix: "changed-prefix",
      });
      expect(job.body).not.toHaveProperty("auth_method");
    },
  );

  it("explicit token mode clears password and disables encryption", async () => {
    const { form, save } = drawer(
      "matrix",
      {
        homeserver: "https://matrix.fixture.test",
        user_id: "@bot:fixture.test",
        password: "old-password",
        access_token: "preserved-token",
        encryption: true,
      },
      true,
    );
    act(() => form.setFieldsValue({ auth_method: "token" }));
    changePrefix();
    const job = await closeAndSave(save);
    expect(job.body).toMatchObject({
      password: "",
      access_token: "preserved-token",
      encryption: false,
    });
    expect(job.body).not.toHaveProperty("auth_method");
  });
});

describe("custom and fallback compatibility", () => {
  it("unknown plugin schema still renders and saves its own fields", async () => {
    const { save } = drawer("fixture-plugin", {}, false, {
      label: "Fixture",
      description: "",
      plugin_id: "fixture-plugin",
      config_fields: [
        {
          name: "endpoint",
          label: "Plugin endpoint",
          type: "text",
          required: true,
        },
      ],
    });
    fireEvent.change(screen.getByLabelText("Plugin endpoint"), {
      target: { value: "https://plugin.fixture.test" },
    });
    expect((await closeAndSave(save)).body.endpoint).toBe(
      "https://plugin.fixture.test",
    );
  });

  it("unknown plugin without schema keeps its value-based form", async () => {
    const { save } = drawer("fixture-legacy", { custom_option: "old-value" });
    fireEvent.change(screen.getByLabelText("custom_option"), {
      target: { value: "new-value" },
    });
    expect((await closeAndSave(save)).body.custom_option).toBe("new-value");
  });

  it.each(["console", "unknown-builtin"])(
    "%s preserves the builtin fallback and presentation save",
    async (key) => {
      const { save } = drawer(key, { opaque_option: "preserved" }, true);
      expect(screen.queryByLabelText("opaque_option")).toBeNull();
      changePrefix();
      expect((await closeAndSave(save)).body).toMatchObject({
        opaque_option: "preserved",
        bot_prefix: "changed-prefix",
      });
    },
  );
});

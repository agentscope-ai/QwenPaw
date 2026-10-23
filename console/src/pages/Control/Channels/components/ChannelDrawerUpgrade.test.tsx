// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { Form } from "antd";
import type { ChannelSchema } from "../../../../api/modules/channel";

const h = vi.hoisted(() => ({
  t: (key: string, fallback?: unknown) =>
    typeof fallback === "string" ? fallback : key,
  i18n: { language: "en" },
  repair: vi.fn(),
  fetch: vi.fn(),
  apply: vi.fn(),
  cancel: vi.fn(),
  confirm: vi.fn(),
  info: vi.fn(),
  update: vi.fn(),
  destroy: vi.fn(),
  message: {
    destroy: vi.fn(),
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  },
}));
vi.mock("@agentscope-ai/design", async () => vi.importActual("antd"));
vi.mock("antd", async (original) => {
  const actual = await original<typeof import("antd")>();
  return {
    ...actual,
    Modal: Object.assign(actual.Modal, { confirm: h.confirm, info: h.info }),
  };
});
vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({ t: h.t, i18n: h.i18n }),
}));
vi.mock("../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: h.message }),
}));
vi.mock("../../../../stores/agentStore", () => ({
  useAgentStore: Object.assign(
    () => ({
      selectedAgent: "channels-agent",
      agents: [{ id: "channels-agent", workspace_dir: "/fixture" }],
    }),
    { subscribe: () => () => {} },
  ),
}));
vi.mock("../../../../api/modules/channel", () => ({
  channelApi: { repairChannel: h.repair },
}));
vi.mock("../../../../api/modules/plugin", async (original) => ({
  ...(await original<typeof import("../../../../api/modules/plugin")>()),
  fetchDependencyUpgrade: h.fetch,
  applyDependencyUpgrade: h.apply,
  cancelDependencyUpgrade: h.cancel,
}));
vi.mock("../../../../api/config", () => ({
  getApiUrl: (path: string) => `http://channels.test/api${path}`,
}));
vi.mock("../../../../api/authHeaders", () => ({
  buildAuthHeaders: () => ({ "X-Agent-Id": "channels-agent" }),
}));
vi.mock("./QrcodeAuthBlock", () => ({ QrcodeAuthBlock: () => null }));

import { PluginApiError } from "../../../../api/modules/plugin";
import { getPendingUpgradeStorageKey } from "../../../Settings/PluginManager/dependencyUpgrade";
import { ChannelDrawer } from "./ChannelDrawer";

const operation = {
  id: "channel-review",
  plugin_id: "matrix",
  status: "needs_confirmation" as const,
  changes: [
    {
      name: "markdown-it-py",
      current_version: "2.2.0",
      target_version: "3.0.0",
    },
  ],
  affected_instances: [],
  requires_restart: false,
  message: "Review replacement",
  error: null,
  retryable: true,
};
const result = {
  id: "matrix",
  name: "Matrix",
  version: "1",
  description: "",
  loaded: true,
  message: "Installed",
};

function drawer(
  action: "install" | "repair",
  onRuntimeChange = vi.fn(),
  open = true,
) {
  const schema: ChannelSchema = {
    label: "Matrix",
    description: "",
    plugin_id: "matrix",
    config_fields: [],
    availability: "dependencies_missing",
    repair: { action, plugin_id: "matrix", source: "/fixture/matrix" },
  };
  function Harness() {
    const [form] = Form.useForm();
    return (
      <ChannelDrawer
        open={open}
        activeKey="matrix"
        activeLabel="Matrix"
        form={form}
        saving={false}
        isBuiltin={false}
        initialValues={{ enabled: false }}
        onClose={() => {}}
        onSubmit={async () => {}}
        onRuntimeChange={onRuntimeChange}
        channelSchema={schema}
      />
    );
  }
  return { ...render(<Harness />), onRuntimeChange };
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  h.confirm.mockReturnValue({ update: h.update, destroy: h.destroy });
  h.info.mockReturnValue({ update: h.update, destroy: h.destroy });
  h.cancel.mockResolvedValue({ ...operation, status: "cancelled" });
});
afterEach(cleanup);

it.each(["install", "repair"] as const)(
  "channel %s offers review and cancellation leaves runtime callback silent",
  async (action) => {
    h.repair.mockRejectedValue(
      new PluginApiError("Review replacement", 409, {
        code: "DEPENDENCY_UPGRADE_REQUIRED",
        operation,
      }),
    );
    const { onRuntimeChange } = drawer(action);
    fireEvent.click(screen.getByRole("button", { name: action }));
    await waitFor(() => expect(h.confirm).toHaveBeenCalledOnce());
    expect(h.apply).not.toHaveBeenCalled();
    await act(async () => {
      await h.confirm.mock.calls[0][0].onCancel();
    });
    await waitFor(() =>
      expect(h.cancel).toHaveBeenCalledWith("channel-review"),
    );
    expect(onRuntimeChange).not.toHaveBeenCalled();
    expect(h.message.success).not.toHaveBeenCalled();
    expect(h.message.error).not.toHaveBeenCalled();
  },
);

it("ordinary channel repair refreshes runtime once", async () => {
  h.repair.mockResolvedValue({ status: "inactive" });
  const { onRuntimeChange } = drawer("repair");
  fireEvent.click(screen.getByRole("button", { name: "repair" }));
  await waitFor(() => expect(onRuntimeChange).toHaveBeenCalledOnce());
  expect(h.confirm).not.toHaveBeenCalled();
});

it("closed drawer recovers a confirmed operation on Channels reload and refreshes the current view", async () => {
  const key = getPendingUpgradeStorageKey();
  localStorage.setItem(key, JSON.stringify([operation.id]));
  h.fetch.mockResolvedValue({ ...operation, status: "succeeded", result });
  const { onRuntimeChange } = drawer("install", vi.fn(), false);
  await waitFor(() => expect(onRuntimeChange).toHaveBeenCalledOnce());
  expect(h.fetch).toHaveBeenCalledWith("channel-review");
  expect(h.apply).not.toHaveBeenCalled();
  expect(h.repair).not.toHaveBeenCalled();
  expect(h.confirm).not.toHaveBeenCalled();
  expect(localStorage.getItem(key)).toBeNull();
});

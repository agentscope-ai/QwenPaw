import { beforeEach, describe, expect, it, vi } from "vitest";
import { Modal } from "antd";
import { requestWithPluginBusyConfirmation } from "./pluginBusy";

vi.mock("antd", () => ({ Modal: { confirm: vi.fn() } }));
vi.mock("../i18n", () => ({ default: { t: (key: string) => key } }));

const busy = (canInterrupt = true) =>
  new Response(
    JSON.stringify({
      detail: { code: "plugin_busy", can_interrupt: canInterrupt },
    }),
    { status: 409 },
  );

describe("plugin busy confirmation", () => {
  beforeEach(() => vi.clearAllMocks());
  it.each(["update", "uninstall"] as const)(
    "%s waits for consent and retries once",
    async (action) => {
      const first = busy();
      const retry = busy();
      const request = vi
        .fn()
        .mockResolvedValueOnce(first)
        .mockResolvedValue(retry);
      const pending = requestWithPluginBusyConfirmation(request, action);
      await vi.waitFor(() => expect(Modal.confirm).toHaveBeenCalledOnce());
      expect(request.mock.calls).toEqual([[false]]);
      const options = vi.mocked(Modal.confirm).mock.calls[0][0];
      expect(options.okType).toBe("danger");
      expect(options.content).toBe(`pluginManager.busy.${action}.warning`);
      await options.onOk?.();
      expect(await pending).toBe(retry);
      expect(request.mock.calls).toEqual([[false], [true]]);
      expect(Modal.confirm).toHaveBeenCalledOnce();
    },
  );
  it.each(["onCancel", "afterClose"] as const)(
    "%s preserves failure without interrupting",
    async (callback) => {
      const response = busy();
      const request = vi.fn().mockResolvedValue(response);
      const pending = requestWithPluginBusyConfirmation(request, "uninstall");
      await vi.waitFor(() => expect(Modal.confirm).toHaveBeenCalledOnce());
      const options = vi.mocked(Modal.confirm).mock.calls[0][0];
      options[callback]?.();
      expect(await pending).toBe(response);
      expect(request.mock.calls).toEqual([[false]]);
      expect(await response.json()).toMatchObject({
        detail: { code: "plugin_busy" },
      });
    },
  );
  it.each([
    new Response("{}", { status: 200 }),
    new Response(JSON.stringify({ detail: "cleanup failed" }), { status: 409 }),
    new Response("not json", { status: 409 }),
    busy(false),
  ])(
    "does not retry unrelated or non-interruptible responses",
    async (response) => {
      const request = vi.fn().mockResolvedValue(response);
      expect(await requestWithPluginBusyConfirmation(request, "update")).toBe(
        response,
      );
      expect(request.mock.calls).toEqual([[false]]);
      expect(Modal.confirm).not.toHaveBeenCalled();
    },
  );
});

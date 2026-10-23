import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({
  t: (key: string) => key,
  install: vi.fn(),
  catalog: vi.fn(),
  cancel: vi.fn(),
  apply: vi.fn(),
  confirm: vi.fn(),
  info: vi.fn(),
  message: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({ t: h.t }),
}));
vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: h.message }),
}));
vi.mock("@/api/modules/plugin", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/modules/plugin")>()),
  installPlugin: h.install,
  fetchPluginCatalog: h.catalog,
  applyDependencyUpgrade: h.apply,
  cancelDependencyUpgrade: h.cancel,
}));
vi.mock("antd", () => ({ Modal: { confirm: h.confirm, info: h.info } }));
import { PluginApiError } from "@/api/modules/plugin";
import { useOfficialPlugins } from "./useOfficialPlugins";

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  h.catalog.mockResolvedValue({ updated_at: null, plugins: [] });
  h.confirm.mockReturnValue({ update: vi.fn(), destroy: vi.fn() });
  h.info.mockReturnValue({ update: vi.fn(), destroy: vi.fn() });
  h.cancel.mockResolvedValue({ status: "cancelled" });
});

it("official install offers dependency review and cancelling produces no install or error notification", async () => {
  const operation = {
    id: "official-review",
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
    message: "Review change",
    error: null,
    retryable: true,
  };
  h.install.mockRejectedValue(
    new PluginApiError("Review change", 409, {
      code: "DEPENDENCY_UPGRADE_REQUIRED",
      operation,
    }),
  );
  const onInstalled = vi.fn();
  const { result } = renderHook(() => useOfficialPlugins({ onInstalled }));
  await waitFor(() => expect(result.current.loading).toBe(false));
  let installing: Promise<void>;
  act(() => {
    installing = result.current.handleInstall({
      id: "matrix",
      plugin_id: "matrix",
      name: "Matrix",
      description: "",
      version: "0.1",
      author: "",
      kind: "channel",
      size: "1kb",
      sha256: "fixture",
      install_url: "https://example.invalid/matrix.zip",
      installed: false,
      upgrade_available: false,
    });
  });
  await waitFor(() => expect(h.confirm).toHaveBeenCalledOnce());
  expect(h.apply).not.toHaveBeenCalled();
  await act(async () => {
    await h.confirm.mock.calls[0][0].onCancel();
    await installing!;
  });
  expect(h.cancel).toHaveBeenCalledWith("official-review");
  expect(onInstalled).not.toHaveBeenCalled();
  expect(h.message.success).not.toHaveBeenCalled();
  expect(h.message.error).not.toHaveBeenCalled();
});

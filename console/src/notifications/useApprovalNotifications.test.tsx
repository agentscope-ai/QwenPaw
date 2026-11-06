import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useApprovalNotifications } from "./useApprovalNotifications";
import { updateNotificationPreferences } from "./preferences";

const mocks = vi.hoisted(() => ({
  configure: vi.fn(async () => undefined),
  translate: (key: string) => key,
}));

vi.mock("../tauri/backendRuntime", () => ({
  isDesktopApp: () => true,
}));
vi.mock("../tauri/consoleNotifications", () => ({
  configureDesktopApprovalNotifications: mocks.configure,
}));
vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn(async () => () => undefined),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: mocks.translate }),
}));

describe("native approval notification preferences", () => {
  beforeEach(() => {
    localStorage.clear();
    mocks.configure.mockClear();
    updateNotificationPreferences({ enabled: true, approval: true });
  });

  afterEach(() => vi.restoreAllMocks());

  it("updates native timing and keeps foreground reminders behind both switches", async () => {
    renderHook(() => useApprovalNotifications(vi.fn()));
    await waitFor(() =>
      expect(mocks.configure).toHaveBeenLastCalledWith(
        true,
        "approvalNotifications.title",
        "approvalNotifications.body",
        false,
      ),
    );
    act(() => updateNotificationPreferences({ approvalTiming: "always" }));
    await waitFor(() =>
      expect(mocks.configure).toHaveBeenLastCalledWith(
        true,
        "approvalNotifications.title",
        "approvalNotifications.body",
        true,
      ),
    );
    act(() => updateNotificationPreferences({ approval: false }));
    expect(mocks.configure).toHaveBeenLastCalledWith(
      false,
      "approvalNotifications.title",
      "approvalNotifications.body",
      true,
    );
    act(() =>
      updateNotificationPreferences({ approval: true, enabled: false }),
    );
    expect(mocks.configure).toHaveBeenLastCalledWith(
      false,
      "approvalNotifications.title",
      "approvalNotifications.body",
      true,
    );
  });
});

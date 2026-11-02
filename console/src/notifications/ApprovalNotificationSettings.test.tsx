import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { message } from "antd";
import ApprovalNotificationSettings from "./ApprovalNotificationSettings";
import { notificationsEnabled, setNotificationsEnabled } from "./preferences";

const mocks = vi.hoisted(() => ({
  desktop: false,
  getPermission: vi.fn(),
  requestNativePermission: vi.fn(),
}));

vi.mock("../tauri/backendRuntime", () => ({
  isDesktopApp: () => mocks.desktop,
}));
vi.mock("../tauri/consoleNotifications", () => ({
  getDesktopNotificationPermission: mocks.getPermission,
  requestDesktopNotificationPermission: mocks.requestNativePermission,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const requestPermission = vi.fn();
class TestNotification {
  static permission: NotificationPermission = "default";
  static requestPermission = requestPermission;
}

const toggle = () =>
  screen.getByRole("switch", { name: "approvalNotifications.settingTitle" });

describe("approval notification settings", () => {
  beforeEach(() => {
    localStorage.clear();
    mocks.desktop = false;
    mocks.getPermission.mockReset().mockResolvedValue("native");
    mocks.requestNativePermission.mockReset().mockResolvedValue("native");
    requestPermission.mockReset().mockResolvedValue("granted");
    TestNotification.permission = "default";
    vi.stubGlobal("Notification", TestNotification);
    vi.stubGlobal("isSecureContext", true);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("starts disabled and never requests permission on mount", () => {
    render(<ApprovalNotificationSettings />);
    expect(toggle()).not.toBeChecked();
    expect(requestPermission).not.toHaveBeenCalled();
  });

  it("requests permission from the enable interaction and persists consent", async () => {
    render(<ApprovalNotificationSettings />);
    fireEvent.click(toggle());
    await waitFor(() => expect(toggle()).toBeChecked());
    expect(requestPermission).toHaveBeenCalledOnce();
    expect(notificationsEnabled()).toBe(true);
  });

  it("keeps the feature disabled after permission is denied", async () => {
    requestPermission.mockResolvedValue("denied");
    render(<ApprovalNotificationSettings />);
    fireEvent.click(toggle());
    await screen.findByText("approvalNotifications.permission.denied");
    expect(toggle()).not.toBeChecked();
    expect(toggle()).toBeDisabled();
    expect(notificationsEnabled()).toBe(false);
  });

  it("shows previously denied permission without prompting again", () => {
    TestNotification.permission = "denied";
    render(<ApprovalNotificationSettings />);
    expect(toggle()).toBeDisabled();
    expect(requestPermission).not.toHaveBeenCalled();
  });

  it("disables the control when notifications are unavailable", () => {
    vi.stubGlobal("Notification", undefined);
    // Some embedded browsers expose no Notification constructor.
    Reflect.deleteProperty(window, "Notification");
    render(<ApprovalNotificationSettings />);
    expect(toggle()).toBeDisabled();
    expect(
      screen.getByText("approvalNotifications.permission.unsupported"),
    ).toBeVisible();
  });

  it("explains when an insecure origin cannot request notifications", () => {
    vi.stubGlobal("isSecureContext", false);
    render(<ApprovalNotificationSettings />);
    expect(toggle()).toBeDisabled();
    expect(
      screen.getByText("approvalNotifications.permission.insecure"),
    ).toBeVisible();
  });

  it("turns off an enabled setting without requesting permission", () => {
    TestNotification.permission = "granted";
    setNotificationsEnabled(true);
    render(<ApprovalNotificationSettings />);
    fireEvent.click(toggle());
    expect(toggle()).not.toBeChecked();
    expect(notificationsEnabled()).toBe(false);
    expect(requestPermission).not.toHaveBeenCalled();
  });

  it("enables native notifications without asking browser permission", async () => {
    mocks.desktop = true;
    render(<ApprovalNotificationSettings />);
    await screen.findByText("approvalNotifications.permission.native");
    fireEvent.click(toggle());
    await waitFor(() => expect(toggle()).toBeChecked());
    expect(mocks.requestNativePermission).toHaveBeenCalledOnce();
    expect(notificationsEnabled()).toBe(true);
    expect(requestPermission).not.toHaveBeenCalled();
  });

  it("requests real native authorization from the enable click", async () => {
    mocks.desktop = true;
    mocks.getPermission.mockResolvedValue("default");
    mocks.requestNativePermission.mockResolvedValue("granted");
    render(<ApprovalNotificationSettings />);
    await screen.findByText("approvalNotifications.permission.nativeDefault");
    expect(mocks.requestNativePermission).not.toHaveBeenCalled();
    fireEvent.click(toggle());
    await screen.findByText("approvalNotifications.permission.nativeGranted");
    expect(toggle()).toBeChecked();
    expect(mocks.requestNativePermission).toHaveBeenCalledOnce();
    expect(requestPermission).not.toHaveBeenCalled();
  });

  it("keeps native notifications off when system permission is denied", async () => {
    mocks.desktop = true;
    mocks.getPermission.mockResolvedValue("default");
    mocks.requestNativePermission.mockResolvedValue("denied");
    render(<ApprovalNotificationSettings />);
    await screen.findByText("approvalNotifications.permission.nativeDefault");
    fireEvent.click(toggle());
    await screen.findByText("approvalNotifications.permission.nativeDenied");
    expect(toggle()).not.toBeChecked();
    expect(notificationsEnabled()).toBe(false);
  });

  it("does not treat a failed native permission query as consent", async () => {
    mocks.desktop = true;
    mocks.getPermission.mockRejectedValue(new Error("App bundle unavailable"));
    render(<ApprovalNotificationSettings />);
    await screen.findByText("approvalNotifications.permission.unavailable");
    expect(toggle()).toBeDisabled();
  });

  it("keeps focus refreshes from replacing an active native consent request", async () => {
    mocks.desktop = true;
    mocks.getPermission.mockResolvedValue("default");
    let resolvePermission!: (permission: string) => void;
    mocks.requestNativePermission.mockReturnValue(
      new Promise<string>((resolve) => {
        resolvePermission = resolve;
      }),
    );
    render(<ApprovalNotificationSettings />);
    await screen.findByText("approvalNotifications.permission.nativeDefault");
    fireEvent.click(toggle());
    act(() => window.dispatchEvent(new Event("focus")));
    expect(mocks.getPermission).toHaveBeenCalledOnce();
    await act(async () => resolvePermission("granted"));
    await screen.findByText("approvalNotifications.permission.nativeGranted");
    expect(toggle()).toBeChecked();
  });

  it("reports a rejected native permission request", async () => {
    mocks.desktop = true;
    mocks.getPermission.mockResolvedValue("default");
    mocks.requestNativePermission.mockRejectedValue(
      new Error("System rejected permission request"),
    );
    const failure = vi.spyOn(message, "error");
    render(<ApprovalNotificationSettings />);
    await screen.findByText("approvalNotifications.permission.nativeDefault");
    fireEvent.click(toggle());
    await waitFor(() =>
      expect(failure).toHaveBeenCalledWith("approvalNotifications.failed"),
    );
    expect(toggle()).not.toBeChecked();
    expect(notificationsEnabled()).toBe(false);
  });

  it("refreshes the permission indicator after site settings change", async () => {
    render(<ApprovalNotificationSettings />);
    TestNotification.permission = "granted";
    act(() => window.dispatchEvent(new Event("focus")));
    await screen.findByText("approvalNotifications.permission.granted");
  });
});

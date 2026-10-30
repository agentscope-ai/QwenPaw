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
  sendTest: vi.fn(),
  getPermission: vi.fn(),
  requestNativePermission: vi.fn(),
}));

vi.mock("../tauri/backendRuntime", () => ({
  isDesktopApp: () => mocks.desktop,
}));
vi.mock("../tauri/consoleNotifications", () => ({
  sendDesktopTestNotification: mocks.sendTest,
  getDesktopNotificationPermission: mocks.getPermission,
  requestDesktopNotificationPermission: mocks.requestNativePermission,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const created = vi.fn();
const requestPermission = vi.fn();
class TestNotification {
  static permission: NotificationPermission = "default";
  static requestPermission = requestPermission;
  close = vi.fn();
  onclick: (() => void) | null = null;
  constructor(title: string, options: NotificationOptions) {
    created(title, options);
  }
}

const toggle = () =>
  screen.getByRole("switch", { name: "approvalNotifications.settingTitle" });

describe("approval notification settings", () => {
  beforeEach(() => {
    localStorage.clear();
    mocks.desktop = false;
    mocks.sendTest.mockReset().mockResolvedValue(undefined);
    mocks.getPermission.mockReset().mockResolvedValue("native");
    mocks.requestNativePermission.mockReset().mockResolvedValue("native");
    created.mockClear();
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
    expect(
      screen.getByRole("button", { name: "approvalNotifications.sendTest" }),
    ).toBeDisabled();
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

  it("sends a clearly labeled browser test notification", async () => {
    TestNotification.permission = "granted";
    setNotificationsEnabled(true);
    render(<ApprovalNotificationSettings />);
    fireEvent.click(
      screen.getByRole("button", { name: "approvalNotifications.sendTest" }),
    );
    await waitFor(() =>
      expect(created).toHaveBeenCalledWith(
        "approvalNotifications.testTitle",
        expect.objectContaining({ tag: "qwenpaw-approval-notification-test" }),
      ),
    );
  });

  it("uses the native driver inside Tauri without asking browser permission", async () => {
    mocks.desktop = true;
    render(<ApprovalNotificationSettings />);
    await screen.findByText("approvalNotifications.permission.native");
    fireEvent.click(toggle());
    await waitFor(() => expect(toggle()).toBeChecked());
    fireEvent.click(
      screen.getByRole("button", { name: "approvalNotifications.sendTest" }),
    );
    await waitFor(() =>
      expect(mocks.sendTest).toHaveBeenCalledWith(
        "approvalNotifications.testTitle",
        "approvalNotifications.testBody",
      ),
    );
    expect(requestPermission).not.toHaveBeenCalled();
    expect(created).not.toHaveBeenCalled();
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
    fireEvent.click(
      screen.getByRole("button", { name: "approvalNotifications.sendTest" }),
    );
    await waitFor(() => expect(mocks.sendTest).toHaveBeenCalledOnce());
    expect(created).not.toHaveBeenCalled();
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
    expect(mocks.sendTest).not.toHaveBeenCalled();
  });

  it("does not treat a failed native permission query as consent", async () => {
    mocks.desktop = true;
    mocks.getPermission.mockRejectedValue(new Error("App bundle unavailable"));
    render(<ApprovalNotificationSettings />);
    await screen.findByText("approvalNotifications.permission.unavailable");
    expect(toggle()).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "approvalNotifications.sendTest" }),
    ).toBeDisabled();
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

  it("does not report success when the native system rejects delivery", async () => {
    mocks.desktop = true;
    mocks.getPermission.mockResolvedValue("granted");
    mocks.sendTest.mockRejectedValue(new Error("System rejected notification"));
    const success = vi.spyOn(message, "success");
    const failure = vi.spyOn(message, "error");
    setNotificationsEnabled(true);
    render(<ApprovalNotificationSettings />);
    await screen.findByText("approvalNotifications.permission.nativeGranted");
    fireEvent.click(
      screen.getByRole("button", { name: "approvalNotifications.sendTest" }),
    );
    await waitFor(() =>
      expect(failure).toHaveBeenCalledWith("approvalNotifications.failed"),
    );
    expect(success).not.toHaveBeenCalled();
  });

  it("refreshes the permission indicator after site settings change", async () => {
    render(<ApprovalNotificationSettings />);
    TestNotification.permission = "granted";
    act(() => window.dispatchEvent(new Event("focus")));
    await screen.findByText("approvalNotifications.permission.granted");
  });
});

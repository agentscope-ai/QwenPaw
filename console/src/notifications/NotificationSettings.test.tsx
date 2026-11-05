import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "antd";
import NotificationSettings from "./NotificationSettings";
import {
  getNotificationPreferences,
  setNotificationsEnabled,
  updateNotificationPreferences,
} from "./preferences";

const notificationsEnabled = () => getNotificationPreferences().enabled;
function ApprovalNotificationSettings() {
  return (
    <App>
      <NotificationSettings />
    </App>
  );
}

const mocks = vi.hoisted(() => ({
  desktop: false,
  getPermission: vi.fn(),
  requestNativePermission: vi.fn(),
  openSettings: vi.fn(),
}));

vi.mock("../tauri/backendRuntime", () => ({
  isDesktopApp: () => mocks.desktop,
}));
vi.mock("../tauri/consoleNotifications", () => ({
  getDesktopNotificationPermission: mocks.getPermission,
  requestDesktopNotificationPermission: mocks.requestNativePermission,
  openSystemNotificationSettings: mocks.openSettings,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { count?: number }) =>
      options?.count === undefined ? key : `${key}:${options.count}`,
  }),
}));

const requestPermission = vi.fn();
class TestNotification {
  static permission: NotificationPermission = "default";
  static requestPermission = requestPermission;
}

const toggle = () =>
  screen.getByRole("switch", { name: "systemNotifications.enabled" });
const background = () =>
  screen.getByRole("combobox", { name: "systemNotifications.background" });
const chooseSource = (source: string) => {
  if (background().getAttribute("aria-expanded") !== "true") {
    fireEvent.mouseDown(background());
  }
  fireEvent.click(screen.getByTitle(`systemNotifications.${source}`));
};

describe("system notification settings", () => {
  beforeEach(() => {
    localStorage.clear();
    mocks.desktop = false;
    mocks.getPermission.mockReset().mockResolvedValue("native");
    mocks.requestNativePermission.mockReset().mockResolvedValue("native");
    mocks.openSettings.mockReset().mockResolvedValue(undefined);
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

  it("distinguishes granted system permission from enabling app notifications", () => {
    TestNotification.permission = "granted";
    render(<ApprovalNotificationSettings />);
    expect(toggle()).not.toBeChecked();
    expect(screen.getAllByRole("switch")).toHaveLength(1);
    expect(screen.getAllByRole("combobox")).toHaveLength(3);
    expect(background()).toBeDisabled();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(
      screen.queryByText("systemNotifications.browserHelp"),
    ).not.toBeInTheDocument();
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
    await screen.findByText("systemNotifications.browserBlocked");
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
    await waitFor(() => expect(toggle()).not.toBeDisabled());
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
    await waitFor(() => expect(toggle()).not.toBeDisabled());
    expect(mocks.requestNativePermission).not.toHaveBeenCalled();
    fireEvent.click(toggle());
    await waitFor(() => expect(toggle()).toBeChecked());
    expect(mocks.requestNativePermission).toHaveBeenCalledOnce();
    expect(requestPermission).not.toHaveBeenCalled();
  });

  it("keeps native notifications off when system permission is denied", async () => {
    mocks.desktop = true;
    mocks.getPermission.mockResolvedValue("default");
    mocks.requestNativePermission.mockResolvedValue("denied");
    render(<ApprovalNotificationSettings />);
    await waitFor(() => expect(toggle()).not.toBeDisabled());
    fireEvent.click(toggle());
    await screen.findByText("systemNotifications.systemBlocked");
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
    await waitFor(() => expect(toggle()).not.toBeDisabled());
    fireEvent.click(toggle());
    act(() => window.dispatchEvent(new Event("focus")));
    expect(mocks.getPermission).toHaveBeenCalledOnce();
    await act(async () => resolvePermission("granted"));
    await waitFor(() => expect(toggle()).toBeChecked());
    expect(toggle()).toBeChecked();
  });

  it("reports a rejected native permission request", async () => {
    mocks.desktop = true;
    mocks.getPermission.mockResolvedValue("default");
    mocks.requestNativePermission.mockRejectedValue(
      new Error("System rejected permission request"),
    );
    render(<ApprovalNotificationSettings />);
    await waitFor(() => expect(toggle()).not.toBeDisabled());
    fireEvent.click(toggle());
    await screen.findByText("approvalNotifications.failed");
    expect(toggle()).not.toBeChecked();
    expect(notificationsEnabled()).toBe(false);
  });

  it("refreshes permission after site settings change without adding normal-state hints", async () => {
    setNotificationsEnabled(true);
    render(<ApprovalNotificationSettings />);
    expect(background()).toBeDisabled();
    TestNotification.permission = "granted";
    act(() => window.dispatchEvent(new Event("focus")));
    await waitFor(() => expect(background()).not.toBeDisabled());
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("preserves and restores all category choices across the master toggle", async () => {
    TestNotification.permission = "granted";
    setNotificationsEnabled(true);
    updateNotificationPreferences({
      conversation: "always",
      approvalTiming: "always",
      cron: true,
      heartbeat: true,
    });
    render(<ApprovalNotificationSettings />);
    chooseSource("mail");
    fireEvent.click(toggle());
    expect(getNotificationPreferences()).toMatchObject({
      enabled: false,
      conversation: "always",
      approval: true,
      approvalTiming: "always",
      cron: true,
      heartbeat: true,
      mail: true,
    });
    expect(background()).toBeDisabled();
    expect(background()).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.getByRole("combobox", { name: "systemNotifications.approval" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("combobox", {
        name: "systemNotifications.conversation",
      }),
    ).toBeDisabled();
    fireEvent.click(toggle());
    await waitFor(() => expect(toggle()).toBeChecked());
    expect(background()).not.toBeDisabled();
    expect(screen.getByText("systemNotifications.allEnabled")).toBeVisible();
    expect(
      screen.getByRole("combobox", {
        name: "systemNotifications.conversation",
      }),
    ).not.toBeDisabled();
    expect(
      screen.getByRole("combobox", { name: "systemNotifications.approval" }),
    ).not.toBeDisabled();
    expect(screen.getAllByText("systemNotifications.mode.always")).toHaveLength(
      2,
    );
    expect(getNotificationPreferences().conversation).toBe("always");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("lets approvals notify in the foreground without enabling other categories", async () => {
    TestNotification.permission = "granted";
    setNotificationsEnabled(true);
    render(<ApprovalNotificationSettings />);
    expect(screen.getAllByRole("group")).toHaveLength(1);
    fireEvent.mouseDown(
      screen.getByRole("combobox", { name: "systemNotifications.approval" }),
    );
    fireEvent.click(screen.getByText("systemNotifications.mode.always"));
    expect(getNotificationPreferences()).toMatchObject({
      approval: true,
      approvalTiming: "always",
      conversation: "off",
      cron: false,
      heartbeat: false,
      mail: false,
    });
  });

  it("preserves preferences but blocks controls after system permission is revoked", async () => {
    TestNotification.permission = "granted";
    setNotificationsEnabled(true);
    updateNotificationPreferences({ approvalTiming: "always", mail: true });
    render(<ApprovalNotificationSettings />);
    TestNotification.permission = "denied";
    act(() => window.dispatchEvent(new Event("focus")));
    await screen.findByText("systemNotifications.browserBlocked");
    expect(toggle()).toBeChecked();
    expect(toggle()).not.toBeDisabled();
    expect(
      screen.getByRole("combobox", { name: "systemNotifications.approval" }),
    ).toBeDisabled();
    expect(background()).toBeDisabled();
    expect(getNotificationPreferences()).toMatchObject({
      enabled: true,
      approval: true,
      approvalTiming: "always",
      mail: true,
    });
    TestNotification.permission = "granted";
    act(() => window.dispatchEvent(new Event("focus")));
    await waitFor(() => expect(background()).not.toBeDisabled());
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(
      screen.getByRole("combobox", { name: "systemNotifications.approval" }),
    ).not.toBeDisabled();
  });

  it("opens native system settings and refreshes permission on return", async () => {
    mocks.desktop = true;
    mocks.getPermission.mockResolvedValue("denied");
    render(<ApprovalNotificationSettings />);
    await screen.findByText("systemNotifications.systemBlocked");
    fireEvent.click(
      screen.getByRole("button", {
        name: "systemNotifications.allowInSettings",
      }),
    );
    expect(mocks.openSettings).toHaveBeenCalledOnce();
    mocks.getPermission.mockResolvedValue("granted");
    act(() => window.dispatchEvent(new Event("focus")));
    await waitFor(() => expect(toggle()).not.toBeDisabled());
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("saves each background source immediately and keeps the multi-select open", () => {
    TestNotification.permission = "granted";
    setNotificationsEnabled(true);
    render(<ApprovalNotificationSettings />);
    chooseSource("cron");
    expect(
      screen.getByText("systemNotifications.selectedCount:1"),
    ).toBeVisible();
    expect(getNotificationPreferences()).toMatchObject({
      cron: true,
      heartbeat: false,
      mail: false,
      approval: true,
      conversation: "off",
    });
    expect(background()).toHaveAttribute("aria-expanded", "true");
    chooseSource("heartbeat");
    expect(
      screen.getByText("systemNotifications.selectedCount:2"),
    ).toBeVisible();
    chooseSource("mail");
    expect(screen.getByText("systemNotifications.allEnabled")).toBeVisible();
    chooseSource("cron");
    chooseSource("mail");
    expect(getNotificationPreferences()).toMatchObject({
      cron: false,
      heartbeat: true,
      mail: false,
    });
    chooseSource("heartbeat");
    expect(getNotificationPreferences()).toMatchObject({
      cron: false,
      heartbeat: false,
      mail: false,
    });
    expect(background()).toHaveAttribute("aria-expanded", "true");
  });

  it("restores saved background sources when the settings are reopened", () => {
    TestNotification.permission = "granted";
    updateNotificationPreferences({ enabled: true, cron: true, mail: true });
    const first = render(<ApprovalNotificationSettings />);
    chooseSource("cron");
    first.unmount();
    render(<ApprovalNotificationSettings />);
    expect(
      screen.getByText("systemNotifications.selectedCount:1"),
    ).toBeVisible();
    expect(getNotificationPreferences()).toMatchObject({
      cron: false,
      heartbeat: false,
      mail: true,
    });
  });

  it("shows browser permission instructions only when help is requested", async () => {
    TestNotification.permission = "denied";
    render(<ApprovalNotificationSettings />);
    expect(
      screen.queryByText("systemNotifications.browserHelp"),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", {
        name: "systemNotifications.showBrowserHelp",
      }),
    );
    await screen.findByText("systemNotifications.browserHelp");
    expect(requestPermission).not.toHaveBeenCalled();
  });

  it("keeps the system settings entry in help when permission is granted", async () => {
    mocks.desktop = true;
    mocks.getPermission.mockResolvedValue("granted");
    render(<ApprovalNotificationSettings />);
    await waitFor(() => expect(toggle()).not.toBeDisabled());
    expect(
      screen.queryByRole("button", {
        name: "systemNotifications.openSettings",
      }),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "systemNotifications.help" }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "systemNotifications.openSettings",
      }),
    );
    expect(mocks.openSettings).toHaveBeenCalledOnce();
  });

  it("can request missing permission without resetting saved category choices", async () => {
    updateNotificationPreferences({ enabled: true, mail: true });
    render(<ApprovalNotificationSettings />);
    expect(background()).toBeDisabled();
    fireEvent.click(
      screen.getByRole("button", { name: "systemNotifications.authorize" }),
    );
    await waitFor(() => expect(background()).not.toBeDisabled());
    expect(requestPermission).toHaveBeenCalledOnce();
    expect(getNotificationPreferences().mail).toBe(true);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

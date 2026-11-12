import { act, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useDesktopTrayLabels } from "../tauri/useDesktopTrayLabels";

const mocks = vi.hoisted(() => ({
  native: true,
  invoke: vi.fn(),
  loadLanguages: vi.fn(),
  on: vi.fn(),
  off: vi.fn(),
  getFixedT: vi.fn(),
  i18n: {} as Record<string, unknown>,
}));

vi.mock("@tauri-apps/api/core", () => ({ invoke: mocks.invoke }));
vi.mock("../tauri/backendRuntime", () => ({
  isDesktopApp: () => mocks.native,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ i18n: mocks.i18n }),
}));

function Harness() {
  useDesktopTrayLabels();
  return null;
}

describe("native tray labels", () => {
  beforeEach(() => {
    mocks.native = true;
    mocks.invoke.mockReset().mockResolvedValue(undefined);
    mocks.loadLanguages.mockReset().mockResolvedValue(undefined);
    mocks.on.mockReset();
    mocks.off.mockReset();
    mocks.getFixedT
      .mockReset()
      .mockImplementation((lang) => (key: string) => `${lang}:${key}`);
    mocks.i18n = {
      language: "zh",
      resolvedLanguage: "en",
      loadLanguages: mocks.loadLanguages,
      on: mocks.on,
      off: mocks.off,
      getFixedT: mocks.getFixedT,
    };
  });

  it("loads the selected locale before sending native labels", async () => {
    let loaded!: () => void;
    mocks.loadLanguages.mockReturnValue(
      new Promise<void>((resolve) => {
        loaded = resolve;
      }),
    );
    render(<Harness />);
    expect(mocks.loadLanguages).toHaveBeenCalledWith("zh");
    expect(mocks.invoke).not.toHaveBeenCalled();
    await act(async () => loaded());
    expect(mocks.invoke).toHaveBeenCalledWith("set_tray_labels", {
      showWindow: "zh:desktop.closeWindow.showWindow",
      quit: "zh:desktop.closeWindow.quitApp",
      stopBlocked: "zh:desktop.closeWindow.stopBlocked",
      viewApprovals: "zh:approvalNotifications.openApprovals",
    });
  });

  it("keeps a slower earlier load from replacing the latest language", async () => {
    let firstLoaded!: () => void;
    mocks.loadLanguages
      .mockReturnValueOnce(
        new Promise<void>((resolve) => {
          firstLoaded = resolve;
        }),
      )
      .mockResolvedValueOnce(undefined);
    render(<Harness />);
    const onLanguage = mocks.on.mock.calls[0][1];
    await act(async () => onLanguage("en"));
    await act(async () => firstLoaded());
    expect(mocks.invoke).toHaveBeenCalledOnce();
    expect(mocks.invoke.mock.calls[0][1].viewApprovals).toBe(
      "en:approvalNotifications.openApprovals",
    );
  });

  it("ignores a locale that finishes loading after unmount", async () => {
    let loaded!: () => void;
    mocks.loadLanguages.mockReturnValue(
      new Promise<void>((resolve) => {
        loaded = resolve;
      }),
    );
    const view = render(<Harness />);
    view.unmount();
    await act(async () => loaded());
    expect(mocks.invoke).not.toHaveBeenCalled();
    expect(mocks.off).toHaveBeenCalledWith(
      "languageChanged",
      expect.any(Function),
    );
  });

  it("does not call native code in a browser", async () => {
    mocks.native = false;
    render(<Harness />);
    await act(async () => undefined);
    expect(mocks.loadLanguages).not.toHaveBeenCalled();
    expect(mocks.invoke).not.toHaveBeenCalled();
  });
});

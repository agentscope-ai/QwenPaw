import { describe, it, expect, vi, beforeEach } from "vitest";

const mocks = vi.hoisted(() => ({
  open: vi.fn(),
  isDesktopTauriRuntime: vi.fn(),
  nativePickerAvailable: vi.fn(),
  openNativePicker: vi.fn(),
}));

vi.mock("@tauri-apps/plugin-dialog", () => ({ open: mocks.open }));
vi.mock("./openExternalLink", () => ({
  isDesktopTauriRuntime: mocks.isDesktopTauriRuntime,
}));
vi.mock("../api/modules/projectDirectory", () => ({
  projectDirectoryApi: {
    nativePickerAvailable: mocks.nativePickerAvailable,
    openNativePicker: mocks.openNativePicker,
  },
}));

import {
  isNativeDirectoryPickerAvailable,
  pickDirectory,
  resetNativeDirectoryPickerCache,
  PICK_CANCELLED,
} from "./pickDirectory";

describe("pickDirectory", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetNativeDirectoryPickerCache();
    mocks.isDesktopTauriRuntime.mockReturnValue(false);
    mocks.nativePickerAvailable.mockResolvedValue({ available: true });
    mocks.openNativePicker.mockResolvedValue({
      path: "/repos/app",
      cancelled: false,
    });
  });

  describe("availability", () => {
    it("is always true under Tauri without asking the backend", async () => {
      mocks.isDesktopTauriRuntime.mockReturnValue(true);

      expect(await isNativeDirectoryPickerAvailable()).toBe(true);
      expect(mocks.nativePickerAvailable).not.toHaveBeenCalled();
    });

    it("asks the backend once and caches the answer", async () => {
      // Platform and display do not change while the console is open.
      expect(await isNativeDirectoryPickerAvailable()).toBe(true);
      expect(await isNativeDirectoryPickerAvailable()).toBe(true);

      expect(mocks.nativePickerAvailable).toHaveBeenCalledTimes(1);
    });

    it("treats a probe failure as unavailable", async () => {
      // A console served from another machine has no endpoint to ask.
      mocks.nativePickerAvailable.mockRejectedValue(new Error("404"));

      expect(await isNativeDirectoryPickerAvailable()).toBe(false);
    });
  });

  describe("under Tauri", () => {
    beforeEach(() => mocks.isDesktopTauriRuntime.mockReturnValue(true));

    it("returns the path from the dialog plugin", async () => {
      mocks.open.mockResolvedValue("/repos/picked");

      expect(await pickDirectory()).toBe("/repos/picked");
      expect(mocks.open).toHaveBeenCalledWith(
        expect.objectContaining({ directory: true, multiple: false }),
      );
    });

    it("reports cancellation distinctly from a path", async () => {
      mocks.open.mockResolvedValue(null);

      expect(await pickDirectory()).toBe(PICK_CANCELLED);
    });

    it("unwraps an array result defensively", async () => {
      // `multiple: false` should give a string; stringifying an array
      // would otherwise produce a bogus path.
      mocks.open.mockResolvedValue(["/repos/first"]);

      expect(await pickDirectory()).toBe("/repos/first");
    });

    it("never calls the backend", async () => {
      mocks.open.mockResolvedValue("/repos/picked");

      await pickDirectory();

      expect(mocks.openNativePicker).not.toHaveBeenCalled();
    });
  });

  describe("in a plain browser", () => {
    it("delegates to the backend dialog", async () => {
      expect(await pickDirectory({ title: "Pick one" })).toBe("/repos/app");
      expect(mocks.openNativePicker).toHaveBeenCalledWith("Pick one");
    });

    it("reports cancellation", async () => {
      mocks.openNativePicker.mockResolvedValue({
        path: null,
        cancelled: true,
      });

      expect(await pickDirectory()).toBe(PICK_CANCELLED);
    });

    it("propagates a backend failure so the caller can fall back", async () => {
      mocks.openNativePicker.mockRejectedValue(new Error("no display"));

      await expect(pickDirectory()).rejects.toThrow("no display");
    });
  });
});

/**
 * useInstallModal — plugin install modal orchestration: local zip/folder
 * selection (picker + drag-drop), zip packaging, URL install, and the
 * reload-guarded success flow.
 * Regression family: settings round-trip (installed plugin shows up) and
 * double-submit protection while installing.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import React from "react";

const mocks = vi.hoisted(() => ({
  installPlugin: vi.fn(),
  uploadPlugin: vi.fn(),
  readDirEntry: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
  reload: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: {
      success: mocks.success,
      error: mocks.error,
      warning: mocks.warning,
    },
  }),
}));

vi.mock("@/api/modules/plugin", () => ({
  installPlugin: (...a: unknown[]) => mocks.installPlugin(...a),
  uploadPlugin: (...a: unknown[]) => mocks.uploadPlugin(...a),
}));

vi.mock("../utils", () => ({
  readDirEntry: (...a: unknown[]) => mocks.readDirEntry(...a),
}));

vi.mock("jszip", () => ({
  default: class {
    private files: Record<string, unknown> = {};
    file(path: string, data: unknown) {
      this.files[path] = data;
    }
    async generateAsync() {
      return new Blob([`zip:${Object.keys(this.files).join(",")}`]);
    }
  },
}));

// Controllable antd Form: a real Form instance needs a mounted <Form> to
// validate, which renderHook does not provide. Back the hook's form with
// a store of our own.
const formStore = vi.hoisted(() => ({
  values: {} as Record<string, unknown>,
  shouldReject: false,
}));

vi.mock("antd", () => ({
  Form: {
    useForm: () => [
      {
        validateFields: () => {
          if (formStore.shouldReject) {
            return Promise.reject(new Error("invalid"));
          }
          return Promise.resolve({ ...formStore.values });
        },
        resetFields: () => {
          formStore.values = {};
        },
        setFieldsValue: (v: Record<string, unknown>) => {
          formStore.values = { ...formStore.values, ...v };
        },
      },
    ],
  },
}));

import { useInstallModal } from "./useInstallModal";

let realLocation: Location;

beforeEach(() => {
  formStore.values = {};
  formStore.shouldReject = false;
  mocks.installPlugin.mockReset().mockResolvedValue({ name: "plug" });
  mocks.uploadPlugin.mockReset().mockResolvedValue({ name: "localplug" });
  mocks.readDirEntry.mockReset().mockResolvedValue([]);
  mocks.success.mockClear();
  mocks.error.mockClear();
  mocks.warning.mockClear();
  // window.location.reload is not writable in jsdom; replace the whole
  // location object via defineProperty on window.
  realLocation = window.location;
  Object.defineProperty(window, "location", {
    value: { ...realLocation, reload: mocks.reload },
    writable: true,
    configurable: true,
  });
});

afterEach(() => {
  Object.defineProperty(window, "location", {
    value: realLocation,
    writable: true,
    configurable: true,
  });
  vi.clearAllMocks();
});

describe("useInstallModal", () => {
  it("opens and closes the modal", () => {
    const { result } = renderHook(() => useInstallModal(vi.fn()));
    expect(result.current.installOpen).toBe(false);
    act(() => {
      result.current.openModal();
    });
    expect(result.current.installOpen).toBe(true);
    act(() => {
      result.current.closeModal();
    });
    expect(result.current.installOpen).toBe(false);
    expect(result.current.localSel).toBeNull();
  });

  it("blocks closing while a local install is in flight", () => {
    mocks.uploadPlugin.mockReturnValue(new Promise(() => {})); // never resolves
    const { result } = renderHook(() => useInstallModal(vi.fn()));
    act(() => {
      result.current.openModal();
    });
    // Simulate an in-flight local install by setting state through pick+install
    const file = new File(["z"], "p.zip");
    act(() => {
      result.current.handleZipPicked({
        target: { files: [file], value: "" },
      } as unknown as React.ChangeEvent<HTMLInputElement>);
    });
    act(() => {
      void result.current.handleInstallLocal();
    });
    expect(result.current.localInstalling).toBe(true);
    act(() => {
      result.current.closeModal();
    });
    // Still open because installing
    expect(result.current.installOpen).toBe(true);
  });

  it("picks a zip file via the hidden input", () => {
    const { result } = renderHook(() => useInstallModal(vi.fn()));
    const file = new File(["data"], "myplugin.zip");
    act(() => {
      result.current.handleZipPicked({
        target: { files: [file], value: "" },
      } as unknown as React.ChangeEvent<HTMLInputElement>);
    });
    expect(result.current.localSel).toEqual({
      kind: "zip",
      name: "myplugin.zip",
      file,
    });
  });

  it("ignores a pick event without files", () => {
    const { result } = renderHook(() => useInstallModal(vi.fn()));
    act(() => {
      result.current.handleZipPicked({
        target: { files: [], value: "" },
      } as unknown as React.ChangeEvent<HTMLInputElement>);
    });
    expect(result.current.localSel).toBeNull();
  });

  it("tracks drag-over state", () => {
    const { result } = renderHook(() => useInstallModal(vi.fn()));
    const evt = { preventDefault: vi.fn(), stopPropagation: vi.fn() };
    act(() => {
      result.current.handleDragOver(evt as unknown as React.DragEvent);
    });
    expect(result.current.dragOver).toBe(true);
    act(() => {
      result.current.handleDragLeave(evt as unknown as React.DragEvent);
    });
    expect(result.current.dragOver).toBe(false);
  });

  it("accepts a dropped zip file and rejects non-zip files", async () => {
    const { result } = renderHook(() => useInstallModal(vi.fn()));
    const zipFile = new File(["z"], "good.zip");

    const makeDrop = (entry: object, files: File[]) =>
      ({
        preventDefault: vi.fn(),
        stopPropagation: vi.fn(),
        dataTransfer: {
          items: [{ webkitGetAsEntry: () => entry }],
          files,
        },
      }) as unknown as React.DragEvent;

    await act(async () => {
      await result.current.handleDrop(
        makeDrop({ isDirectory: false, isFile: true }, [zipFile]),
      );
    });
    expect(result.current.localSel).toEqual({
      kind: "zip",
      name: "good.zip",
      file: zipFile,
    });

    const txtFile = new File(["t"], "notes.txt");
    await act(async () => {
      await result.current.handleDrop(
        makeDrop({ isDirectory: false, isFile: true }, [txtFile]),
      );
    });
    expect(mocks.warning).toHaveBeenCalledWith("pluginManager.zipOnly");
  });

  it("reads a dropped folder into entries", async () => {
    mocks.readDirEntry.mockResolvedValue([
      { path: "a.txt", file: new File(["x"], "a.txt") },
    ]);
    const { result } = renderHook(() => useInstallModal(vi.fn()));
    await act(async () => {
      await result.current.handleDrop({
        preventDefault: vi.fn(),
        stopPropagation: vi.fn(),
        dataTransfer: {
          items: [
            {
              webkitGetAsEntry: () => ({
                isDirectory: true,
                isFile: false,
                name: "myfolder",
              }),
            },
          ],
          files: [],
        },
      } as unknown as React.DragEvent);
    });
    expect(mocks.readDirEntry).toHaveBeenCalled();
    expect(result.current.localSel?.kind).toBe("folder");
  });

  it("reports a drop failure when reading the folder throws", async () => {
    mocks.readDirEntry.mockRejectedValue(new Error("read fail"));
    const { result } = renderHook(() => useInstallModal(vi.fn()));
    await act(async () => {
      await result.current.handleDrop({
        preventDefault: vi.fn(),
        stopPropagation: vi.fn(),
        dataTransfer: {
          items: [
            { webkitGetAsEntry: () => ({ isDirectory: true, name: "bad" }) },
          ],
          files: [],
        },
      } as unknown as React.DragEvent);
    });
    expect(mocks.error).toHaveBeenCalledWith("pluginManager.dropFailed");
  });

  it("does nothing on a drop without entries", async () => {
    const { result } = renderHook(() => useInstallModal(vi.fn()));
    await act(async () => {
      await result.current.handleDrop({
        preventDefault: vi.fn(),
        stopPropagation: vi.fn(),
        dataTransfer: { items: [] },
      } as unknown as React.DragEvent);
    });
    expect(result.current.localSel).toBeNull();
  });

  it("uploads a picked zip and triggers success + reload", async () => {
    vi.useFakeTimers();
    const onSuccess = vi.fn();
    const { result } = renderHook(() => useInstallModal(onSuccess));
    const file = new File(["z"], "p.zip");
    act(() => {
      result.current.handleZipPicked({
        target: { files: [file], value: "" },
      } as unknown as React.ChangeEvent<HTMLInputElement>);
    });
    await act(async () => {
      await result.current.handleInstallLocal();
    });
    expect(mocks.uploadPlugin).toHaveBeenCalledWith(file);
    expect(onSuccess).toHaveBeenCalled();
    expect(mocks.success).toHaveBeenCalledWith(
      "pluginManager.installSuccess: localplug",
    );
    act(() => {
      vi.advanceTimersByTime(900);
    });
    expect(mocks.reload).toHaveBeenCalled();
    vi.useRealTimers();
  });

  it("packages a dropped folder into a zip before uploading", async () => {
    const onSuccess = vi.fn();
    mocks.readDirEntry.mockResolvedValue([
      { path: "skill.md", file: new File(["m"], "skill.md") },
    ]);
    const { result } = renderHook(() => useInstallModal(onSuccess));
    await act(async () => {
      await result.current.handleDrop({
        preventDefault: vi.fn(),
        stopPropagation: vi.fn(),
        dataTransfer: {
          items: [
            {
              webkitGetAsEntry: () => ({ isDirectory: true, name: "folder1" }),
            },
          ],
          files: [],
        },
      } as unknown as React.DragEvent);
    });
    await act(async () => {
      await result.current.handleInstallLocal();
    });
    const uploaded = mocks.uploadPlugin.mock.calls[0][0] as File;
    expect(uploaded.name).toBe("folder1.zip");
    expect(uploaded.type).toBe("application/zip");
    expect(onSuccess).toHaveBeenCalled();
  });

  it("surfaces upload errors and keeps the modal open", async () => {
    mocks.uploadPlugin.mockRejectedValue(new Error("upload broke"));
    const { result } = renderHook(() => useInstallModal(vi.fn()));
    const file = new File(["z"], "p.zip");
    act(() => {
      result.current.handleZipPicked({
        target: { files: [file], value: "" },
      } as unknown as React.ChangeEvent<HTMLInputElement>);
    });
    await act(async () => {
      await result.current.handleInstallLocal();
    });
    expect(mocks.error).toHaveBeenCalledWith("upload broke");
    expect(result.current.localInstalling).toBe(false);
  });

  it("skips local install without a selection", async () => {
    const { result } = renderHook(() => useInstallModal(vi.fn()));
    await act(async () => {
      await result.current.handleInstallLocal();
    });
    expect(mocks.uploadPlugin).not.toHaveBeenCalled();
  });

  it("installs from a URL after validation", async () => {
    vi.useFakeTimers();
    const onSuccess = vi.fn();
    formStore.values = { source: " https://x.com/p " };
    const { result } = renderHook(() => useInstallModal(onSuccess));
    await act(async () => {
      await result.current.handleInstallUrl();
    });
    expect(mocks.installPlugin).toHaveBeenCalledWith("https://x.com/p");
    expect(onSuccess).toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(900);
    });
    expect(mocks.reload).toHaveBeenCalled();
    vi.useRealTimers();
  });

  it("aborts URL install when validation fails", async () => {
    formStore.shouldReject = true;
    const { result } = renderHook(() => useInstallModal(vi.fn()));
    await act(async () => {
      await result.current.handleInstallUrl();
    });
    expect(mocks.installPlugin).not.toHaveBeenCalled();
    expect(result.current.urlInstalling).toBe(false);
    formStore.shouldReject = false;
  });

  it("surfaces URL install errors", async () => {
    mocks.installPlugin.mockRejectedValue(new Error("bad source"));
    formStore.values = { source: "https://broken" };
    const { result } = renderHook(() => useInstallModal(vi.fn()));
    await act(async () => {
      await result.current.handleInstallUrl();
    });
    expect(mocks.error).toHaveBeenCalledWith("bad source");
    expect(result.current.urlInstalling).toBe(false);
  });

  it("clears the local selection", () => {
    const { result } = renderHook(() => useInstallModal(vi.fn()));
    const file = new File(["z"], "p.zip");
    act(() => {
      result.current.handleZipPicked({
        target: { files: [file], value: "" },
      } as unknown as React.ChangeEvent<HTMLInputElement>);
    });
    act(() => {
      result.current.clearSelection();
    });
    expect(result.current.localSel).toBeNull();
  });
});
